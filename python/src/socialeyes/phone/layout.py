"""A study's on-screen tags on a particular phone (CAM-227).

The app writes device_profile.json into its files folder: screen size, the dpi it reports and the
ruler-checked dpi, rounded screen corners (Android 12+) and camera cut-outs. From it, this works out
where the study's tags would sit in the feed's bars (as TagBars.kt does: square tags of size_mm with
a one-cell quiet zone, side_inset_mm from the side edges and edge_gap_mm from the top and bottom) and
whether a rounded corner or a cut-out would clip one, or the top bar's row (wordmark and two icons)
wouldn't fit between the top tags.
"""
from __future__ import annotations

import math
from typing import Optional

CELLS = {"tag36h11": 8, "tag25h9": 7, "tag16h5": 6}
CORNERS = ("top_left", "top_right", "bottom_right", "bottom_left")
MIN_ROW_DP = 180   # the wordmark and two icons need about this much width between the top tags


def tag_boxes(profile: dict, tags: dict, side_inset_mm: Optional[float] = None, quiet_zone: bool = True) -> dict[str, tuple]:
    """Corner -> the tag in screen px, (left, top, right, bottom): its black square with the one-cell
    quiet zone around it, or (quiet_zone=False) the black square alone."""
    w, h = profile["screen_width_px"], profile["screen_height_px"]
    px_x = profile.get("xdpi", profile.get("xdpi_reported")) / 25.4
    px_y = profile.get("ydpi", profile.get("ydpi_reported")) / 25.4
    size = tags["size_mm"] * px_x
    cell = size / CELLS.get(tags.get("family", "tag16h5"), 6)
    inset = (tags.get("side_inset_mm", 5.0) if side_inset_mm is None else side_inset_mm) * px_x
    edge = tags.get("edge_gap_mm", 2.0) * px_y
    out = {}
    for corner in CORNERS:
        left = inset - cell if corner.endswith("left") else w - inset - size - cell
        top = edge - cell if corner.startswith("top") else h - edge - size - cell
        box = (left, top, left + size + 2 * cell, top + size + 2 * cell)
        out[corner] = box if quiet_zone else (box[0] + cell, box[1] + cell, box[2] - cell, box[3] - cell)
    return out


def _clipped(box: tuple, corner: str, r: float, w: int, h: int) -> bool:
    """Whether the box's outer corner lies outside the screen's rounded corner of radius r."""
    if not r:
        return False
    x = box[0] if corner.endswith("left") else w - box[2]          # distance from the side edge
    y = box[1] if corner.startswith("top") else h - box[3]         # from the top / bottom edge
    return x < r and y < r and math.hypot(r - x, r - y) > r


def _overlaps(a: tuple, b) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def layout_checks(profile: Optional[dict], tags: Optional[dict]) -> list[tuple[str, str]]:
    """(level, text) for the loader: 'warn' when this phone's screen would clip a tag or crowd the bar."""
    if not profile or not tags or tags.get("layout") != "bars" or not tags.get("steps"):
        return []
    out = []
    w, h = profile["screen_width_px"], profile["screen_height_px"]
    boxes = tag_boxes(profile, tags)
    # a rounded corner only matters where it cuts into the black square (the pattern the detector reads);
    # a bite out of the white quiet zone at the very corner is tolerated
    squares = tag_boxes(profile, tags, quiet_zone=False)
    corners = profile.get("rounded_corners") or {}
    clipped = [c for c in CORNERS if _clipped(squares[c], c, corners.get(c, 0), w, h)]
    if clipped:
        need = tags.get("side_inset_mm", 5.0)
        while need < 12 and any(_clipped(tag_boxes(profile, tags, need, quiet_zone=False)[c], c, corners.get(c, 0), w, h)
                                for c in clipped):
            need += 0.5
        out.append(("warn", f"This phone's rounded screen corners would clip the {', '.join(c.replace('_', '-') for c in clipped)} "
                            f"tag(s): set markers.on_screen.side_inset_mm to {need:g} mm (now {tags.get('side_inset_mm', 5.0):g})."))
    covered = [c for c in CORNERS if any(_overlaps(boxes[c], r) for r in profile.get("cutouts") or [])]
    if covered:
        out.append(("warn", f"The phone's camera cut-out covers the {', '.join(c.replace('_', '-') for c in covered)} tag(s): "
                            "the scene camera can't read it there; try a larger side inset or another phone."))
    row_dp = (boxes["top_right"][0] - boxes["top_left"][2]) / profile.get("density", 1)
    if row_dp < MIN_ROW_DP:
        out.append(("warn", f"Only {row_dp:.0f} dp between the top tags for the wordmark and icons (about {MIN_ROW_DP} "
                            "needed): smaller tags or a smaller side inset would make room."))
    return out


def ruler_check(profile: Optional[dict], eye_tracking: bool) -> list[tuple[str, str]]:
    """Whether this phone's screen size was checked with a ruler (it matters for eye tracking only)."""
    if not eye_tracking:
        return []
    if profile is None:
        return [("info", "Open SocialEyes on the phone once, so it can describe its screen (size, corners, cut-outs).")]
    if not profile.get("ruler_check"):
        return [("warn", "This phone's screen size hasn't been checked with a ruler: on the phone, tap Check screen size "
                         "(once per phone), so the tags and gaze use true millimetres.")]
    rc = profile["ruler_check"]
    return [("ok", f"Screen size checked with a ruler ({rc.get('measured_x_mm', 0):g} mm for 50, "
                   f"{rc.get('measured_y_mm', 0):g} mm for 100).")]
