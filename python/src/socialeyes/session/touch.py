"""Map touches onto feed content and estimate when a finger covered an AOI."""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from ..study.aoi import AOISet
from .gestures import assign_strokes
from .viewport import Layout

TARGET_COLUMNS = ["t_ns", "stroke", "pointer_id", "action", "x_px", "y_px", "step_id",
                  "post_id", "element", "image_id", "img_x", "img_y", "aoi"]
OCCLUSION_COLUMNS = ["stroke", "post_id", "image_id", "t_start_ns", "t_end_ns", "duration_ms",
                     "aoi_under_finger", "aois_covered"]


def touch_targets(
    touch: pd.DataFrame,
    layout: Layout,
    post_images: Optional[dict[str, str]] = None,
    aois: Optional[dict[str, AOISet]] = None,
    image_sizes: Optional[dict[str, tuple[int, int]]] = None,
) -> pd.DataFrame:
    """Every touch sample with the post/element under it.

    With ``post_images`` (post_id -> image_id shown to this participant, from
    their plan) and ``image_sizes`` the point is also given in image pixels, and
    with ``aois`` labelled with the AOI it falls in.
    """
    if touch is None or not len(touch):
        return pd.DataFrame(columns=TARGET_COLUMNS)
    post_images = post_images or {}
    aois = aois or {}
    image_sizes = image_sizes or {}
    t = touch.assign(stroke=assign_strokes(touch)).reset_index(drop=True)
    loc = layout.locate(t["t_ns"], t["x_px"], t["y_px"])
    out = pd.concat([t[["t_ns", "stroke", "pointer_id", "action", "x_px", "y_px", "step_id"]], loc], axis=1)
    on_image = out["image_left"].notna().to_numpy()
    out["image_id"] = [post_images.get(p, "") if on else "" for p, on in zip(out["post_id"], on_image)]
    out["img_x"] = np.nan
    out["img_y"] = np.nan
    out["aoi"] = ""
    for image_id, g in out[on_image & (out["image_id"] != "")].groupby("image_id"):
        size = image_sizes.get(image_id)
        if size is None and image_id in aois:
            size = (aois[image_id].width, aois[image_id].height)
        if size is None:
            continue
        u = (g["x_px"] - g["image_left"]) / (g["image_right"] - g["image_left"])
        v = (g["y_px"] - g["image_top"]) / (g["image_bottom"] - g["image_top"])
        out.loc[g.index, "img_x"] = u * size[0]
        out.loc[g.index, "img_y"] = v * size[1]
        if image_id in aois:
            out.loc[g.index, "aoi"] = aois[image_id].label_points(u * size[0], v * size[1])
    # keep the image's on-screen width for occlusion radius scaling
    out["image_screen_w"] = out["image_right"] - out["image_left"]
    return out[TARGET_COLUMNS + ["image_screen_w"]]


def _distance_to_polygon(x: np.ndarray, y: np.ndarray, poly: np.ndarray) -> np.ndarray:
    """Distance from each point to the polygon's outline."""
    a = poly
    b = np.roll(poly, -1, axis=0)
    ab = b - a
    denom = np.where((ab ** 2).sum(1) > 0, (ab ** 2).sum(1), 1.0)
    px = x[:, None] - a[None, :, 0]
    py = y[:, None] - a[None, :, 1]
    s = np.clip((px * ab[None, :, 0] + py * ab[None, :, 1]) / denom[None, :], 0, 1)
    dx = px - s * ab[None, :, 0]
    dy = py - s * ab[None, :, 1]
    return np.sqrt(dx ** 2 + dy ** 2).min(axis=1)


def occlusion(targets: pd.DataFrame, aois: dict[str, AOISet], px_per_mm: float,
              finger_radius_mm: float = 8.0) -> pd.DataFrame:
    """Periods when a finger rested on (or swiped over) an image, and the AOIs it covered.

    An AOI counts as covered when the touch point is inside it or within
    ``finger_radius_mm`` of its outline. This is an estimate: the finger and
    hand also cover the screen below the touch point, which is not modelled.
    """
    on = targets[(targets["image_id"] != "") & targets["img_x"].notna()
                 & targets["action"].isin(["down", "move", "up"])].copy()
    if not len(on):
        return pd.DataFrame(columns=OCCLUSION_COLUMNS)
    on["covered"] = ""
    for image_id, g in on.groupby("image_id"):
        if image_id not in aois:
            continue
        aset = aois[image_id]
        r_img = finger_radius_mm * px_per_mm * aset.width / g["image_screen_w"].to_numpy(float)
        x, y = g["img_x"].to_numpy(float), g["img_y"].to_numpy(float)
        hits = []
        for a in aset.aois:
            near = a.contains(x, y) | (_distance_to_polygon(x, y, a.polygon) <= r_img)
            hits.append(np.where(near, a.name, ""))
        on.loc[g.index, "covered"] = ["|".join(n for n in names if n) for names in zip(*hits)] if hits else ""

    # a run = consecutive samples of one stroke on one post
    run = ((on["stroke"] != on["stroke"].shift()) | (on["post_id"] != on["post_id"].shift())).cumsum()
    rows = []
    for _, g in on.groupby(run, sort=False):
        covered = sorted({n for c in g["covered"] for n in c.split("|") if n})
        under = g.loc[g["aoi"] != "", "aoi"]
        rows.append({
            "stroke": int(g["stroke"].iloc[0]),
            "post_id": g["post_id"].iloc[0],
            "image_id": g["image_id"].iloc[0],
            "t_start_ns": int(g["t_ns"].iloc[0]),
            "t_end_ns": int(g["t_ns"].iloc[-1]),
            "duration_ms": (int(g["t_ns"].iloc[-1]) - int(g["t_ns"].iloc[0])) / 1e6,
            "aoi_under_finger": under.mode().iloc[0] if len(under) else "",
            "aois_covered": "|".join(covered),
        })
    return pd.DataFrame(rows, columns=OCCLUSION_COLUMNS)
