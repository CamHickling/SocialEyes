"""AprilTag detection (tag36h11; tag25h9 and tag16h5 for tag_bars) for small on-screen tags in the Neon scene video.

Uses pupil-apriltags: OpenCV's aruco detector missed most tags of ~25 px (CAM-210). A second
pass on a gamma-darkened copy recovers tags washed out by the screen's glare. With a tracker's
prediction of where the tags should be, detect_expected also looks closely at each spot where a
tag was missed (CAM-165 smart detection).
"""
from __future__ import annotations

from typing import Iterable

import cv2
import numpy as np

from ..markers import FAMILY_CELLS

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
        self._cells = FAMILY_CELLS[family]

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

    def detect_expected(self, gray: np.ndarray, expected: dict[int, np.ndarray] | None,
                        ids: Iterable[int] | None = None, slack: float = 1.0) -> dict[int, np.ndarray]:
        """Smart detection: as detect, then a closer look where each tag that wasn't found should be.

        ids: the tags on screen (reads of any other id are dropped). expected: tag id -> where the
        tracker predicts its corners (frame px, detector's corner order); slack widens the search
        when the prediction is old. Around each missing tag the frame is cropped, enlarged (so a
        cell is ~8 px), sharpened and searched as is, contrast-stretched and darkened. A read
        there counts if it has the right id and, when it isn't error-free (only allowed there),
        sits where the prediction, corrected by the error-free reads' shift, puts it."""
        keep = set(ids) if ids is not None else set(expected or ())
        found = {i: c for i, c in self.detect(gray, want=len(keep) or None).items() if i in keep}
        if not expected:
            return found
        missing = {i: p for i, p in expected.items() if i in keep and i not in found}
        exact, fuzzy = {}, {}
        for i, pred in missing.items():
            hit = self._search(gray, i, pred, slack)
            if hit is not None:
                (exact if hit[1] <= self._max_hamming else fuzzy)[i] = hit[0]
        found.update(exact)
        if fuzzy:
            shifts = [found[i].mean(0) - expected[i].mean(0) for i in found if i in expected]
            shift = np.median(shifts, axis=0) if shifts else np.zeros(2)
            # with no error-free read to anchor it, only trust a fresh prediction
            tol = FUZZY_TOL if shifts else FUZZY_TOL * 1.5 if slack <= 1.5 else 0.0
            for i, c in fuzzy.items():
                pred = expected[i] + shift
                if np.linalg.norm(c.mean(0) - pred.mean(0)) <= tol * _side(pred):
                    found[i] = c
        return found

    def _search(self, gray: np.ndarray, tag_id: int, pred: np.ndarray, slack: float):
        """(corners, hamming) of the best read of tag_id around its predicted corners, or None."""
        side = _side(pred)
        if not np.all(np.isfinite(pred)) or side < 4:
            return None
        pad = side * (1 + slack)
        x0, y0 = np.floor(pred.min(0) - pad).astype(int)
        x1, y1 = np.ceil(pred.max(0) + pad).astype(int)
        h, w = gray.shape
        x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, w), min(y1, h)
        if x1 - x0 < side or y1 - y0 < side:
            return None
        crop = gray[y0:y1, x0:x1]
        scale = float(np.clip(TARGET_CELL_PX * self._cells / side, 1, MAX_UPSCALE))
        big = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        sharp = cv2.addWeighted(big, 1.6, cv2.GaussianBlur(big, (0, 0), scale * 0.7), -0.6, 0)
        lo, hi = np.percentile(sharp, (1, 99))
        stretched = cv2.convertScaleAbs(sharp, alpha=255 / max(hi - lo, 1), beta=-lo * 255 / max(hi - lo, 1))
        best = None
        for img in (sharp, stretched, cv2.LUT(stretched, _GAMMA)):
            for d in self._det.detect(img):
                if d.tag_id != tag_id or d.hamming > max(self._max_hamming, 1):
                    continue
                key = (d.hamming, -d.decision_margin)
                if best is None or key < best[0]:
                    best = (key, np.asarray(d.corners, np.float64) / scale + [x0, y0], int(d.hamming))
            if best is not None and best[2] == 0:
                break
        return None if best is None else (best[1], best[2])


TARGET_CELL_PX = 8.0   # smart detection enlarges a crop until a tag cell is about this wide
MAX_UPSCALE = 4.0
FUZZY_TOL = 0.35       # a read with a bit error must lie within this many tag widths of its predicted spot


def _side(corners: np.ndarray) -> float:
    return float(np.mean(np.linalg.norm(corners - np.roll(corners, 1, axis=0), axis=1)))


def tag_corners(rect, quiet_cells: float = 2, cells: float = 8) -> np.ndarray:
    """Screen-pixel corners of a tag's black square, from the rectangle of its whole image
    (tag plus a white margin of `quiet_cells` on each side), in the detector's order:
    TR, TL, BL, BR (y down)."""
    x0, y0, x1, y1 = rect
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    half = (x1 - x0) * cells / (cells + 2 * quiet_cells) / 2
    return np.array([[cx + half, cy - half], [cx - half, cy - half], [cx - half, cy + half], [cx + half, cy + half]])
