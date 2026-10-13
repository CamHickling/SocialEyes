"""Smart tag detection (TagDetector.detect_expected) and reading scene frames in order (SceneVideo)."""
from __future__ import annotations

import cv2
import numpy as np

from socialeyes.gaze.neon import SceneVideo
from socialeyes.gaze.tags import TagDetector
from socialeyes.markers import tag_image


def square(cx, cy, side):
    """Corners of a tag's black square in the detector's order (TR, TL, BL, BR)."""
    h = side / 2
    return np.array([[cx + h, cy - h], [cx - h, cy - h], [cx - h, cy + h], [cx + h, cy + h]])


def scene_with(tag: np.ndarray, cx=400, cy=300, blur=0.0):
    """A white 800 x 600 frame with a tag image (black square + 2-cell margin) centred at (cx, cy)."""
    g = np.full((600, 800), 255, np.uint8)
    n = tag.shape[0]
    g[cy - n // 2:cy - n // 2 + n, cx - n // 2:cx - n // 2 + n] = tag
    return cv2.GaussianBlur(g, (0, 0), blur) if blur else g


def small_16h5(tag_id: int, side_px: int) -> np.ndarray:
    big = tag_image(tag_id, px_per_cell=20, family="tag16h5")  # 10 cells: 6 + a 2-cell margin each side
    n = round(side_px * 10 / 6)
    return cv2.resize(big, (n, n), interpolation=cv2.INTER_AREA)


def test_a_close_look_reads_a_small_blurred_tag_the_whole_frame_search_misses():
    det = TagDetector(family="tag16h5")
    g = scene_with(small_16h5(3, 12), blur=0.8)
    assert det.detect(g) == {}
    found = det.detect_expected(g, {3: square(403, 302, 12)}, ids=[3])  # prediction a few px off
    assert set(found) == {3}
    assert np.abs(found[3].mean(0) - [400, 300]).max() < 1.5


def test_a_read_with_one_bit_wrong_counts_only_at_its_predicted_spot():
    det = TagDetector(family="tag16h5")
    tag = tag_image(3, px_per_cell=8, family="tag16h5").copy()
    tag[32:40, 32:40] = 255 - tag[32:40, 32:40]  # flip one data cell
    g = scene_with(tag)
    assert det.detect(g) == {}  # tag16h5: only error-free reads anywhere
    assert set(det.detect_expected(g, {3: square(400, 300, 48)}, ids=[3])) == {3}
    assert det.detect_expected(g, {3: square(430, 300, 48)}, ids=[3]) == {}       # 0.6 tag widths off
    assert det.detect_expected(g, {3: square(400, 300, 48)}, ids=[3], slack=2.5) == {}  # old prediction, no anchor


def test_tags_not_on_screen_are_dropped():
    det = TagDetector(family="tag16h5")
    g = scene_with(tag_image(5, px_per_cell=8, family="tag16h5"))
    assert set(det.detect(g)) == {5}
    assert det.detect_expected(g, None, ids=[3]) == {}


def test_scene_video_returns_the_frames_asked_for_in_any_order(tmp_path):
    path = tmp_path / "v.avi"
    w = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 30, (64, 48))
    for k in range(20):
        w.write(np.full((48, 64, 3), k * 12, np.uint8))
    w.release()
    with SceneVideo(path) as video:
        got = [(i, round(float(g.mean()) / 12)) for i, g in video.gray([2, 3, 9])]
        got += [(i, round(float(g.mean()) / 12)) for i, g in video.gray([4, 19, 25])]  # back, then past the end
    assert got == [(2, 2), (3, 3), (9, 9), (4, 4), (19, 19)]
