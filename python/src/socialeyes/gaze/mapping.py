"""Gaze samples -> screen pixels, through each scene frame's phone mapping (tracking.py)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .neon import NeonRecording
from .tracking import homographies

MAX_FRAME_GAP_MS = 40.0   # a gaze sample uses the nearest scene frame within this (frames are ~33 ms apart)

GAZE_COLUMNS = ["unix_ns", "t_ns", "step_id", "x_px", "y_px", "on_screen", "source", "frame", "since_tags_ms"]


def map_gaze(rec: NeonRecording, tracking: pd.DataFrame, clock_offset_ns: int, screen_w: int, screen_h: int,
             max_frame_gap_ms: float = MAX_FRAME_GAP_MS) -> pd.DataFrame:
    """One row per gaze sample during the tracked steps (GAZE_COLUMNS). x_px / y_px are NaN
    when no nearby frame had a mapping; on_screen says whether the point falls on the screen."""
    if tracking.empty:
        return pd.DataFrame(columns=GAZE_COLUMNS)
    ft = tracking["unix_ns"].to_numpy(np.int64)
    Hs = homographies(tracking)
    has = np.isfinite(Hs[:, 0, 0])
    sel = (rec.gaze_t >= ft[0] - max_frame_gap_ms * 1e6) & (rec.gaze_t <= ft[-1] + max_frame_gap_ms * 1e6)
    gt = rec.gaze_t[sel]
    g = rec.undistort(rec.gaze[sel])
    # nearest frame (by time) for each sample
    j = np.clip(np.searchsorted(ft, gt), 1, len(ft) - 1)
    j = np.where(np.abs(ft[j - 1] - gt) <= np.abs(ft[j] - gt), j - 1, j)
    near = np.abs(ft[j] - gt) <= max_frame_gap_ms * 1e6
    use = near & has[j]
    xy = np.full((len(gt), 2), np.nan)
    if use.any():
        H = Hs[j[use]]
        p = np.einsum("nij,nj->ni", H, np.hstack([g[use], np.ones((use.sum(), 1))]))
        xy[use] = p[:, :2] / p[:, 2:3]
    on = (xy[:, 0] >= 0) & (xy[:, 0] < screen_w) & (xy[:, 1] >= 0) & (xy[:, 1] < screen_h)
    tr = tracking.iloc[j]
    return pd.DataFrame({
        "unix_ns": gt, "t_ns": gt - clock_offset_ns,
        "step_id": np.where(near, tr["step_id"].to_numpy(), None),
        "x_px": xy[:, 0], "y_px": xy[:, 1], "on_screen": on,
        "source": np.where(use, tr["source"].to_numpy(), ""),
        "frame": np.where(near, tr["frame"].to_numpy(), -1),
        "since_tags_ms": np.where(use, tr["since_tags_ms"].to_numpy(float), np.nan),
    }, columns=GAZE_COLUMNS)


def summary(tracking: pd.DataFrame, gaze: pd.DataFrame) -> pd.DataFrame:
    """Per step: share of scene frames mapped from tags / by flow, and of gaze samples mapped and on screen."""
    rows = []
    for step, f in tracking.groupby("step_id", sort=False):
        gs = gaze[gaze["step_id"] == step]
        rows.append({
            "step_id": step, "frames": len(f),
            "tags": round(float((f["source"] == "tags").mean()), 3),
            "flow": round(float((f["source"] == "flow").mean()), 3),
            "unmapped": round(float((f["source"] == "").mean()), 3),
            "gaze_samples": len(gs),
            "gaze_mapped": round(float(gs["x_px"].notna().mean()), 3) if len(gs) else 0.0,
            "gaze_on_screen": round(float(gs["on_screen"].mean()), 3) if len(gs) else 0.0,
        })
    return pd.DataFrame(rows)
