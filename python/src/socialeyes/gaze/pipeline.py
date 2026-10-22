"""One session's eye tracking, start to end: `socialeyes gaze` and the desktop app's Analyse eye
tracking (study_gaze) run the same steps.

1. track the phone in every scene frame of the steps with on-screen tags (tracking.py);
2. score the validation dots and take the session's gaze offset from them (validation.py);
3. map every gaze sample onto the screen, offset applied (mapping.py);
4. place Neon's fixations on the screen and on the post images (fixations.py).

Writes screen_tracking.csv, validation.csv, validation.json, gaze_screen.csv and fixations.csv.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Optional

from .. import settings

FRAME_PROGRESS = Callable[[str, int, int], None]


def analyse_gaze(neon_dir: Path | str, session_dir: Path | str, out: Path | str, build: Optional[Path] = None,
                 offset: bool = True, max_bridge_ms: float = 300.0, study_id: Optional[str] = None,
                 progress: Optional[FRAME_PROGRESS] = None) -> dict:
    """Runs the four steps and writes their files to `out`. `build`: the compiled study the session
    ran (default: the copy kept when it was loaded, found through `study_id`). Returns a summary:
    accuracy (validation.json's), per-step mapping and the fixation counts. Raises on a bad recording
    or session (NeonFormatError, SessionFormatError, ValueError, FileNotFoundError)."""
    from ..session.io import load_session
    from . import validation
    from .fixations import map_fixations, read_fixations
    from .mapping import map_gaze, summary
    from .neon import read_recording
    from .tracking import clock_offset_ns, track_recording

    rec = read_recording(neon_dir)
    session = load_session(session_dir)
    tracking = track_recording(rec, session, max_bridge_ms, progress)
    clock = clock_offset_ns(session)
    dots, shift, accuracy = validation.score(rec, session, tracking, clock)
    if not offset:
        shift = None
    accuracy["offset_applied"] = shift is not None
    dev = session.device
    gaze = map_gaze(rec, tracking, clock, dev["screen_width_px"], dev["screen_height_px"], offset=shift)

    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    tracking.to_csv(out / "screen_tracking.csv", index=False)
    dots.to_csv(out / "validation.csv", index=False)
    (out / "validation.json").write_text(json.dumps(accuracy, indent=1), encoding="utf-8")
    gaze.to_csv(out / "gaze_screen.csv", index=False)
    steps = summary(tracking, gaze)
    result = {"participant_id": session.participant_id, "frames": len(tracking), "accuracy": accuracy,
              "steps": steps.to_dict("records"), "fixations": None, "on_images": None, "build": None}

    if build is None and session.package_sha256 and study_id:
        snap = settings.build_snapshot(study_id, session.package_sha256)
        build = snap if (snap / "study.json").is_file() else None
    result["build"] = str(build) if build else None
    try:
        fix = map_fixations(read_fixations(neon_dir), gaze, session, clock, build)
    except FileNotFoundError as e:
        result["fixations_error"] = str(e)
        return result
    fix.to_csv(out / "fixations.csv", index=False)
    result["fixations"] = len(fix)
    result["on_images"] = int((fix["image_id"].fillna("") != "").sum())
    return result


def feed_mapped(result: dict) -> Optional[float]:
    """Share of the feed's scene frames placed on the screen (by tags or bridged), or None."""
    feed = [s for s in result.get("steps", []) if s["step_id"] == "feed"]
    return round(1 - feed[0]["unmapped"], 3) if feed else None


def study_gaze(study_dir: Path | str, redo: bool = False, progress: Callable[[str], None] = lambda s: None) -> dict:
    """Analyses the eye tracking of every unloaded session that has its Neon recording copied and
    hasn't been analysed yet (``redo``: all of them again). Results go to
    <analysis folder>/<participant>/<session>/, as `socialeyes gaze` puts them, and each session's
    register row gets the feed's mapped share and the accuracy. Returns counts and the sessions skipped."""
    from ..phone.unload import neon_recording, study_id_of
    from ..session import register

    sid = study_id_of(study_dir)
    data, root = settings.data_dir(sid), settings.analysis_dir(sid)
    folders = sorted(p.parent for p in data.glob("*/*/session.json") if not p.parent.parent.name.startswith("."))
    out = {"sessions": len(folders), "analysed": 0, "skipped": [], "results": []}
    rows = []
    for n, folder in enumerate(folders, 1):
        meta = json.loads((folder / "session.json").read_text(encoding="utf-8"))
        uid = meta.get("session_uid") or folder.name
        rid = (meta.get("neon") or {}).get("recording_id")
        if not rid:
            continue   # no eye tracking in this session
        neon = neon_recording(folder)
        if neon is None:
            out["skipped"].append({"session": f"{folder.parent.name}/{folder.name}",
                                   "why": "its Neon recording isn't copied yet (Copy from the phone)"})
            continue
        res_dir = root / folder.parent.name / folder.name
        if (res_dir / "fixations.csv").is_file() and not redo:
            continue
        progress(f"Eye tracking {n} of {len(folders)}: {folder.parent.name}; a few minutes per session…")
        frame_progress = lambda step, k, total: progress(  # noqa: E731
            f"Eye tracking {n} of {len(folders)}: {folder.parent.name}, {step} {round(100 * k / max(total, 1))}%…")
        try:
            r = analyse_gaze(neon, folder, res_dir, study_id=sid, progress=frame_progress)
        except Exception as e:  # one bad recording never stops the rest
            out["skipped"].append({"session": f"{folder.parent.name}/{folder.name}", "why": str(e)})
            continue
        out["analysed"] += 1
        acc = r["accuracy"]
        out["results"].append({"session": f"{folder.parent.name}/{folder.name}", "feed_mapped": feed_mapped(r),
                               "accuracy_deg": acc.get("corrected_deg_median") if acc.get("offset_applied") else acc.get("raw_deg_median"),
                               "offset_applied": acc.get("offset_applied"), "fixations": r["fixations"],
                               "warnings": acc.get("warnings", [])})
        rows.append({"participant_id": meta.get("participant_id", folder.parent.name), "session_uid": uid,
                     "gaze_mapped": feed_mapped(r),
                     "gaze_accuracy_deg": _round(acc.get("corrected_deg_median") if acc.get("offset_applied") else None),
                     "gaze_offset_deg": _round(acc.get("offset_deg"))})
    if rows:
        register.update(data / register.REGISTER, rows)
        second = settings.second_copy_dir(sid)
        if second is not None and second.is_dir():
            import shutil

            shutil.copy2(data / register.REGISTER, second / register.REGISTER)
    return out


def _round(v) -> Optional[float]:
    return None if v is None or v != v else round(float(v), 2)
