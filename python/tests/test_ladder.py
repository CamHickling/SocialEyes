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
    text = report(__import__("pandas").DataFrame(rows, columns=["hold", "phase", "frame", "tag_id", "kind", "value_mm",
                                                               "size_mm", "apparent_px", "detected", "distance_mm"]), 885)
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
