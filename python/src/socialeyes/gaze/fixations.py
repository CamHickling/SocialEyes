"""Neon's fixations, on the screen and on the post images they landed on.

Companion detects fixations itself (its algorithm allows for head movement) and saves them in the
recording (fixations ps1.raw, with saccades: event_type 1 is a fixation). Each fixation's gaze
samples are mapped onto the screen by the phone tracking (gaze_screen.csv), then onto whatever
was under them at that moment (the feed scrolls, so every sample is placed with the layout of its
own time, as touches are). A fixation belongs to a post's image when most of its mapped samples
fall on that image; its image position is their median, in the image's own pixels, and its AOI
the one that position falls in.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from ..session.io import Session
from ..session.viewport import Layout
from ..study.aoi import aoiset_from_json

FIXATION_COLUMNS = ["fixation", "t_start_ns", "t_end_ns", "duration_ms", "step_id", "samples", "mapped",
                    "x_px", "y_px", "post_id", "element", "image_id", "img_x", "img_y", "aoi", "on_image",
                    "img_per_screen_px"]


def read_fixations(neon_dir: Path | str) -> pd.DataFrame:
    """start_ns, end_ns (Unix ns) of every fixation Companion detected."""
    path = Path(neon_dir)
    if not (path / "fixations ps1.raw").is_file():
        raise FileNotFoundError(f"{path}: no 'fixations ps1.raw' (Companion 2.8 or newer records fixations)")
    dt = np.dtype(ast.literal_eval((path / "fixations.dtype").read_text(encoding="utf-8")))
    a = np.fromfile(path / "fixations ps1.raw", dt)
    a = a[a["event_type"] == 1]
    return pd.DataFrame({"start_ns": a["start_timestamp_ns"].astype(np.int64),
                         "end_ns": a["end_timestamp_ns"].astype(np.int64)})


def build_images(build: Optional[Path], participant_id: str) -> tuple[dict, dict, dict]:
    """(post_id -> image_id in the participant's feed, image_id -> (w, h), image_id -> AOISet)."""
    if build is None:
        return {}, {}, {}
    manifest = json.loads((build / "study.json").read_text(encoding="utf-8"))
    plan = json.loads((build / "plans" / f"{participant_id}.json").read_text(encoding="utf-8"))
    sizes, aois = {}, {}
    for image_id, img in manifest["images"].items():
        sizes[image_id] = (img["width"], img["height"])
        if img.get("aoi"):
            aois[image_id] = aoiset_from_json(json.loads((build / img["aoi"]).read_text(encoding="utf-8")))
    return {e["post_id"]: e["image_id"] for e in plan["feed"]}, sizes, aois


def map_fixations(fix: pd.DataFrame, gaze: pd.DataFrame, session: Session, clock_offset_ns: int,
                  build: Optional[Path] = None) -> pd.DataFrame:
    """One row per fixation during the tracked steps (FIXATION_COLUMNS), in the session's clock.
    ``gaze`` is gaze_screen.csv (mapping.map_gaze)."""
    images, sizes, aois = build_images(build, session.participant_id)
    layout = Layout(session.viewport) if len(session.viewport) else None
    g = gaze.sort_values("unix_ns").reset_index(drop=True)
    gt = g["unix_ns"].to_numpy(np.int64)
    ok = g["x_px"].notna().to_numpy()
    if layout is not None and ok.any():
        loc = layout.locate(g.loc[ok, "t_ns"].to_numpy(np.int64), g.loc[ok, "x_px"], g.loc[ok, "y_px"])
        loc.index = g.index[ok]
        g = g.join(loc)
    else:
        g = g.assign(post_id="", element="", image_left=np.nan, image_top=np.nan, image_right=np.nan, image_bottom=np.nan)
    rows = []
    for k, f in enumerate(fix.itertuples()):
        a, b = np.searchsorted(gt, f.start_ns), np.searchsorted(gt, f.end_ns, side="right")
        s = g.iloc[a:b]
        if not len(s) or s["step_id"].isna().all():
            continue
        m = s[s["x_px"].notna()]
        row = {"fixation": k, "t_start_ns": int(f.start_ns - clock_offset_ns), "t_end_ns": int(f.end_ns - clock_offset_ns),
               "duration_ms": round((f.end_ns - f.start_ns) / 1e6, 1), "step_id": s["step_id"].dropna().mode().iloc[0],
               "samples": len(s), "mapped": round(len(m) / len(s), 3),
               "x_px": round(float(m["x_px"].median()), 1) if len(m) else None,
               "y_px": round(float(m["y_px"].median()), 1) if len(m) else None,
               "post_id": "", "element": "", "image_id": "", "img_x": None, "img_y": None, "aoi": "", "on_image": 0.0}
        if len(m):
            el = m[m["element"].fillna("") != ""]
            if len(el):
                top = el.groupby(["post_id", "element"]).size().idxmax()
                row["post_id"], row["element"] = top
            on = m[m["image_left"].notna() & (m["post_id"] == row["post_id"])]
            row["on_image"] = round(len(on) / len(m), 3)
            image_id = images.get(row["post_id"], "")
            if len(on) > len(m) / 2 and image_id and image_id in sizes:
                w, h = sizes[image_id]
                rw = on["image_right"] - on["image_left"]
                u = (on["x_px"] - on["image_left"]) / rw
                v = (on["y_px"] - on["image_top"]) / (on["image_bottom"] - on["image_top"])
                x, y = float(np.median(u)) * w, float(np.median(v)) * h
                row.update(image_id=image_id, img_x=round(x, 1), img_y=round(y, 1),
                           img_per_screen_px=round(float(w / rw.median()), 4))
                if image_id in aois:
                    row["aoi"] = aois[image_id].label_points(np.array([x]), np.array([y]))[0]
        rows.append(row)
    return pd.DataFrame(rows, columns=FIXATION_COLUMNS)

