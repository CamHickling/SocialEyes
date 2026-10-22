"""Gaze accuracy at the validation dots, and the session's gaze offset from them (CAM-210, CAM-165).

For every dot the participant tapped (`validation_target`, then an `on_target` `validation_tap`)
in a step the phone was tracked in (validation steps listed in markers.on_screen.steps), the gaze
samples in the WINDOW_NS before the tap are compared with the dot:

- angle: between the gaze ray and the ray to the dot, from the scene camera (degrees of visual
  angle, near enough: the scene camera sits beside the eyes);
- on screen: the median gaze mapped onto the screen minus the dot, in mm.

Neon's remaining error is mostly a constant direction offset per wearer and session (CAM-210: 1.7
deg as recorded, about 0.4 deg once a per-session shift is removed). The offset is the median,
over the dots, of (dot - gaze) in normalised camera coordinates (x/z, y/z), so it holds whatever
the phone's distance or pose (a shift in screen pixels, as the 12 Oct analysis used, only holds at
the distance the dots were looked at). `shift_gaze` moves every gaze sample by it before the
mapping. The corrected accuracy is leave-one-out: each dot is corrected by the offset of the
others, so it isn't flattered by the dot's own error.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..session.io import Session
from .neon import NeonRecording
from .tracking import Screen, homographies

WINDOW_NS = 500_000_000     # gaze before each tap (gaze leads the finger)
MAX_FRAME_GAP_NS = 40_000_000
MIN_FRAMES = 3              # tracked scene frames a dot needs in its window
MIN_DOTS = 4                # fewer and the offset isn't trusted: gaze stays as recorded
WARN_RAW_DEG = 3.0          # an offset this large: check the wearer profile and the glasses' fit
WARN_CORRECTED_DEG = 1.5    # still this far off after the offset: the glasses moved, or a bad recording

DOT_COLUMNS = ["step_id", "index", "x_px", "y_px", "gaze_samples", "frames", "err_deg", "err_mm",
               "dx_mm", "dy_mm", "err_deg_corrected", "err_mm_corrected"]


def normalised(px: np.ndarray, K: np.ndarray) -> np.ndarray:
    """Undistorted scene pixels -> normalised camera coordinates (x/z, y/z)."""
    px = np.atleast_2d(np.asarray(px, float))
    return (px - K[:2, 2]) / np.array([K[0, 0], K[1, 1]])


def to_pixels(n: np.ndarray, K: np.ndarray) -> np.ndarray:
    n = np.atleast_2d(np.asarray(n, float))
    return n * np.array([K[0, 0], K[1, 1]]) + K[:2, 2]


def angle_deg(a: np.ndarray, b: np.ndarray) -> float:
    """Angle between the rays through two points in normalised camera coordinates."""
    ra, rb = np.append(a, 1.0), np.append(b, 1.0)
    c = ra @ rb / (np.linalg.norm(ra) * np.linalg.norm(rb))
    return float(np.degrees(np.arccos(np.clip(c, -1.0, 1.0))))


def shift_gaze(gaze_undistorted: np.ndarray, offset: np.ndarray | None, K: np.ndarray) -> np.ndarray:
    """Gaze (undistorted scene px) moved by a normalised-coordinate offset (None: unchanged)."""
    if offset is None:
        return gaze_undistorted
    return to_pixels(normalised(gaze_undistorted, K) + offset, K)


def _apply_h(H: np.ndarray, pts: np.ndarray) -> np.ndarray:
    p = np.hstack([np.atleast_2d(pts), np.ones((len(np.atleast_2d(pts)), 1))]) @ H.T
    return p[:, :2] / p[:, 2:3]


def _targets(session: Session) -> list[dict]:
    """Each validation dot that was tapped on target: step, index, screen px, shown and tap times."""
    ev = session.events_of("validation_target", "validation_tap")
    if not len(ev):
        return []
    out, shown = [], {}
    for e in ev.sort_values("t_ns").itertuples():
        key = (e.step_id, int(e.index))
        if e.type == "validation_target":
            shown[key] = {"step_id": e.step_id, "index": int(e.index), "xy": np.array([e.x_px, e.y_px], float),
                          "shown_ns": int(e.t_ns)}
        elif bool(getattr(e, "on_target", False)) and key in shown:
            out.append({**shown.pop(key), "tap_ns": int(e.t_ns)})
    return out


def score(rec: NeonRecording, session: Session, tracking: pd.DataFrame, clock_offset_ns: int):
    """(per-dot table, offset in normalised coordinates or None, summary dict)."""
    targets = _targets(session)
    summary: dict = {"dots": len(targets), "dots_scored": 0, "offset_applied": False, "warnings": []}
    if not targets:
        summary["warnings"].append("no validation dots tapped in this session")
        return pd.DataFrame(columns=DOT_COLUMNS), None, summary
    K = rec.K
    screen = Screen.of(session.device)
    ft = tracking["unix_ns"].to_numpy(np.int64) if len(tracking) else np.array([], np.int64)
    fstep = tracking["step_id"].to_numpy() if len(tracking) else np.array([])
    Hs = homographies(tracking) if len(tracking) else np.empty((0, 3, 3))
    has = np.isfinite(Hs[:, 0, 0]) if len(Hs) else np.array([], bool)
    gt = rec.gaze_t
    gu = rec.undistort(rec.gaze)

    dots = []
    for t in targets:
        t0 = max(t["tap_ns"] - WINDOW_NS, t["shown_ns"]) + clock_offset_ns
        t1 = t["tap_ns"] + clock_offset_ns
        fsel = np.where((ft >= t0 - MAX_FRAME_GAP_NS) & (ft <= t1 + MAX_FRAME_GAP_NS) & has & (fstep == t["step_id"]))[0]
        gsel = np.where((gt >= t0) & (gt <= t1))[0]
        if len(fsel) < MIN_FRAMES or not len(gsel):
            continue
        # each gaze sample against the dot as seen in its nearest tracked frame
        near = fsel[np.abs(ft[fsel][None, :] - gt[gsel][:, None]).argmin(axis=1)]
        ok = np.abs(ft[near] - gt[gsel]) <= MAX_FRAME_GAP_NS
        if ok.sum() < 3:
            continue
        gsel, near = gsel[ok], near[ok]
        dot_scene = np.vstack([_apply_h(np.linalg.inv(Hs[j]), t["xy"])[0] for j in near])
        d = normalised(dot_scene, K) - normalised(gu[gsel], K)          # per sample: dot - gaze
        on_screen = np.vstack([_apply_h(Hs[j], gu[i])[0] for i, j in zip(gsel, near)])
        mid = near[len(near) // 2]
        n_dot = normalised(_apply_h(np.linalg.inv(Hs[mid]), t["xy"]), K)[0]
        err = np.median(d, axis=0)
        dmm = screen.mm(np.median(on_screen, axis=0) - t["xy"])
        dots.append({"step_id": t["step_id"], "index": t["index"], "x_px": float(t["xy"][0]), "y_px": float(t["xy"][1]),
                     "gaze_samples": int(len(gsel)), "frames": int(len(np.unique(near))),
                     "err_deg": angle_deg(n_dot, n_dot - err), "err_mm": float(np.linalg.norm(dmm)),
                     "dx_mm": float(dmm[0]), "dy_mm": float(dmm[1]), "_err": err, "_n_dot": n_dot, "_H": Hs[mid]})

    summary["dots_scored"] = len(dots)
    if not dots:
        summary["warnings"].append("no validation dot could be scored: list the validation steps in "
                                   "markers.on_screen.steps so the phone can be tracked while they show")
        return pd.DataFrame(columns=DOT_COLUMNS), None, summary

    errs = np.array([x["_err"] for x in dots])
    for k, x in enumerate(dots):   # leave-one-out correction
        others = np.delete(errs, k, axis=0)
        if not len(others):
            x["err_deg_corrected"] = x["err_mm_corrected"] = np.nan
            continue
        resid = x["_err"] - np.median(others, axis=0)
        x["err_deg_corrected"] = angle_deg(x["_n_dot"], x["_n_dot"] - resid)
        gaze_px = to_pixels(x["_n_dot"] - resid, K)
        x["err_mm_corrected"] = float(np.linalg.norm(screen.mm(_apply_h(x["_H"], gaze_px)[0] - [x["x_px"], x["y_px"]])))
    table = pd.DataFrame([{k: v for k, v in x.items() if not k.startswith("_")} for x in dots], columns=DOT_COLUMNS)

    offset = np.median(errs, axis=0) if len(dots) >= MIN_DOTS else None
    summary.update(_summarise(table, errs, offset, K))
    if offset is None:
        summary["warnings"].append(f"only {len(dots)} validation dot(s) scored (at least {MIN_DOTS} needed): "
                                   "gaze is left as recorded, without an offset correction")
    else:
        if summary["offset_deg"] > WARN_RAW_DEG:
            summary["warnings"].append(f"gaze offset {summary['offset_deg']:.1f} deg: check the wearer profile "
                                       "(no offset correction in Companion) and how the glasses sit")
        if summary["corrected_deg_median"] > WARN_CORRECTED_DEG:
            summary["warnings"].append(f"accuracy after the offset is {summary['corrected_deg_median']:.1f} deg "
                                       "(median): the glasses may have moved during the session")
    return table, offset, summary


def _summarise(table: pd.DataFrame, errs: np.ndarray, offset: np.ndarray | None, K: np.ndarray) -> dict:
    s = {"raw_deg_median": float(table["err_deg"].median()), "raw_deg_mean": float(table["err_deg"].mean()),
         "raw_mm_median": float(table["err_mm"].median()),
         "corrected_deg_median": float(table["err_deg_corrected"].median()),
         "corrected_deg_mean": float(table["err_deg_corrected"].mean()),
         "corrected_mm_median": float(table["err_mm_corrected"].median())}
    if offset is not None:
        s["offset_normalised"] = [float(v) for v in offset]
        s["offset_deg"] = angle_deg(np.zeros(2), offset)
        s["offset_deg_xy"] = [float(np.degrees(np.arctan(v))) for v in offset]
    # drift: the offset of each validation step (e.g. before vs after the feed)
    per_step = {}
    for step, g in table.groupby("step_id", sort=False):
        e = errs[g.index.to_numpy()]
        per_step[step] = {"dots": len(g), "raw_deg_median": float(g["err_deg"].median()),
                          "offset_deg_xy": [float(np.degrees(np.arctan(v))) for v in np.median(e, axis=0)]}
    s["steps"] = per_step
    return s


def report(summary: dict) -> str:
    if not summary.get("dots_scored"):
        return "Validation: " + "; ".join(summary["warnings"])
    lines = [f"Validation: {summary['dots_scored']} of {summary['dots']} dots scored",
             f"  accuracy as recorded: {summary['raw_deg_median']:.2f} deg median ({summary['raw_mm_median']:.1f} mm on screen)",
             f"  after the offset (leave-one-out): {summary['corrected_deg_median']:.2f} deg median "
             f"({summary['corrected_mm_median']:.1f} mm on screen)"]
    if "offset_deg" in summary:
        x, y = summary["offset_deg_xy"]
        lines.append(f"  offset {summary['offset_deg']:.2f} deg (x {x:+.2f}, y {y:+.2f}) "
                     + ("applied to all gaze" if summary.get("offset_applied") else "not applied"))
    for step, s in summary.get("steps", {}).items():
        x, y = s["offset_deg_xy"]
        lines.append(f"  {step}: {s['dots']} dots, {s['raw_deg_median']:.2f} deg as recorded, offset x {x:+.2f} y {y:+.2f} deg")
    lines += [f"  warning: {w}" for w in summary["warnings"]]
    return "\n".join(lines)
