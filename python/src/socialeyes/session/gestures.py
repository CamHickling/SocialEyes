"""Turn raw touch samples into strokes and classify them as gestures.

Gestures are derived here rather than in the app, so the definitions can be
changed and re-run on old data. Defaults follow Android's ViewConfiguration
(touch slop 8 dp, long press 500 ms, double tap 300 ms, min fling velocity
50 dp/s): a "fling" is a stroke after which Android would keep the content
moving, a "scroll" one where the finger stopped before lifting.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class GestureParams:
    slop_dp: float = 8.0
    long_press_ms: float = 500.0
    double_tap_ms: float = 300.0
    double_tap_slop_dp: float = 100.0
    fling_min_dp_s: float = 50.0
    velocity_window_ms: float = 100.0


STROKE_COLUMNS = [
    "stroke", "pointer_id", "step_id", "t_start_ns", "t_end_ns", "duration_ms", "x0", "y0", "x1", "y1",
    "dx", "dy", "distance_dp", "path_dp", "mean_speed_dp_s", "end_speed_dp_s", "max_fingers",
    "cancelled", "direction", "gesture",
]


def assign_strokes(touch: pd.DataFrame) -> np.ndarray:
    """Stroke number for every touch sample (a stroke = one finger from down to up).

    Samples of a pointer that was never put down (a log that starts mid-stroke)
    get -1.
    """
    stroke = np.full(len(touch), -1, dtype=np.int64)
    active: dict[int, int] = {}
    next_id = 0
    for i, (action, pid) in enumerate(zip(touch["action"].to_numpy(), touch["pointer_id"].to_numpy())):
        if action == "down":
            active[pid] = next_id
            next_id += 1
        s = active.get(pid, -1)
        stroke[i] = s
        if action in ("up", "cancel"):
            active.pop(pid, None)
    return stroke


def _max_fingers(starts: np.ndarray, ends: np.ndarray) -> np.ndarray:
    """For each stroke, the largest number of strokes active at the same time during it."""
    out = np.ones(len(starts), dtype=np.int64)
    for i in range(len(starts)):
        # concurrency only rises when a stroke starts, so its maximum during
        # stroke i is reached at one of the start times inside [start_i, end_i]
        # (a finger lifting at the same instant another touches down doesn't count)
        times = starts[(starts >= starts[i]) & (starts < ends[i])] if ends[i] > starts[i] else starts[i:i + 1]
        active = (starts[None, :] <= times[:, None]) & (ends[None, :] > times[:, None])
        active[:, i] = True
        out[i] = int(active.sum(axis=1).max())
    return out


def strokes(touch: pd.DataFrame, px_per_dp: float, params: GestureParams = GestureParams()) -> pd.DataFrame:
    if touch is None or not len(touch):
        return pd.DataFrame(columns=STROKE_COLUMNS)
    t = touch.assign(stroke=assign_strokes(touch))
    t = t[t["stroke"] >= 0]
    rows = []
    for sid, g in t.groupby("stroke", sort=True):
        ts = g["t_ns"].to_numpy(np.int64)
        x = g["x_px"].to_numpy(float)
        y = g["y_px"].to_numpy(float)
        dur_ms = (ts[-1] - ts[0]) / 1e6
        dx, dy = x[-1] - x[0], y[-1] - y[0]
        path = float(np.hypot(np.diff(x), np.diff(y)).sum())
        win = ts >= ts[-1] - params.velocity_window_ms * 1e6
        wt = (ts[-1] - ts[win][0]) / 1e9
        end_speed = float(np.hypot(x[-1] - x[win][0], y[-1] - y[win][0]) / wt) if wt > 0 else 0.0
        rows.append({
            "stroke": int(sid),
            "pointer_id": int(g["pointer_id"].iloc[0]),
            "step_id": g["step_id"].iloc[0],
            "t_start_ns": int(ts[0]),
            "t_end_ns": int(ts[-1]),
            "duration_ms": dur_ms,
            "x0": x[0], "y0": y[0], "x1": x[-1], "y1": y[-1],
            "dx": dx, "dy": dy,
            "distance_dp": float(np.hypot(dx, dy)) / px_per_dp,
            "path_dp": path / px_per_dp,
            "mean_speed_dp_s": (path / px_per_dp) / (dur_ms / 1e3) if dur_ms > 0 else 0.0,
            "end_speed_dp_s": end_speed / px_per_dp,
            "cancelled": bool(g["action"].iloc[-1] == "cancel"),
            "ended": bool(g["action"].iloc[-1] in ("up", "cancel")),
        })
    df = pd.DataFrame(rows)
    df["max_fingers"] = _max_fingers(df["t_start_ns"].to_numpy(), df["t_end_ns"].to_numpy())
    df["direction"] = np.where(
        df["distance_dp"] < params.slop_dp, "",
        np.where(df["dy"].abs() >= df["dx"].abs(), np.where(df["dy"] < 0, "up", "down"),
                 np.where(df["dx"] < 0, "left", "right")),
    )
    df["gesture"] = [_classify(r, params) for r in df.itertuples()]
    _mark_double_taps(df, px_per_dp, params)
    return df[STROKE_COLUMNS]


def _classify(r, p: GestureParams) -> str:
    if r.max_fingers >= 2:
        return "pinch"
    if r.cancelled:
        return "cancel"
    if not r.ended:
        return "incomplete"
    if r.distance_dp < p.slop_dp:
        return "long_press" if r.duration_ms >= p.long_press_ms else "tap"
    return "fling" if r.end_speed_dp_s >= p.fling_min_dp_s else "scroll"


def _mark_double_taps(df: pd.DataFrame, px_per_dp: float, p: GestureParams) -> None:
    taps = df.index[df["gesture"] == "tap"].tolist()
    k = 0
    while k < len(taps) - 1:
        a, b = df.loc[taps[k]], df.loc[taps[k + 1]]
        gap_ms = (b["t_start_ns"] - a["t_end_ns"]) / 1e6
        dist_dp = float(np.hypot(b["x0"] - a["x0"], b["y0"] - a["y0"])) / px_per_dp
        if gap_ms <= p.double_tap_ms and dist_dp <= p.double_tap_slop_dp:
            df.loc[[taps[k], taps[k + 1]], "gesture"] = "double_tap"
            k += 2
        else:
            k += 1
