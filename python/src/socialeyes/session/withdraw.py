"""Participant withdrawal (``socialeyes withdraw``, the desktop app's Data page), in two steps.

1. **Withdraw** marks the participant ``withdrawn`` in the register and moves every file SocialEyes
   holds for them (their sessions in the data folder and the second copy, and their analysis output)
   into ``withdrawn/<participant>/`` holding folders. They are left out of everything from then on:
   unloading, exports, the exploration page and heatmaps. The study-wide outputs that included them
   (the export tables and the heatmaps) are deleted, to be made again. Nothing is gone yet, so a
   mistake (the wrong id) can be undone: **restore** moves everything back.
2. **Delete permanently** removes the holding folders and, with the phone connected, the
   participant's sessions still on the phone.

The register keeps the participant's rows with their status, and ``withdrawals.csv`` (in the data
folder) logs every step: when, what, how many files, and the Neon recording ids to delete in Neon
Companion or Pupil Cloud, which SocialEyes doesn't hold.
"""
from __future__ import annotations

import csv
import json
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from .. import settings
from . import register

HOLD = "withdrawn"
LOG = "withdrawals.csv"
LOG_COLUMNS = ["at", "participant_id", "action", "sessions", "files", "neon_recordings", "reason"]


@dataclass
class WithdrawResult:
    participant_id: str
    action: str
    sessions: list = field(default_factory=list)          # session uids
    moved: list = field(default_factory=list)             # (from, to) folders
    deleted: list = field(default_factory=list)           # folders deleted
    neon_recordings: list = field(default_factory=list)   # to delete in Companion / Pupil Cloud
    on_phone: list = field(default_factory=list)          # sessions still on the phone
    notes: list = field(default_factory=list)

    def to_json(self) -> dict:
        return asdict(self)


def _places(sid: str) -> list[Path]:
    """The study's folders that hold per-participant files: data, second copy, analysis output."""
    places = [settings.data_dir(sid)]
    second = settings.second_copy_dir(sid)
    if second is not None:
        places.append(second)
    places.append(settings.analysis_dir(sid))
    return places


def _check_id(pid: str) -> str:
    from ..phone.unload import SAFE

    if not pid or not SAFE.fullmatch(pid) or pid in (HOLD, "export", "builds", "heatmaps", "aoi_review"):
        raise ValueError(f"{pid!r} is not a participant id")
    return pid


def _count_files(folder: Path) -> int:
    return sum(1 for p in folder.rglob("*") if p.is_file()) if folder.is_dir() else 0


def _neon_ids(folders: list[Path]) -> list[str]:
    ids = []
    for f in folders:
        for meta in f.glob("*/session.json"):
            try:
                rid = (json.loads(meta.read_text(encoding="utf-8")).get("neon") or {}).get("recording_id")
            except (OSError, ValueError):
                rid = None
            if rid and rid not in ids:
                ids.append(rid)
    return ids


def _log(sid: str, r: WithdrawResult, files: int, reason: str = "") -> None:
    path = settings.data_dir(sid) / LOG
    new = not path.is_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8-sig" if new else "utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=LOG_COLUMNS)
        if new:
            w.writeheader()
        w.writerow({"at": datetime.now().isoformat(timespec="seconds"), "participant_id": r.participant_id,
                    "action": r.action, "sessions": " ".join(r.sessions), "files": files,
                    "neon_recordings": " ".join(r.neon_recordings), "reason": reason})
    second = settings.second_copy_dir(sid)
    if second is not None and second.is_dir():
        shutil.copy2(path, second / LOG)


def _sync_register(sid: str) -> None:
    second = settings.second_copy_dir(sid)
    reg = settings.data_dir(sid) / register.REGISTER
    if second is not None and second.is_dir() and reg.is_file():
        shutil.copy2(reg, second / register.REGISTER)


def _move(src: Path, dest: Path) -> None:
    """Moves the folder's contents into dest (merging with what an earlier step put there)."""
    dest.mkdir(parents=True, exist_ok=True)
    for item in list(src.iterdir()):
        target = dest / item.name
        if target.exists():
            raise OSError(f"{target} exists already; move it away and try again")
        shutil.move(str(item), str(target))
    src.rmdir()


def status(study_dir: Path | str) -> dict:
    """participant id -> "active" / "withdrawn" from the register, and the log's entries."""
    from ..phone.unload import study_id_of

    sid = study_id_of(study_dir)
    rows = register.read(settings.data_dir(sid) / register.REGISTER)[1]
    out = {}
    for r in rows:
        out[r["participant_id"]] = r.get("status") or "active"
    log_path = settings.data_dir(sid) / LOG
    log = list(csv.DictReader(log_path.open(encoding="utf-8-sig", newline=""))) if log_path.is_file() else []
    held = {p.name for p in (settings.data_dir(sid) / HOLD).iterdir()} if (settings.data_dir(sid) / HOLD).is_dir() else set()
    return {"participants": out, "log": log, "held": sorted(held)}


def withdraw(study_dir: Path | str, participant_id: str, reason: str = "") -> WithdrawResult:
    from ..phone.unload import study_id_of

    sid, pid = study_id_of(study_dir), _check_id(participant_id)
    r = WithdrawResult(pid, "withdrawn")
    reg = settings.data_dir(sid) / register.REGISTER
    if pid in register.withdrawn_ids(reg):
        raise ValueError(f"{pid} is withdrawn already")
    sources = [base / pid for base in _places(sid) if (base / pid).is_dir()]
    r.sessions = sorted({p.name for s in sources for p in s.iterdir() if p.is_dir()})
    r.neon_recordings = _neon_ids(sources)
    files = sum(_count_files(s) for s in sources)
    for src in sources:
        dest = src.parent / HOLD / pid
        _move(src, dest)
        r.moved.append((str(src), str(dest)))
    register.set_status(reg, pid, "withdrawn", datetime.now().isoformat(timespec="seconds"))
    _sync_register(sid)
    # study-wide outputs that included them: made again without them
    for pooled in (settings.export_dir(sid), settings.analysis_dir(sid) / "heatmaps"):
        if pooled.is_dir():
            shutil.rmtree(pooled)
            r.deleted.append(str(pooled))
    if r.deleted:
        r.notes.append("the export tables and heatmaps included them and were deleted: make them again")
    if not sources:
        r.notes.append("no files of theirs on this computer (their sessions may still be on the phone)")
    if r.neon_recordings:
        r.notes.append("delete their Neon recording(s) in Neon Companion or Pupil Cloud: " + ", ".join(r.neon_recordings))
    _log(sid, r, files, reason)
    return r


def restore(study_dir: Path | str, participant_id: str) -> WithdrawResult:
    """Undoes a withdrawal that hasn't been deleted permanently yet."""
    from ..phone.unload import study_id_of

    sid, pid = study_id_of(study_dir), _check_id(participant_id)
    r = WithdrawResult(pid, "restored")
    reg = settings.data_dir(sid) / register.REGISTER
    if pid not in register.withdrawn_ids(reg):
        raise ValueError(f"{pid} isn't withdrawn")
    held = [base / HOLD / pid for base in _places(sid) if (base / HOLD / pid).is_dir()]
    if not held and any(e["participant_id"] == pid and e["action"] == "deleted" for e in status(study_dir)["log"]):
        raise ValueError(f"{pid}'s data was deleted permanently; it can't be restored")
    r.sessions = sorted({p.name for h in held for p in h.iterdir() if p.is_dir()})
    files = sum(_count_files(h) for h in held)
    for h in held:
        dest = h.parent.parent / pid
        _move(h, dest)
        r.moved.append((str(h), str(dest)))
        if not any(h.parent.iterdir()):
            h.parent.rmdir()
    register.set_status(reg, pid, "active", datetime.now().isoformat(timespec="seconds"))
    _sync_register(sid)
    r.notes.append("make the tables and heatmaps again to include them")
    _log(sid, r, files)
    return r


def delete_permanently(study_dir: Path | str, participant_id: str, serial: Optional[str] = None,
                       phone: bool = True) -> WithdrawResult:
    """Deletes a withdrawn participant's held files, and (``phone``, if one is connected) their
    sessions on the phone. Can't be undone."""
    from ..phone.adb import APP_FILES, Adb, AdbError
    from ..phone.unload import phone_sessions, study_id_of

    sid, pid = study_id_of(study_dir), _check_id(participant_id)
    r = WithdrawResult(pid, "deleted")
    reg = settings.data_dir(sid) / register.REGISTER
    if pid not in register.withdrawn_ids(reg):
        raise ValueError(f"{pid} isn't withdrawn: withdraw them first")
    held = [base / HOLD / pid for base in _places(sid) if (base / HOLD / pid).is_dir()]
    r.sessions = sorted({p.name for h in held for p in h.iterdir() if p.is_dir()})
    r.neon_recordings = _neon_ids(held)
    files = sum(_count_files(h) for h in held)
    for h in held:
        shutil.rmtree(h)
        r.deleted.append(str(h))
        if not any(h.parent.iterdir()):
            h.parent.rmdir()
    if phone:
        try:
            adb = Adb(serial)
            adb.choose()
            mine = [uid for p, uid in phone_sessions(adb, sid) if p == pid]
            if mine:
                adb.shell(f"rm -r {APP_FILES}/data/{sid}/{pid}", check=True)
                r.deleted.append(f"phone: {len(mine)} session(s)")
                r.sessions = sorted(set(r.sessions) | set(mine))
        except AdbError as e:
            r.notes.append(f"the phone wasn't reachable ({e}): delete again with the phone connected if it "
                           "still holds their sessions")
    if r.neon_recordings:
        r.notes.append("delete their Neon recording(s) in Neon Companion or Pupil Cloud: " + ", ".join(r.neon_recordings))
    _log(sid, r, files)
    return r
