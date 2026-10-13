"""AprilTag detection (tag36h11; tag25h9 and tag16h5 for tag_bars) for small on-screen tags in the Neon scene video.

Uses pupil-apriltags: OpenCV's aruco detector missed most tags of ~25 px (CAM-210). A second
pass on a gamma-darkened copy recovers tags washed out by the screen's glare.
"""
from __future__ import annotations

import cv2
import numpy as np

_GAMMA = (np.linspace(0, 1, 256) ** 3 * 255).astype(np.uint8)


class TagDetector:
    def __init__(self, threads: int = 4, family: str = "tag36h11"):
        try:
            from pupil_apriltags import Detector
        except ImportError as e:  # pragma: no cover - depends on the environment
            raise RuntimeError("pupil-apriltags is needed for gaze mapping: pip install pupil-apriltags") from e
        self._det = Detector(families=family, quad_decimate=1.0, decode_sharpening=0.25, nthreads=threads)
        # tag16h5 can be confused with random patches: only error-free reads count
        self._max_hamming = 0 if family == "tag16h5" else 2

    def detect(self, gray: np.ndarray, want: int | None = None) -> dict[int, np.ndarray]:
        """Corners of each tag found, in pupil_apriltags' order (TR, TL, BL, BR for an upright tag),
        in the frame's own (distorted) pixels. The darkened pass runs when fewer than `want` tags
        were found."""
        return {i: c for i, (c, _) in self.detect_margins(gray, want).items()}

    def detect_margins(self, gray: np.ndarray, want: int | None = None, second_pass: bool = True) -> dict[int, tuple]:
        """As detect, with each tag's decision margin (how clearly its bits read; higher is safer).
        second_pass=False skips the darkened pass, to judge the picture as recorded."""
        best = {d.tag_id: d for d in self._det.detect(gray) if d.hamming <= self._max_hamming}
        if second_pass and (want is None or len(best) < want):
            for d in self._det.detect(cv2.LUT(gray, _GAMMA)):
                if d.hamming > self._max_hamming:
                    continue
                if d.tag_id not in best or d.decision_margin > best[d.tag_id].decision_margin:
                    best[d.tag_id] = d
        return {int(i): (np.asarray(d.corners, np.float64), float(d.decision_margin)) for i, d in best.items()}


def tag_corners(rect, quiet_cells: float = 2, cells: float = 8) -> np.ndarray:
    """Screen-pixel corners of a tag's black square, from the rectangle of its whole image
    (tag plus a white margin of `quiet_cells` on each side), in the detector's order:
    TR, TL, BL, BR (y down)."""
    x0, y0, x1, y1 = rect
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    half = (x1 - x0) * cells / (cells + 2 * quiet_cells) / 2
    return np.array([[cx + half, cy - half], [cx - half, cy - half], [cx - half, cy + half], [cx + half, cy + half]])
