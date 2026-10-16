"""Where the phone screen is in each Neon scene frame.

The phone's 3-D pose is solved from the visible tags' corners (PnP: Neon's scene camera
intrinsics plus the tags' real positions in mm), which needs only one tag and is steadier than
a free homography. Frames without usable tags are bridged by optical flow of the area around
the tags (which doesn't scroll), for at most `max_bridge_ms` after the last tag frame.
Offline test on CAM-210 recordings (scripts/tracking_pnp_test.py, results on CAM-165): PnP
halved the gaze error when tags were hard to read; flow stays under ~0.5 mm for 0.25 s even in
poor conditions.

Every frame's mapping is a homography from undistorted scene pixels to screen pixels.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import cv2
import numpy as np
import pandas as pd

from ..session.io import Session, load_session
from .neon import NeonRecording, SceneVideo, read_recording, undistort
from ..markers import FAMILY_CELLS
from .tags import TagDetector, tag_corners

MAX_RMS_PX = 2.0          # corner reprojection RMS (scene px) above which a pose is rejected
MAX_BRIDGE_MS = 300.0     # longest stretch bridged by flow after the last frame with tags
FLOW_REGION_SCALE = 2.0   # flow tracks features within this many tag-widths around each tag
PREDICT_MS = 1000.0       # smart detection searches where the tags were up to this long ago
MAX_FRAME_GAP_MS = 100.0  # no flow across a longer gap between frames (e.g. skipped frames)

TRACKING_COLUMNS = ["frame", "unix_ns", "t_ns", "step_id", "source", "n_tags", "tag_ids", "reproj_px",
                    "distance_mm", "since_tags_ms"] + [f"h{i}{j}" for i in range(3) for j in range(3)]


class Screen:
    """Screen pixels <-> mm on the screen plane (z = 0), from the device's real dpi."""

    def __init__(self, width_px: int, height_px: int, xdpi: float, ydpi: float):
        self.w, self.h = width_px, height_px
        self.mm_per_px = np.array([25.4 / xdpi, 25.4 / ydpi])
        self.S = np.diag([*self.mm_per_px, 1.0])

    @classmethod
    def of(cls, device: dict) -> "Screen":
        return cls(device["screen_width_px"], device["screen_height_px"], device["xdpi"], device["ydpi"])

    def mm(self, px: np.ndarray) -> np.ndarray:
        return np.asarray(px) * self.mm_per_px


@dataclass
class Pose:
    H: np.ndarray        # undistorted scene px -> screen px
    R: np.ndarray        # rotation, phone -> camera
    t: np.ndarray        # translation (mm), phone origin (screen top-left) in camera coordinates
    rms: float           # corner reprojection RMS, scene px
    tag_ids: tuple


def apply_h(H: np.ndarray, pts) -> np.ndarray:
    return cv2.perspectiveTransform(np.asarray(pts, np.float64).reshape(-1, 1, 2), H).reshape(-1, 2)


def _pnp(ids, dets, tags, K, screen: Screen, prev_R) -> Optional[Pose]:
    img = np.vstack([dets[i] for i in ids])
    obj = np.hstack([screen.mm(np.vstack([tags[i] for i in ids])), np.zeros((4 * len(ids), 1))])
    n, rvecs, tvecs, _ = cv2.solvePnPGeneric(obj, img, K, None, flags=cv2.SOLVEPNP_IPPE)
    cands = []
    for rv, tv in zip(rvecs[:n], tvecs[:n]):
        if tv[2, 0] <= 0:
            continue
        rv, tv = cv2.solvePnPRefineLM(obj, img, K, None, rv.copy(), tv.copy())
        proj = cv2.projectPoints(obj, rv, tv, K, None)[0].reshape(-1, 2)
        rms = float(np.sqrt(np.mean(np.sum((proj - img) ** 2, axis=1))))
        cands.append((cv2.Rodrigues(rv)[0], tv.ravel(), rms))
    if not cands:
        return None
    if prev_R is not None and len(ids) == 1:
        # one tag: IPPE's two mirror-image poses fit about equally well; keep the one nearest the last pose
        R, t, rms = min(cands, key=lambda c: np.linalg.norm(cv2.Rodrigues(c[0] @ prev_R.T)[0]))
    else:
        R, t, rms = min(cands, key=lambda c: c[2])
    H = np.linalg.inv(K @ np.column_stack([R[:, 0], R[:, 1], t]) @ screen.S)
    return Pose(H / H[2, 2], R, t, rms, tuple(ids))


def solve_pose(dets: dict, tags: dict, K: np.ndarray, screen: Screen, prev_R: Optional[np.ndarray] = None,
               max_rms: float = MAX_RMS_PX) -> Optional[Pose]:
    """Phone pose from the tags found (undistorted scene px) and where those tags are on screen
    (screen px corners, same order). If the fit is poor with several tags (e.g. a thumb half over
    one), each tag is left out in turn and the best fit that passes is kept."""
    ids = sorted(i for i in dets if i in tags)
    if not ids:
        return None
    pose = _pnp(ids, dets, tags, K, screen, prev_R)
    if pose is not None and pose.rms <= max_rms:
        return pose
    if len(ids) < 2:
        return None
    alts = [p for drop in ids if (p := _pnp([i for i in ids if i != drop], dets, tags, K, screen, prev_R)) is not None]
    alts = [p for p in alts if p.rms <= max_rms]
    return min(alts, key=lambda p: p.rms) if alts else None


@dataclass
class FrameResult:
    source: str                  # "tags", "flow" or "" (no mapping)
    H: Optional[np.ndarray]
    tag_ids: tuple = ()
    reproj_px: float = float("nan")
    distance_mm: float = float("nan")
    since_tags_ms: float = float("nan")
    detected: tuple = ()         # every tag read in the frame (the pose may leave one out)


class PhoneTracker:
    """Feed it scene frames in order; it returns each frame's scene->screen mapping."""

    def __init__(self, K: np.ndarray, dist: np.ndarray, screen: Screen, max_bridge_ms: float = MAX_BRIDGE_MS,
                 max_rms: float = MAX_RMS_PX):
        self.K, self.dist, self.screen = K, dist, screen
        self.max_bridge_ns = max_bridge_ms * 1e6
        self.max_rms = max_rms
        self.reset()

    def reset(self) -> None:
        self._prev_gray = None
        self._t_prev = None     # time of the previous frame
        self._H = None          # mapping of the previous frame (tags or flow)
        self._R = None          # last pose's rotation (resolves single-tag ambiguity)
        self._t_tags = None     # time of the last frame with a tag pose
        self._H_known, self._t_known = None, None   # the latest mapping of any kind, for predictions

    def predict(self, t_ns: int, tags: dict) -> tuple[Optional[dict], float]:
        """Where each tag should be in this frame (distorted frame px, detector's corner order), from
        the latest mapping if it is at most PREDICT_MS old, and how much to widen the search for
        its age (1 = the previous frame)."""
        if self._H_known is None or t_ns - self._t_known > PREDICT_MS * 1e6:
            return None, 1.0
        Hinv = np.linalg.inv(self._H_known)
        pred = {i: _distort(apply_h(Hinv, c), self.K, self.dist) for i, c in tags.items()}
        age_ms = (t_ns - self._t_known) / 1e6
        return pred, min(1.0 + max(age_ms - 40, 0) / 150, 3.0)

    def track(self, t_ns: int, gray: np.ndarray, tags: dict, detector: TagDetector, smart: bool = True) -> FrameResult:
        """Detect the tags in this frame (smart: also closely where they're predicted to be) and update."""
        pred, slack = self.predict(t_ns, tags) if smart else (None, 1.0)
        return self.update(t_ns, gray, detector.detect_expected(gray, pred, tags.keys(), slack), tags)

    def update(self, t_ns: int, gray: np.ndarray, raw_dets: dict, tags: dict) -> FrameResult:
        """raw_dets: tag corners as detected (distorted px); tags: where each tag is on screen."""
        dets = {i: undistort(c, self.K, self.dist) for i, c in raw_dets.items() if i in tags}
        pose = solve_pose(dets, tags, self.K, self.screen, self._R, self.max_rms)
        res = FrameResult("", None, detected=tuple(sorted(dets)))
        recent = self._t_prev is not None and t_ns - self._t_prev <= MAX_FRAME_GAP_MS * 1e6
        if pose is not None:
            self._R, self._t_tags = pose.R, t_ns
            res = FrameResult("tags", pose.H, pose.tag_ids, pose.rms, float(np.linalg.norm(pose.t)), 0.0, res.detected)
        elif (self._H is not None and self._prev_gray is not None and recent
              and t_ns - self._t_tags <= self.max_bridge_ns):
            G = self._flow(self._prev_gray, gray, self._H, tags)
            if G is not None:
                res = FrameResult("flow", self._H @ np.linalg.inv(G), since_tags_ms=(t_ns - self._t_tags) / 1e6,
                                  detected=res.detected)
        self._H = res.H
        if res.H is not None:
            self._H_known, self._t_known = res.H, t_ns
        self._prev_gray, self._t_prev = gray, t_ns
        return res

    def _flow(self, prev: np.ndarray, cur: np.ndarray, H_prev: np.ndarray, tags: dict) -> Optional[np.ndarray]:
        """Homography taking undistorted scene points in the previous frame to this one, from
        features around the tags (they stay put on screen while the content scrolls)."""
        mask = np.zeros_like(prev)
        Hinv = np.linalg.inv(H_prev)
        for c in tags.values():
            centre = c.mean(axis=0)
            region = centre + (c - centre) * FLOW_REGION_SCALE
            poly = _distort(apply_h(Hinv, region), self.K, self.dist)
            if not np.all(np.isfinite(poly)):
                continue
            cv2.fillConvexPoly(mask, np.round(poly).astype(np.int32), 255)
        p0 = cv2.goodFeaturesToTrack(prev, 200, 0.01, 5, mask=mask)
        if p0 is None or len(p0) < 8:
            return None
        p1, st, _ = cv2.calcOpticalFlowPyrLK(prev, cur, p0, None, winSize=(21, 21), maxLevel=3)
        good = st.ravel() == 1
        if good.sum() < 8:
            return None
        a = undistort(p0[good].reshape(-1, 2), self.K, self.dist)
        b = undistort(p1[good].reshape(-1, 2), self.K, self.dist)
        G, inl = cv2.findHomography(a, b, cv2.RANSAC, 1.5)
        return G if G is not None and inl.sum() >= 8 else None


def _distort(pts: np.ndarray, K: np.ndarray, dist: np.ndarray) -> np.ndarray:
    xn = np.hstack([pts, np.ones((len(pts), 1))]) @ np.linalg.inv(K).T
    return cv2.projectPoints(xn, np.zeros(3), np.zeros(3), K, dist)[0].reshape(-1, 2)


# ---------------------------------------------------------------- a whole recording

def clock_offset_ns(session: Session) -> int:
    """Unix ns minus the session's elapsed-realtime ns. Companion and the app run on the same
    phone, so the session's clock anchor ties the two together (agreed to 0.7 ms in CAM-210)."""
    c = session.meta["clock"]
    return int(c["wall_ms"]) * 1_000_000 - int(c["elapsed_ns"])


def tag_windows(session: Session) -> list[tuple[str, int, int, dict, str]]:
    """(step_id, start_ns, end_ns, {tag id: screen corners}, tag family) for each step with
    on-screen tags, in the session's clock."""
    layouts = session.events_of("marker_layout")
    if "on_screen" not in layouts:
        return []
    steps = session.step_windows().set_index("step_id")
    out = []
    for _, e in layouts[layouts["on_screen"] == True].iterrows():  # noqa: E712 (NaN for other layouts)
        if e["step_id"] not in steps.index:
            continue
        s = steps.loc[e["step_id"]]
        family = e.get("family") if isinstance(e.get("family"), str) else "tag36h11"  # NaN before bars
        tags = {int(k): tag_corners(v, cells=FAMILY_CELLS[family]) for k, v in e["tags"].items()}
        out.append((e["step_id"], int(s["start_ns"]), int(s["end_ns"]), tags, family))
    return out


def track_recording(rec: NeonRecording | str | Path, session: Session | str | Path,
                    max_bridge_ms: float = MAX_BRIDGE_MS,
                    progress: Optional[Callable[[str, int, int], None]] = None, smart: bool = True) -> pd.DataFrame:
    """One row per scene frame during steps with on-screen tags (TRACKING_COLUMNS).
    smart=False turns off the close search where tags are predicted to be (TagDetector.detect_expected).
    t_ns is in the session's clock (as in events.jsonl and viewport.csv); unix_ns in Neon's."""
    rec = rec if isinstance(rec, NeonRecording) else read_recording(rec)
    session = session if isinstance(session, Session) else load_session(session)
    off = clock_offset_ns(session)
    screen = Screen.of(session.device)
    windows = tag_windows(session)
    if not windows:
        raise ValueError("this session has no steps with on-screen tags (markers.on_screen), so the phone can't be tracked")
    detectors: dict[str, TagDetector] = {}
    tracker = PhoneTracker(rec.K, rec.dist, screen, max_bridge_ms)
    rows = []
    with SceneVideo(rec.scene_video) as video:
        for step_id, start, end, tags, family in windows:
            detector = detectors.setdefault(family, TagDetector(family=family))
            idx = np.where((rec.scene_t >= start + off) & (rec.scene_t <= end + off))[0]
            if not len(idx):
                continue
            tracker.reset()
            for n, (i, gray) in enumerate(video.gray(idx)):
                r = tracker.track(int(rec.scene_t[i]), gray, tags, detector, smart)
                H = r.H if r.H is not None else np.full((3, 3), np.nan)
                rows.append([int(i), int(rec.scene_t[i]), int(rec.scene_t[i]) - off, step_id, r.source, len(r.tag_ids),
                             " ".join(map(str, r.tag_ids)), r.reproj_px, r.distance_mm, r.since_tags_ms, *H.ravel()])
                if progress and n % 100 == 0:
                    progress(step_id, n, len(idx))
    return pd.DataFrame(rows, columns=TRACKING_COLUMNS)


def homographies(tracking: pd.DataFrame) -> np.ndarray:
    """(frames, 3, 3) scene->screen homographies from a tracking table (NaN where none)."""
    return tracking[[f"h{i}{j}" for i in range(3) for j in range(3)]].to_numpy(float).reshape(-1, 3, 3)
