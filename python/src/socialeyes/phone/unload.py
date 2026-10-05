"""Unloading sessions from the phone (``socialeyes unload``, the desktop app's Data tab).

For each session of the study on the phone, in this order:

1. read every file's SHA-256 on the phone;
2. copy it into the study's data folder (via a staging folder) and check every file
   against the phone's hashes;
3. if a second copy folder is set, copy it there too and check that copy;
4. run the session analysis (quality.json etc. in analysis_out/);
5. add or refresh its row in the register (sessions.csv);
6. only then delete it from the phone.

Any failure before step 6 leaves the session on the phone. A session that hasn't
ended while SocialEyes is open on the phone may still be recording: it is copied
but left on the phone.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import yaml

from .. import settings
from ..session import register
from .adb import APP_FILES, PACKAGE, Adb, AdbError
from .loader import build_study, discard, parse_sha256sum

SAFE = re.compile(r"[A-Za-z0-9_.-]+")


@dataclass
class SessionResult:
    participant_id: str
    session_uid: str
    copied: bool = False
    second_copy: Optional[bool] = None   # None: no second copy folder set
    deleted: bool = False
    kept_reason: Optional[str] = None    # why it is still on the phone
    completed: Optional[bool] = None
    warnings: list = field(default_factory=list)
    error: Optional[str] = None


@dataclass
class UnloadResult:
    study_id: Optional[str] = None
    data_dir: Optional[str] = None
    second_copy_dir: Optional[str] = None
    phone: Optional[str] = None
    sessions: list = field(default_factory=list)
    error: Optional[str] = None

    def to_json(self) -> dict:
        return asdict(self)


def study_id_of(study_dir: Path | str) -> str:
    path = Path(study_dir)
    path = path if path.suffix.lower() in (".yaml", ".yml") else path / "study.yaml"
    try:
        sid = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("id")
    except (OSError, yaml.YAMLError) as e:
        raise ValueError(f"can't read {path}: {e}") from e
    if not sid or not SAFE.fullmatch(str(sid)):
        raise ValueError(f"{path} has no valid study id")
    return str(sid)


def local_hashes(folder: Path) -> dict:
    out = {}
    for p in sorted(folder.rglob("*")):
        if p.is_file():
            h = hashlib.sha256()
            with p.open("rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
            out[p.relative_to(folder).as_posix()] = h.hexdigest()
    return out


def phone_sessions(adb: Adb, study_id: str) -> list[tuple[str, str]]:
    """(participant id, session uid) of every session of the study on the phone."""
    out = adb.shell(f"cd {APP_FILES}/data/{study_id} 2>/dev/null && find . -mindepth 2 -maxdepth 2 -type d")
    found = []
    for line in out.splitlines():
        parts = line.strip().removeprefix("./").split("/")
        if len(parts) == 2 and all(SAFE.fullmatch(p) for p in parts):
            found.append((parts[0], parts[1]))
    return sorted(found)


def _replace_dir(staging: Path, final: Path) -> None:
    if final.exists():
        shutil.rmtree(final)
    final.parent.mkdir(parents=True, exist_ok=True)
    staging.replace(final)


def _copy_verified(src: Path, final: Path, expected: dict) -> None:
    staging = final.parent / f".incoming-{final.name}"
    shutil.rmtree(staging, ignore_errors=True)
    shutil.copytree(src, staging)
    if local_hashes(staging) != expected:
        shutil.rmtree(staging, ignore_errors=True)
        raise OSError(f"the copy in {final.parent} doesn't match the phone's files")
    _replace_dir(staging, final)


def _register_row(final: Path, quality: Optional[dict], serial: str) -> dict:
    meta = json.loads((final / "session.json").read_text(encoding="utf-8"))
    dev = meta.get("device", {})
    end = meta.get("end") or {}
    q = quality or {}
    warnings = q.get("warnings", [])
    return {
        "participant_id": meta.get("participant_id", ""),
        "session_uid": meta.get("session_uid") or final.name,
        "started": meta.get("started_wall", ""),
        "phone": f"{dev.get('manufacturer', '')} {dev.get('model', '')} ({serial})".strip(),
        "app_version": meta.get("app_version", ""),
        "completed": "yes" if end.get("reason") == "completed" else "no",
        "end_reason": end.get("reason", "did not end"),
        "duration_s": q.get("duration_s", ""),
        "group_key": meta.get("group_key", ""),
        "package_sha256": meta.get("package_sha256", ""),
        "n_warnings": len(warnings),
        "warnings": "; ".join(warnings),
        "unloaded_at": datetime.now().isoformat(timespec="seconds"),
    }


def unload(study_dir: Path | str, serial: Optional[str] = None,
           progress: Callable[[str], None] = lambda s: None) -> UnloadResult:
    r = UnloadResult()
    build = None
    try:
        r.study_id = sid = study_id_of(study_dir)
        data = settings.data_dir(sid)
        second = settings.second_copy_dir(sid)
        r.data_dir, r.second_copy_dir = str(data), (str(second) if second else None)
        adb = Adb(serial)
        device = adb.choose()
        r.phone = f"{device.model or device.serial} ({device.serial})"
        progress("Looking for sessions on the phone…")
        found = phone_sessions(adb, sid)
        if not found:
            return r
        app_running = bool(adb.shell(f"pidof {PACKAGE}").strip())
        try:
            progress("Compiling the study for the analysis…")
            build = build_study(study_dir)
        except Exception:
            build = None  # analyse without it: quality only, no image/AOI mapping
        for n, (pid, uid) in enumerate(found, 1):
            progress(f"Session {n} of {len(found)}: {pid} ({uid})…")
            s = _unload_one(adb, sid, pid, uid, data, second, build, app_running, device.serial)
            r.sessions.append(s)
        _tidy_phone(adb, sid)
        return r
    except (AdbError, ValueError) as e:
        r.error = str(e)
        return r
    finally:
        discard(build)


def _unload_one(adb: Adb, sid: str, pid: str, uid: str, data: Path, second: Optional[Path],
                build, app_running: bool, serial: str) -> SessionResult:
    s = SessionResult(pid, uid)
    remote = f"{APP_FILES}/data/{sid}/{pid}/{uid}"
    try:
        expected = parse_sha256sum(adb.shell(f"cd {remote} && find . -type f -exec sha256sum {{}} +", timeout=600))
        if "session.json" not in expected:
            s.kept_reason = "no session.json on the phone yet (the session may be starting); left on the phone"
            return s
        meta_text = adb.shell(f"cat {remote}/session.json")
        try:
            ended = bool(json.loads(meta_text).get("end"))
        except ValueError:
            ended = False

        # 1-2: copy into the data folder and check it
        final = data / pid / uid
        if not (final.is_dir() and local_hashes(final) == expected):
            incoming = data / ".incoming"
            shutil.rmtree(incoming / uid, ignore_errors=True)
            incoming.mkdir(parents=True, exist_ok=True)
            adb.run("pull", remote, str(incoming), timeout=3600)
            if local_hashes(incoming / uid) != expected:
                shutil.rmtree(incoming / uid, ignore_errors=True)
                raise OSError("the copied files don't match the phone's; nothing was deleted. Check the cable "
                              "and unload again")
            _replace_dir(incoming / uid, final)
            if not any(incoming.iterdir()):
                incoming.rmdir()
        s.copied = True

        # 3: second copy
        if second is not None:
            _copy_verified(final, second / pid / uid, expected)
            s.second_copy = True

        # 4: analysis (never blocks the unload)
        quality = None
        try:
            from ..session.analyze import analyze_session, write_results

            results = analyze_session(final, build.build if build else None)
            quality = results["quality"]
            write_results(results, settings.analysis_dir(sid) / pid / uid)
            s.completed = quality["completed"]
            s.warnings = quality["warnings"]
        except Exception as e:
            s.warnings = [f"could not analyse this session: {e}"]

        # 5: register (before deleting, so every deleted session is on record)
        on_phone = not ended and app_running
        row = _register_row(final, quality, serial)
        row["on_phone"] = "yes" if on_phone else ""
        if quality is None:
            row["warnings"], row["n_warnings"] = "; ".join(s.warnings), len(s.warnings)
        register.update(data / register.REGISTER, [row])
        if second is not None:
            shutil.copy2(data / register.REGISTER, second / register.REGISTER)

        # 6: delete from the phone
        if on_phone:
            s.kept_reason = ("hasn't ended and SocialEyes is open on the phone, so it may still be recording: "
                             "copied but left on the phone. Close the app and unload again")
        else:
            adb.shell(f"rm -r {remote}", check=True)
            s.deleted = True
    except (OSError, AdbError) as e:
        s.error = str(e)
    return s


def _tidy_phone(adb: Adb, sid: str) -> None:
    """Removes the study's empty participant folders (and the study folder) on the phone."""
    base = f"{APP_FILES}/data/{sid}"
    adb.shell(f"cd {base} 2>/dev/null && for d in */; do rmdir \"$d\" 2>/dev/null; done; cd .. && rmdir {sid} 2>/dev/null; true")
