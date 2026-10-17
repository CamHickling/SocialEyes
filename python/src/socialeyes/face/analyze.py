"""Per-frame face measures from a session's front camera video.

MediaPipe's Face Landmarker (478 points with the irises, a head pose matrix and 52 expression
scores; model in models/face_landmarker.task, Apache 2.0) runs on every recorded frame. From it:

- head pose: yaw (turned toward the image's right, i.e. the participant's left, is positive),
  pitch (tilted up is positive) and roll, in degrees
- distance from the phone: the iris is about 11.7 mm across in nearly every adult, so
  distance = focal length in pixels x 11.7 / iris width in pixels (the camera's focal length
  from session.json, else an assumed 75° horizontal field of view, flagged in the summary)
- eye direction: each iris's position between its eye corners and lids, -1 to 1
- looking at the phone or away: most of a feed is spent looking at the screen, so each session
  is its own reference. A frame counts as looking away when the head turns more than
  AWAY_HEAD_DEG or the eyes more than AWAY_EYE from the session's median during the feed, for at
  least MIN_AWAY_S. While the eyes are closed (MediaPipe's blink score above BLINK) the iris
  can't be placed, so eye_x / eye_y are left blank and only the head counts: a blink is not
  looking away.

Checked against a recording of known actions (studies/face_test, 16 Oct 2026): the phone put
down, held close (18 cm) and at arm's length (48 cm), the head turned 55° away, a hand over the
mouth (the face is still found) all came out as expected.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Optional

import numpy as np
import pandas as pd

from ..session.io import Session, load_session

MODEL = Path(__file__).parent / "models" / "face_landmarker.task"
IRIS_MM = 11.7
ASSUMED_HFOV_DEG = 75.0
AWAY_HEAD_DEG = 20.0
AWAY_EYE = 0.45
MIN_AWAY_S = 0.25
BLINK = 0.45

FACE_COLUMNS = ["segment", "frame", "t_ns", "step_id", "faces", "face", "yaw_deg", "pitch_deg", "roll_deg",
                "distance_mm", "eye_x", "eye_y", "blink", "looking", "box_left", "box_top", "box_right", "box_bottom"]

# landmark indices (MediaPipe face mesh with irises)
_R_IRIS, _L_IRIS = (468, 469, 470, 471, 472), (473, 474, 475, 476, 477)
_R_EYE = {"outer": 33, "inner": 133, "top": 159, "bottom": 145}
_L_EYE = {"outer": 263, "inner": 362, "top": 386, "bottom": 374}


@dataclass
class FaceResult:
    frames: pd.DataFrame        # FACE_COLUMNS, one row per video frame
    expressions: pd.DataFrame   # segment, frame, t_ns, then one column per blendshape
    summary: dict


def video_frames(session: Session) -> Iterator[tuple[int, int, int, np.ndarray]]:
    """(segment, frame, t_ns, BGR image upright) for every frame in camera_frames.csv, read in order."""
    import cv2

    cf = session.camera_frames
    if cf is None or not len(cf):
        return
    for seg, g in cf.sort_values(["segment", "frame"]).groupby("segment"):
        path = session.path / "camera" / f"front_{int(seg):03d}.mp4"
        if not path.is_file():
            continue
        cap = cv2.VideoCapture(str(path))
        times = dict(zip(g["frame"].astype(int), g["t_ns"].astype(np.int64)))
        k = 0
        try:
            while True:
                ok, img = cap.read()  # OpenCV applies the file's rotation flag, so frames come upright
                if not ok:
                    break
                if k in times:
                    yield int(seg), k, int(times[k]), img
                k += 1
        finally:
            cap.release()


def _landmarker():
    import os
    import warnings

    os.environ.setdefault("GLOG_minloglevel", "2")       # MediaPipe's own start-up messages
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
    warnings.filterwarnings("ignore", message="SymbolDatabase.GetPrototype")
    import mediapipe as mp
    from mediapipe.tasks.python import BaseOptions, vision

    opts = vision.FaceLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(MODEL)),
        running_mode=vision.RunningMode.VIDEO,
        num_faces=2,  # a second face: someone else watching
        min_face_detection_confidence=0.5,
        min_face_presence_confidence=0.5,
        min_tracking_confidence=0.5,
        output_face_blendshapes=True,
        output_facial_transformation_matrixes=True,
    )
    from .model_files import quiet_native_stderr

    with quiet_native_stderr():
        return mp, vision.FaceLandmarker.create_from_options(opts)


def head_angles(m: np.ndarray) -> tuple[float, float, float]:
    """yaw, pitch, roll in degrees from MediaPipe's facial transformation matrix (camera looks
    down -z, y up)."""
    r = np.asarray(m, float)[:3, :3]
    fwd = r @ np.array([0.0, 0.0, 1.0])     # out of the face, toward the camera when facing it
    right = r @ np.array([1.0, 0.0, 0.0])
    yaw = math.degrees(math.atan2(fwd[0], fwd[2]))
    pitch = math.degrees(math.atan2(fwd[1], math.hypot(fwd[0], fwd[2])))
    roll = math.degrees(math.atan2(right[1], right[0]))
    return yaw, pitch, roll


def _iris_px(pts: np.ndarray, iris: tuple) -> float:
    """Iris width in pixels: the ring's horizontal and vertical diameters, averaged."""
    ring = pts[list(iris[1:])]
    return float((np.linalg.norm(ring[0] - ring[2]) + np.linalg.norm(ring[1] - ring[3])) / 2)


def _eye_offset(pts: np.ndarray, iris: tuple, eye: dict) -> tuple[float, float]:
    """Iris centre between the eye's corners (x) and lids (y), -1 to 1 (toward the image's right / up)."""
    c = pts[iris[0]]
    a, b = pts[eye["outer"]], pts[eye["inner"]]
    left, right = (a, b) if a[0] < b[0] else (b, a)
    half = max(1e-6, (right[0] - left[0]) / 2)
    x = (c[0] - (left[0] + right[0]) / 2) / half
    top, bottom = pts[eye["top"]], pts[eye["bottom"]]
    vhalf = max(1e-6, (bottom[1] - top[1]) / 2)
    y = -(c[1] - (top[1] + bottom[1]) / 2) / vhalf
    return float(np.clip(x, -1, 1)), float(np.clip(y, -1, 1))


def focal_px(session: Session, width: int) -> tuple[float, bool]:
    """(focal length in pixels for frames `width` px wide, whether it is assumed)."""
    cam = session.meta.get("camera") or {}
    f, w = cam.get("focal_px"), cam.get("width")
    if f and w:
        # the recording's own size; frames may come rotated, so scale by the long side
        long_rec = max(int(cam.get("width")), int(cam.get("height", 0)))
        return float(f) * max(width, 1) / long_rec if long_rec else float(f), False
    return width / 2 / math.tan(math.radians(ASSUMED_HFOV_DEG / 2)), True


def analyze_faces(session_dir: Path | str, progress: Callable[[int, int], None] = lambda n, total: None) -> FaceResult:
    s = load_session(session_dir)
    if s.camera_frames is None or not len(s.camera_frames):
        raise ValueError("this session has no front camera video (logging.front_camera)")
    mp, lm = _landmarker()
    steps = s.step_windows()
    starts, ends, ids = (steps[c].to_numpy() for c in ("start_ns", "end_ns", "step_id"))
    total = len(s.camera_frames)
    rows, expr = [], []
    f_px, assumed, last_ms = None, True, -1
    try:
        for n, (seg, k, t, img) in enumerate(video_frames(s)):
            h, w = img.shape[:2]
            if f_px is None:
                f_px, assumed = focal_px(s, max(w, h))
            ms = max(last_ms + 1, t // 1_000_000)  # the landmarker needs increasing timestamps
            last_ms = ms
            rgb = mp.Image(image_format=mp.ImageFormat.SRGB, data=img[:, :, ::-1].copy())
            res = lm.detect_for_video(rgb, int(ms))
            inside = np.flatnonzero((starts <= t) & (t < ends))
            row = {"segment": seg, "frame": k, "t_ns": t, "step_id": ids[inside[-1]] if len(inside) else "",
                   "faces": len(res.face_landmarks), "face": int(bool(res.face_landmarks))}
            if res.face_landmarks:
                # the largest face is the participant's
                sizes = [np.ptp([p.x for p in f]) * np.ptp([p.y for p in f]) for f in res.face_landmarks]
                i = int(np.argmax(sizes))
                pts = np.array([[p.x * w, p.y * h] for p in res.face_landmarks[i]])
                yaw, pitch, roll = head_angles(res.facial_transformation_matrixes[i])
                iris = (_iris_px(pts, _R_IRIS) + _iris_px(pts, _L_IRIS)) / 2
                ex = [_eye_offset(pts, _R_IRIS, _R_EYE), _eye_offset(pts, _L_IRIS, _L_EYE)]
                x0, y0 = pts.min(axis=0)
                x1, y1 = pts.max(axis=0)
                row.update({
                    "yaw_deg": round(yaw, 2), "pitch_deg": round(pitch, 2), "roll_deg": round(roll, 2),
                    "distance_mm": round(f_px * IRIS_MM / iris, 1) if iris > 1 else None,
                    "eye_x": round((ex[0][0] + ex[1][0]) / 2, 3), "eye_y": round((ex[0][1] + ex[1][1]) / 2, 3),
                    "box_left": round(float(x0), 1), "box_top": round(float(y0), 1),
                    "box_right": round(float(x1), 1), "box_bottom": round(float(y1), 1),
                })
                if res.face_blendshapes:
                    scores = {b.category_name: round(b.score, 4) for b in res.face_blendshapes[i]}
                    expr.append({"segment": seg, "frame": k, "t_ns": t, **scores})
                    blink = (scores.get("eyeBlinkLeft", 0) + scores.get("eyeBlinkRight", 0)) / 2
                    row["blink"] = round(blink, 3)
                    if blink > BLINK:  # lids closed: the iris can't be placed between them
                        row["eye_x"] = row["eye_y"] = None
            rows.append(row)
            if n % 100 == 0:
                progress(n, total)
    finally:
        lm.close()
    frames = pd.DataFrame(rows).reindex(columns=FACE_COLUMNS)
    _classify_looking(frames, steps)
    expressions = pd.DataFrame(expr)
    if len(expressions):
        expressions = expressions.drop(columns=["_neutral"], errors="ignore")
    return FaceResult(frames, expressions, summarize(frames, s, assumed))


def _classify_looking(frames: pd.DataFrame, steps: pd.DataFrame) -> None:
    """looking = 1 (at the phone) / 0 (away) for frames with a face, against the session's own
    median head pose and eye position during the feed (all frames if there is no feed)."""
    face = frames["face"] == 1
    feed_ids = set(steps.loc[steps["step_type"] == "feed", "step_id"])
    ref = frames[face & frames["step_id"].isin(feed_ids)]
    if len(ref) < 30:
        ref = frames[face]
    if not len(ref):
        return
    med = ref[["yaw_deg", "pitch_deg", "eye_x", "eye_y"]].median()
    d_head = np.hypot(frames["yaw_deg"] - med["yaw_deg"], frames["pitch_deg"] - med["pitch_deg"])
    d_eye = np.hypot(frames["eye_x"] - med["eye_x"], frames["eye_y"] - med["eye_y"])  # NaN while blinking
    away = ((d_head > AWAY_HEAD_DEG) | (d_eye > AWAY_EYE)).to_numpy()
    away = _drop_short(away & face.to_numpy(), frames["t_ns"].to_numpy(np.int64), MIN_AWAY_S)
    frames["looking"] = np.where(face, (~away).astype(int), np.nan)


def _drop_short(away: np.ndarray, t_ns: np.ndarray, min_s: float) -> np.ndarray:
    """Runs of looking away shorter than ``min_s`` (glances, tracking jitter) count as looking."""
    out = away.copy()
    edges = np.flatnonzero(np.diff(np.concatenate([[0], away.astype(int), [0]])))
    for a, b in zip(edges[::2], edges[1::2]):  # [a, b) is a run of True
        if (t_ns[b - 1] - t_ns[a]) / 1e9 < min_s:
            out[a:b] = False
    return out


def summarize(frames: pd.DataFrame, s: Session, focal_assumed: bool) -> dict:
    """Per recorded step: frames, share with a face, with more than one face, looking at the
    phone (of the frames with a face), distance and head pose; and warnings."""
    out, warnings = {}, []
    for step_id, g in frames.groupby("step_id", sort=False):
        if not step_id:
            continue
        f = g[g["face"] == 1]
        out[step_id] = {
            "frames": int(len(g)),
            "face_share": round(float(g["face"].mean()), 3),
            "multi_face_share": round(float((g["faces"] > 1).mean()), 3),
            "looking_share": round(float(f["looking"].mean()), 3) if len(f) else None,
            "distance_mm_median": _r(f["distance_mm"].median()),
            "distance_mm_p10": _r(f["distance_mm"].quantile(0.1)),
            "distance_mm_p90": _r(f["distance_mm"].quantile(0.9)),
            "yaw_deg_median": _r(f["yaw_deg"].median()),
            "pitch_deg_median": _r(f["pitch_deg"].median()),
        }
        st = out[step_id]
        if st["face_share"] < 0.8:
            warnings.append(f"face visible in only {100 * st['face_share']:.0f}% of step {step_id!r}")
        if st["multi_face_share"] > 0.05:
            warnings.append(f"more than one face in {100 * st['multi_face_share']:.0f}% of step {step_id!r}")
        if st["looking_share"] is not None and st["looking_share"] < 0.8:
            warnings.append(f"looked away from the phone in {100 - 100 * st['looking_share']:.0f}% of step {step_id!r}")
    if focal_assumed:
        warnings.append(f"the camera's focal length wasn't recorded: distances assume a {ASSUMED_HFOV_DEG:.0f}° "
                        "field of view and may be off by 20% or more")
    return {"participant_id": s.participant_id, "session_uid": s.meta.get("session_uid"),
            "steps": out, "focal_assumed": focal_assumed, "warnings": warnings}


def _r(v) -> Optional[float]:
    return None if v is None or v != v else round(float(v), 1)


def write_face(result: FaceResult, out_dir: Path | str) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    result.frames.to_csv(out / "face.csv", index=False)
    result.expressions.to_csv(out / "face_expressions.csv", index=False)
    (out / "face_summary.json").write_text(json.dumps(result.summary, indent=2) + "\n", encoding="utf-8")
    return out


def study_faces(study_dir: Path | str, blur: bool = False,
                progress: Callable[[str], None] = lambda s: None) -> dict:
    """Analyses the face video of every session of a study that has one and hasn't been analysed
    (with ``blur``: also makes the blurred copies still missing). Results go where `socialeyes face`
    puts them: <analysis folder>/<participant>/<session>/. Returns counts and the sessions skipped."""
    from .. import settings
    from ..phone.unload import study_id_of

    sid = study_id_of(study_dir)
    data, root = settings.data_dir(sid), settings.analysis_dir(sid)
    folders = sorted(p.parent for p in data.glob("*/*/camera_frames.csv") if not p.parent.parent.name.startswith("."))
    out = {"videos": len(folders), "analysed": 0, "blurred": 0, "skipped": []}
    for n, folder in enumerate(folders, 1):
        res = root / folder.parent.name / folder.name
        done = (res / "face_summary.json").is_file()
        need_blur = blur and not (res / "camera_blurred").is_dir()
        if done and not need_blur:
            continue
        progress(f"Face video {n} of {len(folders)}: {folder.parent.name}; about as long as the video…")
        try:
            if done:
                frames = pd.read_csv(res / "face.csv")
            else:
                r = analyze_faces(folder)
                write_face(r, res)
                frames = r.frames
                out["analysed"] += 1
            if need_blur:
                from .blur import blur_session

                blur_session(folder, frames, res / "camera_blurred")
                out["blurred"] += 1
        except Exception as e:  # one bad video never stops the others
            out["skipped"].append({"folder": str(folder), "why": str(e)})
    return out
