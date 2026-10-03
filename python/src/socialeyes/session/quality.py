"""Session-level data quality summary."""
from __future__ import annotations

import numpy as np

from .io import Session

THERMAL_LEVELS = ("none", "light", "moderate", "severe", "critical", "emergency", "shutdown")


def session_quality(s: Session) -> dict:
    """Numbers and warnings to decide whether a session is usable."""
    warnings: list[str] = []
    end = s.meta.get("end") or {}
    completed = end.get("reason") == "completed"
    if not end:
        warnings.append("session did not end normally (no end in session.json): crash or battery?")
    elif not completed:
        warnings.append(f"session ended with reason {end.get('reason')!r}")

    ev = s.events
    types = ev["type"] if len(ev) else []

    # time in background: background -> next foreground (or session end)
    background_s = 0.0
    n_background = 0
    since = None
    for _, e in s.events_of("app_state").iterrows():
        if e["state"] == "background" and since is None:
            since, n_background = int(e["t_ns"]), n_background + 1
        elif e["state"] == "foreground" and since is not None:
            background_s += (int(e["t_ns"]) - since) / 1e9
            since = None
    if since is not None:
        background_s += (s.end_ns - since) / 1e9
    if n_background:
        warnings.append(f"app was in the background {n_background} time(s), {background_s:.1f} s in total")

    interruptions = s.events_of("interruption")
    by_kind = interruptions["kind"].value_counts().to_dict() if len(interruptions) else {}
    if by_kind:
        warnings.append(f"interruptions: {by_kind}")

    jank = s.events_of("jank")
    frames_dropped = int(jank["frames_dropped"].sum()) if len(jank) else 0
    longest_frame_ms = float(jank["longest_frame_ms"].max()) if len(jank) else 0.0
    if longest_frame_ms > 250:
        warnings.append(f"the screen froze for up to {longest_frame_ms:.0f} ms")

    slept_s = None
    c0, c1 = s.meta.get("clock"), end.get("clock")
    if c0 and c1 and "uptime_ns" in c0 and "uptime_ns" in c1:
        slept_s = ((c1["elapsed_ns"] - c1["uptime_ns"]) - (c0["elapsed_ns"] - c0["uptime_ns"])) / 1e9
        if slept_s > 0.5:
            warnings.append(f"the phone was asleep for {slept_s:.1f} s during the session")

    neon = s.events_of("neon")
    disconnects = int((neon["status"] == "disconnected").sum()) if len(neon) else 0
    if disconnects:
        warnings.append(f"Neon disconnected {disconnects} time(s)")
    rotations = s.events_of("orientation")
    n_rotations = int((rotations["rotation"] != 0).sum()) if len(rotations) else 0
    if n_rotations:
        warnings.append("the screen rotated away from portrait; touch and viewport coordinates change with it")

    thermal = s.events_of("thermal")
    thermal_max = (max(thermal["status"], key=THERMAL_LEVELS.index) if len(thermal) else None)
    if thermal_max and THERMAL_LEVELS.index(thermal_max) >= THERMAL_LEVELS.index("moderate"):
        warnings.append(f"the phone got hot (thermal status {thermal_max!r}); Android may have slowed it down")

    camera = camera_quality(s)
    if camera:
        warnings += camera.pop("warnings")

    feed_start, feed_end = s.feed_window()
    return {
        "participant_id": s.participant_id,
        "session_uid": s.meta.get("session_uid"),
        "completed": completed,
        "end_reason": end.get("reason"),
        "duration_s": round((s.end_ns - s.start_ns) / 1e9, 3),
        "feed_duration_s": round((feed_end - feed_start) / 1e9, 3),
        "n_events": int(len(ev)),
        "n_touch_samples": int(len(s.touch)) if s.touch is not None else None,
        "n_viewport_frames": int((s.viewport["element"] == "frame").sum()),
        "n_sensor_samples": int(len(s.sensors)) if s.sensors is not None else None,
        "background_s": round(background_s, 3),
        "n_background": n_background,
        "interruptions": by_kind,
        "frames_dropped": frames_dropped,
        "longest_frame_ms": longest_frame_ms,
        "slept_s": slept_s,
        "neon_disconnects": disconnects,
        "orientation_changes": n_rotations,
        "thermal_max": thermal_max,
        "camera": camera,
        "event_types": dict(sorted(ev["type"].value_counts().to_dict().items())) if len(types) else {},
        "warnings": warnings,
    }


def camera_quality(s: Session) -> dict | None:
    """Front-camera checks: missing or broken segments, dropped frames, coverage."""
    cfg = s.meta.get("logging", {}).get("front_camera", {})
    if not cfg.get("enabled") and s.camera_frames is None:
        return None
    warnings: list[str] = []
    out: dict = {}
    info = s.meta.get("camera", {})
    if info.get("timestamp_source") == "unknown":
        warnings.append("camera timestamps were not on the realtime clock; video timing may be off")
    fps = float(info.get("fps") or cfg.get("fps", 30))
    interval = 1e9 / fps

    cf = s.camera_frames.sort_values(["segment", "frame"])
    recorded_ns, dropped, n_frames = 0, 0, 0
    segments = []
    for seg, g in cf.groupby("segment"):
        times = g["t_ns"].to_numpy(np.int64)
        gaps = np.diff(times)
        seg_dropped = int(np.clip(np.round(gaps / interval) - 1, 0, None).sum())
        dropped += seg_dropped
        n_frames += len(g)
        recorded_ns += int(times[-1] - times[0]) + int(interval)
        segments.append({"segment": int(seg), "frames": int(len(g)), "dropped": seg_dropped,
                         "file": f"camera/front_{int(seg):03d}.mp4"})
    _check_segment_files(s, segments, warnings)
    achieved = n_frames / (recorded_ns / 1e9) if recorded_ns else 0.0
    drop_pct = 100 * dropped / max(1, n_frames + dropped)
    if drop_pct > 1:
        warnings.append(f"front camera dropped {dropped} frames ({drop_pct:.1f}%)")

    # coverage of the steps that should have been recorded
    steps = s.step_windows()
    wanted = steps if cfg.get("steps", ["feed"]) == "all" else steps[steps["step_id"].isin(cfg.get("steps", ["feed"]))]
    coverage = {}
    t_all = cf["t_ns"].to_numpy(np.int64)
    for _, w in wanted.iterrows():
        n = int(((t_all >= w["start_ns"]) & (t_all < w["end_ns"])).sum())
        expected = (w["end_ns"] - w["start_ns"]) / interval
        coverage[w["step_id"]] = round(min(1.0, n / expected), 3) if expected > 0 else None
        if coverage[w["step_id"]] is not None and coverage[w["step_id"]] < 0.95:
            warnings.append(f"front camera covered only {100 * coverage[w['step_id']]:.0f}% of step {w['step_id']!r}")

    out.update({
        "segments": segments,
        "frames": n_frames,
        "dropped_frames": dropped,
        "recorded_s": round(recorded_ns / 1e9, 3),
        "fps_requested": fps,
        "fps_achieved": round(achieved, 2),
        "step_coverage": coverage,
        "warnings": warnings,
    })
    return out


def _check_segment_files(s: Session, segments: list[dict], warnings: list[str]) -> None:
    """Each segment's video must exist and hold as many frames as camera_frames.csv lists."""
    try:
        import cv2
    except ImportError:  # frame counts can't be checked without OpenCV
        cv2 = None
    for seg in segments:
        path = s.path / seg["file"]
        if not path.is_file():
            warnings.append(f"front camera segment {seg['file']} is missing")
            seg["video_frames"] = None
            continue
        if cv2 is None:
            continue
        cap = cv2.VideoCapture(str(path))
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) if cap.isOpened() else 0
        cap.release()
        seg["video_frames"] = n
        if n == 0:
            warnings.append(f"front camera segment {seg['file']} cannot be read (recording interrupted?)")
        elif n != seg["frames"]:
            warnings.append(f"{seg['file']} has {n} video frames but camera_frames.csv lists {seg['frames']}")
