"""Shared by the CAM-165 offline tracking tests (content matching, motion sensors): a recording
with a tag pose for every scene frame, the best of them kept as the reference.

Works on CAM-210 runs (tags above and below the feed) and on tag_ladder sessions (16 tags on a
white screen, rearranged every few seconds). Tag detections are cached in out_dir/scan.json;
for CAM-210 runs the scan.json written by tracking_pnp_test.py is used as is.

A reference frame has a pose from at least two tags whose centres are at least half the screen
height apart (CAM-210: a top and a bottom tag, 0.45 mm from the 4-tag pose in that test), with
a corner reprojection RMS under 2 px.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).parents[1] / "python" / "src"))
from socialeyes.gaze.neon import NeonRecording, read_recording, undistort  # noqa: E402
from socialeyes.gaze.tags import TagDetector, tag_corners  # noqa: E402
from socialeyes.gaze.tracking import (PhoneTracker, Pose, Screen, apply_h, clock_offset_ns,  # noqa: E402
                                      solve_pose)
from socialeyes.session.io import Session, load_session  # noqa: E402


@dataclass
class Frame:
    i: int                       # scene video frame index
    t: int                       # Unix ns (Neon clock)
    step: str
    segment: str                 # the step, or "<step> hold <n>" on the tag ladder
    tags: dict                   # tag id -> screen corners of the layout on screen
    dets: dict                   # tag id -> undistorted corners
    G: Optional[np.ndarray]      # flow around the tags, previous frame -> this one (undistorted px)
    pose: Optional[Pose]         # from all tags found
    ref: bool                    # pose from tags spanning the screen


@dataclass
class Run:
    name: str
    rec: NeonRecording
    session: Session
    screen: Screen
    offset_ns: int               # Unix ns - session ns
    frames: list[Frame]
    grid: np.ndarray             # screen px where gaze could land (5 x 9)

    def transfer_err_mm(self, H_ref: np.ndarray, H_est: np.ndarray, pts: Optional[np.ndarray] = None) -> np.ndarray:
        """Where screen points sit in the scene under the reference, mapped back with the estimate:
        how far from where they should be (mm on the screen)."""
        pts = self.grid if pts is None else pts
        scene = apply_h(np.linalg.inv(H_ref), pts)
        return np.linalg.norm(self.screen.mm(apply_h(H_est, scene) - pts), axis=1)


def layouts(session: Session) -> list[tuple[str, int, int, dict, str]]:
    """(step_id, start_ns, end_ns, {tag id: screen corners}, segment) for every tag layout shown
    on the phone screen (on-screen tags and tag ladder arrangements), in the session's clock."""
    ev = session.events_of("marker_layout")
    steps = session.step_windows().set_index("step_id")
    rows = []
    for _, e in ev.iterrows():
        ladder = e.get("ladder") if isinstance(e.get("ladder"), dict) else None
        if (e.get("on_screen") == True or ladder) and e["step_id"] in steps.index:  # noqa: E712
            segment = f"{e['step_id']} hold {ladder['hold']}" if ladder else e["step_id"]
            rows.append((e["step_id"], int(e["t_ns"]), {int(k): tag_corners(v) for k, v in e["tags"].items()}, segment))
    out = []
    for k, (step, t0, tags, segment) in enumerate(rows):
        end = int(steps.loc[step, "end_ns"])
        if k + 1 < len(rows) and rows[k + 1][0] == step:
            end = rows[k + 1][1]
        out.append((step, max(t0, int(steps.loc[step, "start_ns"])), end, tags, segment))
    return out


def _scan(rec: NeonRecording, session: Session, screen: Screen, off: int, cache: Path) -> list[dict]:
    detector, tracker = TagDetector(), PhoneTracker(rec.K, rec.dist, screen)
    cap = cv2.VideoCapture(str(rec.scene_video))
    frames = []
    try:
        for n, (step, start, end, tags, _) in enumerate(layouts(session)):
            idx = np.where((rec.scene_t >= start + off) & (rec.scene_t < end + off))[0]
            if not len(idx):
                continue
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(idx[0]))
            prev, H_prev = None, None
            for i in idx:
                ok, frame = cap.read()
                if not ok:
                    break
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                dets = {k: undistort(c, rec.K, rec.dist) for k, c in detector.detect(gray, len(tags)).items() if k in tags}
                G = tracker._flow(prev, gray, H_prev, tags) if prev is not None and H_prev is not None else None
                pose = solve_pose(dets, tags, rec.K, screen)
                H_prev = pose.H if pose else (H_prev @ np.linalg.inv(G) if G is not None and H_prev is not None else None)
                frames.append({"i": int(i), "t": int(rec.scene_t[i]), "step": step, "layout": n,
                               "dets": {k: v.tolist() for k, v in dets.items()}, "G": None if G is None else G.tolist()})
                prev = gray
            print(f"  scanned layout {n} ({step}): {len(idx)} frames", flush=True)
    finally:
        cap.release()
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(frames), encoding="utf-8")
    return frames


def load_run(rec_dir: Path, session_dir: Path, out_dir: Path) -> Run:
    rec, session = read_recording(rec_dir), load_session(session_dir)
    screen, off = Screen.of(session.device), clock_offset_ns(session)
    lays = layouts(session)
    cache = out_dir / "scan.json"
    scan = json.loads(cache.read_text(encoding="utf-8")) if cache.exists() else _scan(rec, session, screen, off, cache)
    frames, prev_R = [], None
    for f in scan:
        if "layout" in f:
            _, _, _, tags, segment = lays[f["layout"]]
        else:  # tracking_pnp_test.py's scan: one layout per step
            _, _, _, tags, segment = next(lay for lay in lays if lay[0] == f["step"])
        dets = {int(k): np.array(v) for k, v in f["dets"].items() if int(k) in tags}
        pose = solve_pose(dets, tags, rec.K, screen, prev_R)
        if pose is not None:
            prev_R = pose.R
        ref = False
        if pose is not None and len(pose.tag_ids) >= 2:
            ys = [tags[k][:, 1].mean() for k in pose.tag_ids]
            ref = max(ys) - min(ys) >= screen.h / 2
        frames.append(Frame(f["i"], f["t"], f["step"], segment, tags, dets, None if f["G"] is None else np.array(f["G"]),
                            pose, ref))
    xs, ys = np.linspace(54, screen.w - 54, 5), np.linspace(120, screen.h - 120, 9)
    grid = np.array([[x, y] for y in ys for x in xs])
    return Run(out_dir.name, rec, session, screen, off, frames, grid)


def stats(errs) -> dict:
    """Median, p90 and count of per-case errors."""
    e = np.asarray(errs, float)
    e = e[np.isfinite(e)]
    if not len(e):
        return {"n": 0, "median": None, "p90": None}
    return {"n": int(len(e)), "median": round(float(np.median(e)), 2), "p90": round(float(np.percentile(e, 90)), 2)}


def table(title: str, rows: list[list], cols: list[str]) -> str:
    cells = [[f"{v:.2f}" if isinstance(v, float) else str(v) for v in r] for r in rows]
    widths = [max([len(c)] + [len(r[k]) for r in cells]) + 2 for k, c in enumerate(cols)]
    out = [title, "  " + "".join(f"{c:>{w}}" for c, w in zip(cols, widths))]
    for r in cells:
        out.append("  " + "".join(f"{v:>{w}}" for v, w in zip(r, widths)))
    return "\n".join(out)
