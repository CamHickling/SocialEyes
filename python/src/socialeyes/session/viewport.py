"""The feed layout over time: which post (and which part of it) is where on screen.

The app logs a frame whenever the layout changes; a frame stays in effect until
the next one. ``Layout`` answers "what was at screen point (x, y) at time t" and
how long each post and element was on screen.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# Most specific first: a point on the "edited" label is reported as label, not image.
# The comments sheet lies on top of the feed, so its comments and the sheet itself
# come before any feed element.
PRIORITY = ("label", "image", "header", "actions", "caption", "comments", "post")
NO_HIT = 10_000


def _rank(element: str) -> int:
    if element == "story":  # an open story covers the whole screen
        return 0
    if element == "sheet_input":  # the comment box lies over the bottom of the sheet
        return 1
    if element.startswith("sheet_comment_"):
        return 2
    if element == "sheet":
        return 3
    return 4 + PRIORITY.index(element)


def _is_overlay(element: str) -> bool:
    """Elements drawn over the feed: the comments sheet and an open story."""
    return element in ("sheet", "sheet_input", "story") or element.startswith("sheet_comment_")


class Layout:
    def __init__(self, viewport: pd.DataFrame):
        vp = viewport.reset_index(drop=True)
        is_frame = (vp["element"] == "frame").to_numpy()
        if len(vp) and not is_frame[0]:
            raise ValueError("viewport.csv must start with a frame row")
        frame_index = np.cumsum(is_frame) - 1
        self.times = vp.loc[is_frame, "t_ns"].to_numpy(np.int64)
        self.scroll_y = vp.loc[is_frame, "scroll_y"].to_numpy(float)
        el = vp.loc[~is_frame, ["post_id", "element", "left", "top", "right", "bottom"]].copy()
        el["fi"] = frame_index[~is_frame]
        el["rank"] = el["element"].map(_rank).astype(int)
        self.elements = el.reset_index(drop=True)
        self._by_frame = {fi: g for fi, g in self.elements.groupby("fi")}

    def frame_at(self, t_ns) -> np.ndarray:
        """Index of the frame in effect at each time (-1 before the first frame)."""
        return np.searchsorted(self.times, np.asarray(t_ns, np.int64), side="right") - 1

    def locate(self, t_ns, x, y) -> pd.DataFrame:
        """What is under each screen point.

        Returns one row per point: post_id, element (most specific element hit,
        '' if none) and image_left/top/right/bottom (the rectangle of the image
        under the point, NaN if the point is not on an image; a point on the
        label overlaying an image still counts as on the image).
        """
        t_ns = np.atleast_1d(np.asarray(t_ns, np.int64))
        x = np.atleast_1d(np.asarray(x, float))
        y = np.atleast_1d(np.asarray(y, float))
        n = len(t_ns)
        post = np.full(n, "", dtype=object)
        element = np.full(n, "", dtype=object)
        img = np.full((n, 4), np.nan)
        fi = self.frame_at(t_ns)
        for f in np.unique(fi):
            g = self._by_frame.get(f)
            if f < 0 or g is None:
                continue
            idx = np.flatnonzero(fi == f)
            px, py = x[idx, None], y[idx, None]
            L, T, R, B = (g[c].to_numpy(float)[None, :] for c in ("left", "top", "right", "bottom"))
            hit = (px >= L) & (px < R) & (py >= T) & (py < B)
            ranks = np.where(hit, g["rank"].to_numpy()[None, :], NO_HIT)
            best = ranks.argmin(axis=1)
            found = hit[np.arange(len(idx)), best]
            post[idx[found]] = g["post_id"].to_numpy()[best[found]]
            element[idx[found]] = g["element"].to_numpy()[best[found]]
            on_img = hit & (g["element"].to_numpy() == "image")[None, :]
            rows, cols = np.nonzero(on_img)
            rects = g[["left", "top", "right", "bottom"]].to_numpy(float)
            img[idx[rows]] = rects[cols]
        out = pd.DataFrame({"post_id": post, "element": element})
        out[["image_left", "image_top", "image_right", "image_bottom"]] = img
        return out

    def exposure(self, end_ns: int, area: tuple[float, float, float, float]) -> pd.DataFrame:
        """Time each post/element was on screen.

        ``area`` is the screen rectangle the feed is visible in; ``end_ns`` closes
        the last frame. While the comments sheet is open, feed elements count as
        visible only above the sheet's top edge, and not at all while a story is
        open; the sheet, its comments and stories may extend above ``area``. Columns: post_id, element, visible_s (any part on
        screen), full_s (>= 99.9% on screen), weighted_s (time x visible area
        fraction), first_visible_ns, entries (times it came into view).
        """
        cols = ["post_id", "element", "visible_s", "full_s", "weighted_s", "first_visible_ns", "entries"]
        el = self.elements
        if not len(el):
            return pd.DataFrame(columns=cols)
        next_t = np.append(self.times[1:], max(end_ns, self.times[-1]))
        dt = (next_t - self.times) / 1e9
        L, T, R, B = (el[c].to_numpy(float) for c in ("left", "top", "right", "bottom"))
        aL, aT, aR, aB = area
        sheet = el["element"].map(_is_overlay).to_numpy(bool)
        # what hides the feed in each frame: the sheet's top edge, everything while
        # a story is open (inf when nothing covers it)
        sheet_top = np.full(len(self.times), np.inf)
        is_sheet_row = (el["element"] == "sheet").to_numpy()
        np.minimum.at(sheet_top, el["fi"].to_numpy()[is_sheet_row], T[is_sheet_row])
        is_story_row = (el["element"] == "story").to_numpy()
        sheet_top[el["fi"].to_numpy()[is_story_row]] = -np.inf
        bottom = np.where(sheet, aB, np.minimum(aB, sheet_top[el["fi"].to_numpy()]))
        top = np.where(sheet, -np.inf, aT)
        w = np.clip(np.minimum(R, aR) - np.maximum(L, aL), 0, None)
        h = np.clip(np.minimum(B, bottom) - np.maximum(T, top), 0, None)
        full_area = (R - L) * (B - T)
        frac = np.divide(w * h, full_area, out=np.zeros_like(full_area), where=full_area > 0)
        d = el.assign(dt=dt[el["fi"].to_numpy()], frac=frac, t=self.times[el["fi"].to_numpy()])
        d["visible"] = d["frac"] > 0
        rows = []
        for (pid, element), g in d.groupby(["post_id", "element"], sort=False):
            vis = g[g["visible"]]
            frames = np.sort(vis["fi"].to_numpy())
            rows.append({
                "post_id": pid,
                "element": element,
                "visible_s": float(vis["dt"].sum()),
                "full_s": float(g.loc[g["frac"] >= 0.999, "dt"].sum()),
                "weighted_s": float((g["dt"] * g["frac"]).sum()),
                "first_visible_ns": int(vis["t"].min()) if len(vis) else None,
                "entries": int(len(frames) and 1 + (np.diff(frames) > 1).sum()),
            })
        return pd.DataFrame(rows, columns=cols)
