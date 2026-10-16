"""Copies of a session's front camera video with the face blurred, for sharing.

Each frame's face box (from face.csv, widened by MARGIN, more above for the hair) is replaced
by a smooth smear of its average colours (shrunk to 3 x 4 pixels and blown up again): a plain
blur or pixelation leaves a face recognisable at a glance (checked on studies/face_test). A
frame where no face was found is smeared whole: the detector may have missed a face there, and
a shared file must never show one. The hair outside the box, clothes and the room stay visible.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from ..session.io import load_session
from .analyze import video_frames

MARGIN = 0.3
MARGIN_ABOVE = 0.6


def _cover(img: np.ndarray, box: tuple[int, int, int, int]) -> None:
    import cv2

    x0, y0, x1, y1 = box
    if x1 - x0 < 2 or y1 - y0 < 2:
        return
    roi = img[y0:y1, x0:x1]
    w, h = x1 - x0, y1 - y0
    small = cv2.resize(roi, (3, 4), interpolation=cv2.INTER_AREA)
    # smoothed at 1/16 scale (a full-size blur this wide would take seconds per frame)
    mid = cv2.resize(small, (max(2, w // 16), max(2, h // 16)), interpolation=cv2.INTER_LINEAR)
    mid = cv2.GaussianBlur(mid, (0, 0), max(1.0, max(w, h) / 160))
    roi[:] = cv2.resize(mid, (w, h), interpolation=cv2.INTER_LINEAR)


def blur_session(session_dir: Path | str, faces: pd.DataFrame, out_dir: Path | str,
                 progress: Callable[[int, int], None] = lambda n, total: None) -> list[Path]:
    """Writes <out_dir>/front_NNN.mp4 (one per segment, same frames) with the faces blurred."""
    import cv2

    s = load_session(session_dir)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    fps = float((s.meta.get("camera") or {}).get("fps") or 30)
    # each box also covers where the face was two frames either side: fast movements
    f = faces.sort_values(["segment", "frame"]).copy()
    for c, how in (("box_left", "min"), ("box_top", "min"), ("box_right", "max"), ("box_bottom", "max")):
        f[c] = getattr(f.groupby("segment")[c].rolling(5, center=True, min_periods=1), how)().reset_index(level=0, drop=True)
    boxes = {(int(r.segment), int(r.frame)): r for r in f.itertuples()}
    writers: dict[int, cv2.VideoWriter] = {}
    files = []
    total = len(s.camera_frames) if s.camera_frames is not None else 0
    try:
        for n, (seg, k, _t, img) in enumerate(video_frames(s)):
            h, w = img.shape[:2]
            if seg not in writers:
                path = out / f"front_{seg:03d}.mp4"
                writers[seg] = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
                files.append(path)
            r = boxes.get((seg, k))
            if r is not None and r.face == 1 and r.box_right == r.box_right:
                mx, my = (r.box_right - r.box_left) * MARGIN, (r.box_bottom - r.box_top) * MARGIN
                box = (int(max(0, r.box_left - mx)), int(max(0, r.box_top - (r.box_bottom - r.box_top) * MARGIN_ABOVE)),
                       int(min(w, r.box_right + mx)), int(min(h, r.box_bottom + my)))
                _cover(img, box)
            else:
                _cover(img, (0, 0, w, h))
            writers[seg].write(img)
            if n % 100 == 0:
                progress(n, total)
    finally:
        for wr in writers.values():
            wr.release()
    return files
