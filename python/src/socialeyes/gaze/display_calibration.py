"""Display calibration: the screen brightness and Neon scene camera exposure at which the scene
camera reads the on-screen tags best without blowing out the screen (CAM-165).

Runs on a laptop during a session's `display_calibration` step:

    socialeyes calibrate-display <phone ip>

The phone shows the session's on-screen tags around a post image and runs a small server for the
step (port 8091). This module:
  1. asks the app for the layout (tags, the image, the screen) and the scene camera's settings;
  2. for each screen brightness x scene camera exposure, has the app apply it, waits for the
     scene video to show it, and scores a few frames of Companion's scene video stream:
       - tags read: share of the on-screen tags detected (as the analysis pipeline detects them)
       - margin: how clearly their bits read (pupil-apriltags' decision margin)
       - blown out: share of the post image at full white in the video (lost content)
  3. measures the best few again (the participant may have moved), picks one and sends it back;
     the app keeps it for the rest of the session and puts the scene camera back at the end.

Choice (see rank): the most tags read; then the least blown out; then the post image at a usable
grey level in the video; then the screen brightness closest to the phone's own setting (what the
participant is used to); then the clearest tag margin. An over-bright screen still reads its tags
(white saturates, black stays black) but loses the content, hence the blown-out criterion.
"""
from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import asdict, dataclass, field
from typing import Callable, Optional, Protocol

import cv2
import numpy as np

from .neon import undistort
from .tags import TagDetector, tag_corners
from .tracking import Screen, apply_h, solve_pose

BRIGHTNESS_LEVELS = (1.0, 0.75, 0.55, 0.4, 0.3)
EXPOSURES_US = ("auto", 1000, 2000, 4000, 8000, 16000)
FRAMES_PER_SETTING = 8
SETTLE_S = 0.3            # after a manual exposure or brightness change
SETTLE_AUTO_S = 1.2       # auto exposure needs time to converge
SATURATED = 250
DET_TOLERANCE = 0.1
SAT_TOLERANCE = 0.05
IMAGE_LEVEL = (80, 235)   # grey level of the post image in the video where its detail survives
CONFIRM_TOP = 3


# ---------------------------------------------------------------- the phone and the scene camera

class App(Protocol):
    def state(self) -> dict: ...
    def apply(self, brightness: float, camera: dict) -> int: ...
    def done(self, brightness: float, camera: dict, summary: dict) -> None: ...


class Scene(Protocol):
    def frames_after(self, t_unix_ns: int, n: int, timeout_s: float) -> list[np.ndarray]: ...


class AppLink:
    """The app's calibration server (only up during a display_calibration step)."""

    def __init__(self, host: str, port: int = 8091, timeout_s: float = 10.0):
        self.base, self.timeout = f"http://{host}:{port}", timeout_s

    def _call(self, path: str, body: Optional[dict] = None) -> dict:
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.base + path, data=data, method="GET" if body is None else "POST",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.loads(r.read().decode() or "{}")

    def state(self) -> dict:
        return self._call("/state")

    def apply(self, brightness: Optional[float], camera: dict) -> int:
        """Sets both (None / {}: leave as is); returns when the app applied them (Unix ns, the
        phone's clock = Companion's)."""
        return int(self._call("/apply", {"brightness": brightness, "camera": camera})["applied_unix_ns"])

    def done(self, brightness: Optional[float], camera: Optional[dict], summary: dict) -> None:
        """The chosen setting (None: keep what the session had before the calibration)."""
        self._call("/done", {"brightness": brightness, "camera": camera, "summary": summary})


class NeonScene:
    """Companion's scene video stream (Pupil Labs' real-time API)."""

    def __init__(self, host: str, port: int = 8080):
        try:
            from pupil_labs.realtime_api.simple import Device
        except ImportError as e:  # pragma: no cover - depends on the environment
            raise RuntimeError("needs Pupil Labs' real-time API: pip install pupil-labs-realtime-api") from e
        self.device = Device(host, port)

    def calibration(self):
        c = self.device.get_calibration()  # pupil_labs.neon_recording Calibration (fields as attributes)
        return (np.asarray(c.scene_camera_matrix, float).reshape(3, 3),
                np.asarray(c.scene_distortion_coefficients, float).ravel())

    def frames_after(self, t_unix_ns: int, n: int, timeout_s: float = 5.0) -> list[np.ndarray]:
        out, deadline = [], time.monotonic() + timeout_s
        while len(out) < n and time.monotonic() < deadline:
            f = self.device.receive_scene_video_frame(timeout_seconds=1.0)
            if f is not None and f.timestamp_unix_seconds * 1e9 >= t_unix_ns:
                out.append(cv2.cvtColor(f.bgr_pixels, cv2.COLOR_BGR2GRAY))
        return out

    def close(self):
        self.device.close()


# ---------------------------------------------------------------- scoring

@dataclass
class Measure:
    brightness: float
    camera: dict
    frames: int = 0
    tags_read: float = 0.0          # share of on-screen tags detected, over frames
    margin: float = 0.0             # median decision margin of the tags read
    blown_out: Optional[float] = None   # share of the post image at full white (frames with a pose)
    image_level: Optional[float] = None  # median grey level of the post image in the video
    pose_frames: int = 0

    @property
    def label(self) -> str:
        cam = "auto" if self.camera.get("ae_mode") == "auto" else f"{self.camera.get('man_exp')} us"
        return f"brightness {self.brightness:.2f}, exposure {cam}"


@dataclass
class Layout:
    tags: dict                      # tag id -> screen corners (black square)
    image: Optional[tuple]          # post image rectangle (screen px), or None
    screen: Screen
    K: np.ndarray
    dist: np.ndarray
    samples: np.ndarray = field(default=None)  # screen px sampled inside the image

    def __post_init__(self):
        if self.image is not None and self.samples is None:
            l, t, r, b = self.image
            xs, ys = np.linspace(l + 0.05 * (r - l), r - 0.05 * (r - l), 24), np.linspace(t + 0.05 * (b - t), b - 0.05 * (b - t), 30)
            self.samples = np.array([[x, y] for y in ys for x in xs])

    @classmethod
    def from_state(cls, state: dict, K=None, dist=None) -> "Layout":
        cal = state.get("calibration") or {}
        K = np.asarray(cal["K"], float).reshape(3, 3) if K is None and cal.get("K") else K
        dist = np.asarray(cal.get("dist", [0] * 8), float) if dist is None else dist
        if K is None:
            raise ValueError("no scene camera calibration from the app or Companion")
        s = state["screen"]
        return cls({int(k): tag_corners(v) for k, v in state["tags"].items()},
                   tuple(state["image"]) if state.get("image") else None,
                   Screen(s["width_px"], s["height_px"], s["xdpi"], s["ydpi"]), K, dist)


def measure(frames: list[np.ndarray], layout: Layout, detector: TagDetector, brightness: float, camera: dict,
            prior_H: Optional[np.ndarray] = None) -> tuple[Measure, Optional[np.ndarray]]:
    """Scores frames taken at one setting. Where no tag is read (e.g. the screen is so blown out
    that the tags are lost), the blown-out share is measured where the phone last was (`prior_H`,
    a scene->screen mapping from a previous setting a second or so earlier). Returns the measure
    and the last mapping seen."""
    m = Measure(brightness, dict(camera), frames=len(frames))
    if not frames:
        return m, prior_H
    read, margins, blown, levels = [], [], [], []
    H = prior_H
    for gray in frames:
        found = {i: v for i, v in detector.detect_margins(gray, len(layout.tags)).items() if i in layout.tags}
        read.append(len(found) / len(layout.tags))
        margins += [mg for _, mg in found.values()]
        dets = {i: undistort(c, layout.K, layout.dist) for i, (c, _) in found.items()}
        pose = solve_pose(dets, layout.tags, layout.K, layout.screen) if dets else None
        if pose is not None:
            H = pose.H
            m.pose_frames += 1
        if H is None or layout.samples is None:
            continue
        scene = apply_h(np.linalg.inv(H), layout.samples)
        raw = _distort(scene, layout.K, layout.dist)
        ok = (raw[:, 0] >= 0) & (raw[:, 1] >= 0) & (raw[:, 0] < gray.shape[1] - 1) & (raw[:, 1] < gray.shape[0] - 1)
        if ok.mean() < 0.5:
            continue
        vals = gray[raw[ok, 1].round().astype(int), raw[ok, 0].round().astype(int)]
        blown.append(float((vals >= SATURATED).mean()))
        levels.append(float(np.median(vals)))
    m.tags_read = float(np.mean(read))
    m.margin = float(np.median(margins)) if margins else 0.0
    if blown:
        m.blown_out, m.image_level = float(np.mean(blown)), float(np.median(levels))
    return m, H


def _distort(pts: np.ndarray, K: np.ndarray, dist: np.ndarray) -> np.ndarray:
    xn = np.hstack([pts, np.ones((len(pts), 1))]) @ np.linalg.inv(K).T
    return cv2.projectPoints(xn, np.zeros(3), np.zeros(3), K, dist)[0].reshape(-1, 2)


def rank(measures: list[Measure], target_brightness: Optional[float] = None) -> list[Measure]:
    """Best first: most tags read (within DET_TOLERANCE of the best), then least blown out (within
    SAT_TOLERANCE of the least), then the post image at a usable level in the video (not so dark
    that it loses detail), then the screen brightness closest to `target_brightness` (the phone's
    own setting, so the participant sees what they're used to; None: the brightest), then the
    clearest tag margin. Settings that read no tags are left out."""
    ms = [m for m in measures if m.frames and m.tags_read > 0]
    if not ms:
        return []
    best_read = max(m.tags_read for m in ms)
    sats = [m.blown_out for m in ms if m.blown_out is not None and m.tags_read >= best_read - DET_TOLERANCE]
    least = min(sats) if sats else None

    def key(m: Measure):
        reads = m.tags_read >= best_read - DET_TOLERANCE
        clear = least is None or (m.blown_out is not None and m.blown_out <= least + SAT_TOLERANCE)
        level_ok = m.image_level is not None and IMAGE_LEVEL[0] <= m.image_level <= IMAGE_LEVEL[1]
        near = -abs(m.brightness - target_brightness) if target_brightness is not None else m.brightness
        return (reads, clear, level_ok, round(near, 3), m.margin)

    return sorted(ms, key=key, reverse=True)


def choose(measures: list[Measure], target_brightness: Optional[float] = None) -> Optional[Measure]:
    ranked = rank(measures, target_brightness)
    return ranked[0] if ranked else None


def settings(state: dict, levels=BRIGHTNESS_LEVELS, exposures=EXPOSURES_US, min_brightness: float = 0.25) -> list[tuple[float, dict]]:
    """Brightness x exposure to try, exposures clipped to what Companion allows."""
    cam = state.get("camera") or {}
    rng = cam.get("man_exp") or {}
    lo, hi = rng.get("min"), rng.get("max")
    exp = []
    for e in exposures:
        if e == "auto":
            exp.append({"ae_mode": "auto"})
        else:
            v = int(e)
            if (lo is not None and v < lo) or (hi is not None and v > hi):
                continue
            exp.append({"ae_mode": "manual", "man_exp": str(v)})
    return [(b, c) for b in levels if b >= min_brightness for c in exp]


# ---------------------------------------------------------------- the whole run

def calibrate(app: App, scene: Scene, layout: Layout, plan: list[tuple[float, dict]],
              detector: Optional[TagDetector] = None, frames: int = FRAMES_PER_SETTING,
              target_brightness: Optional[float] = None,
              log: Callable[[str], None] = print) -> tuple[Optional[Measure], list[Measure]]:
    detector = detector or TagDetector()
    measures = []
    last_H = [None]

    def run(b, cam, n):
        t = app.apply(b, cam)
        settle = SETTLE_AUTO_S if cam.get("ae_mode") == "auto" else SETTLE_S
        m, last_H[0] = measure(scene.frames_after(t + int(settle * 1e9), n, timeout_s=settle + 5), layout, detector,
                               b, cam, last_H[0])
        log(f"  {m.label:<36} tags read {m.tags_read:4.0%}  margin {m.margin:5.1f}  "
            f"blown out {'-' if m.blown_out is None else f'{m.blown_out:4.0%}'}  "
            f"image level {'-' if m.image_level is None else f'{m.image_level:5.1f}'}")
        return m

    for b, cam in plan:
        measures.append(run(b, cam, frames))
    # the best few again (the participant may have moved), averaged with the first look
    ranked = rank(measures, target_brightness)
    final = []
    if ranked:
        log("measuring the best again:")
    for m in ranked[:CONFIRM_TOP]:
        again = run(m.brightness, m.camera, frames)
        final.append(_combine(m, again))
    best = choose(final, target_brightness) or choose(measures, target_brightness)
    return best, measures + final


def _combine(a: Measure, b: Measure) -> Measure:
    n = a.frames + b.frames
    if not n:
        return a
    w = a.frames / n
    blown = [x for x in (a.blown_out, b.blown_out) if x is not None]
    return Measure(a.brightness, a.camera, n, w * a.tags_read + (1 - w) * b.tags_read, (a.margin + b.margin) / 2,
                   float(np.mean(blown)) if blown else None,
                   a.image_level if b.image_level is None else b.image_level, a.pose_frames + b.pose_frames)


def summary(best: Optional[Measure], measures: list[Measure]) -> dict:
    return {"best": asdict(best) if best else None, "tried": len(measures),
            "measures": [asdict(m) for m in measures]}
