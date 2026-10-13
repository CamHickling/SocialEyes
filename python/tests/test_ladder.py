"""Tag size ladder analysis (socialeyes.gaze.ladder) on a rendered scene with a known pose."""
from __future__ import annotations

import cv2
import numpy as np

from socialeyes.gaze.ladder import Arrangement, arrangements, observe, report
from socialeyes.gaze.tags import TagDetector, tag_corners
from socialeyes.gaze.tracking import Screen
from socialeyes.markers import tag_image
from socialeyes.session.io import load_session, write_session

K = np.array([[885.0, 0, 800], [0, 885.0, 600], [0, 0, 1]])
SCREEN = Screen(1080, 2400, 397.6, 395.8)
PX_PER_MM = 397.6 / 25.4


def rect(cx_mm, cy_mm, size_mm):
    """Whole-image rectangle (12 cells) of a tag whose black square is centred at (cx, cy) mm."""
    half = size_mm * 1.5 / 2 * PX_PER_MM
    return [cx_mm * PX_PER_MM - half, cy_mm * PX_PER_MM - half, cx_mm * PX_PER_MM + half, cy_mm * PX_PER_MM + half]


# four reference tags (always readable) plus one tiny and one medium test tag
LAYOUT = {
    20: ("size", 3.0, 3.0, rect(34.5, 70, 3.0)),
    21: ("size", 10.0, 10.0, rect(34.5, 100, 10.0)),
    24: ("left_inset", 6.0, 14.0, rect(13, 30, 14.0)),
    28: ("right_inset", 6.0, 14.0, rect(56, 30, 14.0)),
    32: ("top_gap", 3.5, 14.0, rect(13, 130, 14.0)),
    34: ("bottom_gap", 3.5, 14.0, rect(56, 130, 14.0)),
}


def render(R, t):
    canvas = np.full((2400, 1080), 255, np.uint8)
    for i, (*_, (x0, y0, x1, y1)) in LAYOUT.items():
        img = cv2.resize(tag_image(i, px_per_cell=20), (round(x1 - x0), round(y1 - y0)), interpolation=cv2.INTER_NEAREST)
        canvas[round(y0):round(y0) + img.shape[0], round(x0):round(x0) + img.shape[1]] = img
    M = K @ np.column_stack([R[:, 0], R[:, 1], t]) @ SCREEN.S
    return cv2.warpPerspective(canvas, M, (1600, 1200), flags=cv2.INTER_AREA, borderValue=60)


def test_observe_detects_big_tags_and_measures_apparent_size():
    R = cv2.Rodrigues(np.array([0.3, 0.0, 0.0]))[0]
    t = np.array([-34.5, -76.0, 330.0])  # screen centre ~33 cm in front of the camera
    arr = Arrangement(0, 0, 0, 1, {i: tag_corners(v[3]) for i, v in LAYOUT.items()},
                      {i: {"kind": k, "value_mm": v, "size_mm": s} for i, (k, v, s, _) in LAYOUT.items()})
    rows = list(observe([(7, 0, render(R, t))], arr, K, np.zeros(8), SCREEN, TagDetector()))
    by_id = {r[3]: r for r in rows}
    assert set(by_id) == set(LAYOUT)
    detected = {i: r[8] for i, r in by_id.items()}
    assert not detected[20]  # 3 mm: ~8 px wide, unreadable
    assert all(detected[i] for i in (21, 24, 28, 32, 34))
    # apparent width matches the true pose's projection of the tag
    M = K @ np.column_stack([R[:, 0], R[:, 1], t]) @ SCREEN.S
    c = cv2.perspectiveTransform(tag_corners(LAYOUT[21][3]).reshape(-1, 1, 2), M).reshape(-1, 2)
    truth = np.mean(np.linalg.norm(c - np.roll(c, 1, axis=0), axis=1))
    assert abs(by_id[21][7] - truth) < 0.3
    assert abs(by_id[21][9] - np.linalg.norm(t)) < 5
    from socialeyes.gaze.ladder import OBS_COLUMNS
    text = report(__import__("pandas").DataFrame(rows, columns=OBS_COLUMNS), 885)
    assert "size (middle)" in text and "3 mm:   0%" in text


def test_arrangements_from_the_session_log(tmp_path):
    meta = {"format": "socialeyes-session", "format_version": 1, "participant_id": "T01",
            "clock": {"elapsed_ns": 0, "wall_ms": 1_000}, "device": {"screen_width_px": 1080, "screen_height_px": 2400,
                                                                     "xdpi": 397.6, "ydpi": 395.8, "density_dpi": 400},
            "end": {"clock": {"elapsed_ns": 90_000_000_000, "wall_ms": 91_000}}}
    tags = {str(i): v[3] for i, v in LAYOUT.items()}
    info = {str(i): {"kind": k, "value_mm": v, "size_mm": s} for i, (k, v, s, _) in LAYOUT.items()}
    events = [
        {"t_ns": 1_000_000_000, "type": "tag_ladder_hold", "step_id": "ladder", "hold": 0, "status": "start"},
        {"t_ns": 1_100_000_000, "type": "marker_layout", "step_id": "ladder", "tags": tags,
         "ladder": {"hold": 0, "phase": 0, "tags": info}},
        {"t_ns": 6_100_000_000, "type": "marker_layout", "step_id": "ladder", "tags": tags,
         "ladder": {"hold": 0, "phase": 1, "tags": info}},
        {"t_ns": 9_000_000_000, "type": "tag_ladder_hold", "step_id": "ladder", "hold": 0, "status": "end"},
        {"t_ns": 20_000_000_000, "type": "marker_layout", "step_id": "feed", "on_screen": True, "tags": tags},
    ]
    write_session(tmp_path, meta, events, [])
    arrs = arrangements(load_session(tmp_path))
    assert [(a.hold, a.phase, a.start_ns, a.end_ns) for a in arrs] == [
        (0, 0, 1_100_000_000, 6_100_000_000), (0, 1, 6_100_000_000, 9_000_000_000)]
    assert arrs[0].info[21]["size_mm"] == 10.0


def bars_arrangement(family, size_mm, ids):
    """Four tags of `family` in the screen's corners, as tag_bars logs them (TL, TR, BR, BL)."""
    from socialeyes.markers import FAMILY_CELLS
    cells = FAMILY_CELLS[family]
    half = size_mm / 2
    centres = [(8 + half, 8 + half), (61 - half, 8 + half), (61 - half, 142 - half), (8 + half, 142 - half)]
    corners = ["top_left", "top_right", "bottom_right", "bottom_left"]
    rects, info = {}, {}
    for k, (i, (cx, cy)) in enumerate(zip(ids, centres)):
        h = size_mm * (cells + 4) / cells / 2 * PX_PER_MM  # the whole image: tag + 2-cell margin
        rects[i] = [cx * PX_PER_MM - h, cy * PX_PER_MM - h, cx * PX_PER_MM + h, cy * PX_PER_MM + h]
        info[i] = {"kind": "bars", "value_mm": size_mm, "size_mm": size_mm, "family": family, "cells": cells,
                   "grey": 0.0, "variant": f"{family[3:]} {size_mm:g} mm", "corner": corners[k]}
    canvas = np.full((2400, 1080), 255, np.uint8)
    for i, (x0, y0, x1, y1) in rects.items():
        img = cv2.resize(tag_image(i, px_per_cell=20, family=family), (round(x1 - x0), round(y1 - y0)),
                         interpolation=cv2.INTER_NEAREST)
        canvas[round(y0):round(y0) + img.shape[0], round(x0):round(x0) + img.shape[1]] = img
    arr = Arrangement(0, 0, 0, 1, {i: tag_corners(r, cells=cells) for i, r in rects.items()}, info,
                      {"variant": info[ids[0]]["variant"], "top_bar_dp": 80.0, "tab_bar_dp": 70.0, "feed_px": 1500.0})
    return arr, canvas


def test_bars_count_every_frame_and_read_small_16h5_tags():
    import pandas as pd
    from socialeyes.gaze.ladder import OBS_COLUMNS, bars_table
    R = cv2.Rodrigues(np.array([0.3, 0.0, 0.0]))[0]
    t = np.array([-34.5, -76.0, 330.0])
    rows = []
    for family, size, ids in (("tag16h5", 9.0, [0, 1, 2, 3]), ("tag36h11", 2.0, [60, 61, 62, 63])):
        arr, canvas = bars_arrangement(family, size, ids)
        M = K @ np.column_stack([R[:, 0], R[:, 1], t]) @ SCREEN.S
        scene = cv2.warpPerspective(canvas, M, (1600, 1200), flags=cv2.INTER_AREA, borderValue=60)
        rows += list(observe([(7, 0, scene)], arr, K, np.zeros(8), SCREEN, TagDetector(family=family)))
    obs = pd.DataFrame(rows, columns=OBS_COLUMNS)
    table = bars_table(obs).set_index("variant")
    assert table.loc["16h5 9 mm", "top_and_bottom"] == 1.0
    # 2 mm tags are unreadable: no pose, but the frame still counts against the variant
    assert table.loc["36h11 2 mm", "frames"] == 1 and table.loc["36h11 2 mm", "none"] == 1.0
    assert "16h5 9 mm" in report(obs, 885)
