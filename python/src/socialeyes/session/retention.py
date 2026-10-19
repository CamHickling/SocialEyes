"""Retention: reminders of the data a study should no longer keep (``data:`` in study.yaml), and
where its data lives (``storage``). Nothing is ever deleted without the researcher confirming it.

- ``data.keep_until``: after this date every session of the study is due for deletion
- ``data.face_video_days``: raw front camera videos are due this many days after unloading (the
  face measures and expression scores stay)

``delete_due`` deletes what is due, from this computer only (data folder, second copy and analysis
output), logs it in withdrawals.csv, and keeps the register's rows (status ``deleted``).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

import yaml

from .. import settings
from . import register

CLOUD = ("OneDrive", "Dropbox", "Google Drive", "GoogleDrive", "My Drive", "iCloudDrive", "iCloud Drive", "Box Sync")


def _policy(study_dir: Path | str) -> dict:
    path = Path(study_dir)
    path = path if path.suffix.lower() in (".yaml", ".yml") else path / "study.yaml"
    return ((yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("data") or {})


def _date(v) -> Optional[dt.date]:
    if v in (None, ""):
        return None
    return v if isinstance(v, dt.date) else dt.date.fromisoformat(str(v))


def due(study_dir: Path | str, today: Optional[dt.date] = None) -> dict:
    """What the study's retention rules say is due now: {"keep_until", "past_keep_until", "sessions"
    (participant, session, unloaded), "face_videos" (participant, session, unloaded, files)}."""
    from ..phone.unload import study_id_of

    sid = study_id_of(study_dir)
    today = today or dt.date.today()
    pol = _policy(study_dir)
    keep_until = _date(pol.get("keep_until"))
    days = pol.get("face_video_days")
    data = settings.data_dir(sid)
    rows = {r["session_uid"]: r for r in register.read(data / register.REGISTER)[1]}
    sessions, videos = [], []
    for meta in sorted(data.glob("*/*/session.json")):
        folder = meta.parent
        if folder.parent.name.startswith("."):
            continue
        try:
            uid = json.loads(meta.read_text(encoding="utf-8")).get("session_uid") or folder.name
        except (OSError, ValueError):
            uid = folder.name
        row = rows.get(uid, {})  # the register knows a session by its session_uid
        unloaded = (row.get("unloaded_at") or "")[:10]
        item = {"participant_id": folder.parent.name, "session": folder.name, "unloaded": unloaded}
        if keep_until and today > keep_until:
            sessions.append(item)
        cams = sorted((folder / "camera").glob("front_*.mp4"))
        if days is not None and cams and unloaded and (today - dt.date.fromisoformat(unloaded)).days >= int(days):
            videos.append({**item, "files": len(cams)})
    return {"keep_until": keep_until.isoformat() if keep_until else None, "face_video_days": days,
            "past_keep_until": bool(keep_until and today > keep_until), "sessions": sessions, "face_videos": videos}


def delete_due(study_dir: Path | str, what: str, today: Optional[dt.date] = None) -> dict:
    """Deletes what is due: ``what`` is "face_videos" (the raw videos only) or "sessions" (every
    session past keep_until, with its analysis output). Returns what was deleted."""
    from ..phone.unload import study_id_of
    from .withdraw import WithdrawResult, _log, _sync_register

    if what not in ("face_videos", "sessions"):
        raise ValueError("what must be face_videos or sessions")
    sid = study_id_of(study_dir)
    d = due(study_dir, today)
    places = [settings.data_dir(sid)] + ([settings.second_copy_dir(sid)] if settings.second_copy_dir(sid) else [])
    deleted, files = [], 0
    for item in d[what]:
        pid, uid = item["participant_id"], item["session"]
        for base in places + ([settings.analysis_dir(sid)] if what == "sessions" else []):
            folder = base / pid / uid
            if what == "face_videos":
                for v in sorted((folder / "camera").glob("front_*.mp4")):
                    v.unlink()
                    files += 1
                blurred = settings.analysis_dir(sid) / pid / uid / "camera_blurred"
                if blurred.is_dir() and base == places[0]:
                    files += sum(1 for _ in blurred.iterdir())
                    shutil.rmtree(blurred)
            elif folder.is_dir():
                files += sum(1 for p in folder.rglob("*") if p.is_file())
                shutil.rmtree(folder)
                if not any(folder.parent.iterdir()):
                    folder.parent.rmdir()
        deleted.append(f"{pid}/{uid}")
    if what == "sessions" and deleted:
        reg = settings.data_dir(sid) / register.REGISTER
        for pid in sorted({x.split("/")[0] for x in deleted}):
            register.set_status(reg, pid, "deleted", dt.datetime.now().isoformat(timespec="seconds"))
        _sync_register(sid)
    if deleted:
        r = WithdrawResult("(retention)", "retention: " + ("face videos" if what == "face_videos" else "sessions"),
                           sessions=[x.split("/")[1] for x in deleted])
        _log(sid, r, files, f"keep_until {d['keep_until']}" if what == "sessions" else f"face_video_days {d['face_video_days']}")
    return {"deleted": deleted, "files": files}


# ---------------------------------------------------------------- where the data lives


def bitlocker(path: Path) -> Optional[bool]:
    """Whether Windows reports the drive holding ``path`` as BitLocker-encrypted (no admin rights
    needed); None when it can't say (other systems, network drives)."""
    if os.name != "nt":
        return None
    drive = Path(path).resolve().drive
    if not drive or drive.startswith("\\\\"):
        return None
    cmd = (f"(New-Object -ComObject Shell.Application).NameSpace('{drive}\\').Self."
           "ExtendedProperty('System.Volume.BitLockerProtection')")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd], capture_output=True,
                             text=True, timeout=15, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    # 1 on, 3 encrypting, 6 on (locked); 0 / 2 off or not available; 4 decrypting, 5 suspended
    return {"1": True, "3": True, "6": True, "0": False, "2": False, "4": False, "5": False}.get(out)


def cloud_folder(path: Path) -> Optional[str]:
    """The cloud-sync service whose folder holds ``path``, if any (files there upload themselves)."""
    p = Path(path).resolve()
    for env in ("OneDrive", "OneDriveCommercial", "OneDriveConsumer"):
        root = os.environ.get(env)
        if root:
            try:
                p.relative_to(Path(root).resolve())
                return "OneDrive"
            except ValueError:
                pass
    for part in p.parts:
        for name in CLOUD:
            if part.lower().startswith(name.lower()):
                return name.replace("GoogleDrive", "Google Drive").replace("My Drive", "Google Drive")
    return None


def storage(study_dir: Path | str) -> list[dict]:
    """The data folder and second copy: path, encrypted drive (True/False/None), cloud-sync service."""
    from ..phone.unload import study_id_of

    sid = study_id_of(study_dir)
    out = []
    for name, path in (("data", settings.data_dir(sid)), ("second copy", settings.second_copy_dir(sid))):
        if path is None:
            continue
        out.append({"folder": name, "path": str(path), "encrypted": bitlocker(path), "cloud": cloud_folder(path)})
    return out
