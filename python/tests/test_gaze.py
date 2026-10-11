"""Phone tracking and gaze mapping (socialeyes.gaze), on synthetic scenes with a known pose."""
from __future__ import annotations

import cv2
import numpy as np
import pandas as pd

from socialeyes.gaze.mapping import map_gaze
from socialeyes.gaze.neon import NeonRecording
from socialeyes.gaze.tags import tag_corners
from socialeyes.gaze.tracking import TRACKING_COLUMNS, PhoneTracker, Screen, apply_h, solve_pose

K = np.array([[890.0, 0, 800], [0, 890.0, 600], [0, 0, 1]])
NO_DIST = np.zeros(8)
SCREEN = Screen(1080, 2400, 397.6, 395.8)
# four on-screen tags as the app lays them out (whole-image rects, 12 cells with a 2-cell margin)
TAGS = {i: tag_corners(r) for i, r in {
    0: (58, -18, 270, 194), 1: (810, -18, 1022, 194), 2: (810, 2206, 1022, 2418), 3: (58, 2206, 270, 2418)}.items()}
GRID = np.array([[x, y] for x in (60, 540, 1020) for y in (100, 1200, 2300)], float)


def pose(rx=0.35, ry=-0.1, rz=0.05, t=(-35.0, -60.0, 360.0)):
    R = cv2.Rodrigues(np.array([rx, ry, rz]))[0]
    return R, np.array(t)


def screen_to_scene(R, t):
    return K @ np.column_stack([R[:, 0], R[:, 1], t]) @ SCREEN.S


def project(R, t, ids=TAGS):
    M = screen_to_scene(R, t)
    return {i: apply_h(M, TAGS[i]) for i in ids}


def err_mm(H, R, t):
    """How far grid points land from where they should, mapped scene -> screen with H."""
    scene = apply_h(screen_to_scene(R, t), GRID)
    return np.linalg.norm(SCREEN.mm(apply_h(H, scene) - GRID), axis=1).max()


def test_tag_corners_match_black_square():
    c = tag_corners((0, 0, 120, 120))
    assert np.allclose(c, [[100, 20], [20, 20], [20, 100], [100, 100]])  # TR, TL, BL, BR


def test_pnp_recovers_the_screen_from_four_tags():
    R, t = pose()
    p = solve_pose(project(R, t), TAGS, K, SCREEN)
    assert p is not None and p.rms < 1e-3
    assert err_mm(p.H, R, t) < 0.01
    assert abs(np.linalg.norm(p.t) - np.linalg.norm(t)) < 0.1


def test_pnp_from_one_tag_uses_the_previous_pose():
    R, t = pose()
    p = solve_pose(project(R, t, ids=(2,)), TAGS, K, SCREEN, prev_R=R)
    assert p is not None and err_mm(p.H, R, t) < 0.05


def test_noisy_corners_hurt_pnp_less_than_a_homography():
    rng = np.random.default_rng(1)
    R, t = pose()
    pnp, hom = [], []
    for _ in range(30):
        dets = {i: c + rng.normal(0, 0.4, c.shape) for i, c in project(R, t, ids=(0, 1)).items()}
        pnp.append(err_mm(solve_pose(dets, TAGS, K, SCREEN).H, R, t))
        H, _ = cv2.findHomography(np.vstack([dets[0], dets[1]]), np.vstack([TAGS[0], TAGS[1]]))
        hom.append(err_mm(H, R, t))
    assert np.median(pnp) < np.median(hom) / 2


def test_a_badly_placed_tag_is_left_out():
    R, t = pose()
    dets = project(R, t)
    dets[3] = dets[3] + [25.0, -10.0]  # e.g. a thumb half over the tag
    p = solve_pose(dets, TAGS, K, SCREEN)
    assert p is not None and 3 not in p.tag_ids and err_mm(p.H, R, t) < 0.05


def test_no_tags_no_pose():
    assert solve_pose({}, TAGS, K, SCREEN) is None
    assert solve_pose({7: TAGS[0]}, TAGS, K, SCREEN) is None  # a tag that isn't on this screen


def _texture(shape=(1200, 1600), seed=0):
    img = np.random.default_rng(seed).integers(0, 255, (shape[0] // 8, shape[1] // 8), dtype=np.uint8)
    return cv2.GaussianBlur(cv2.resize(img, shape[::-1], interpolation=cv2.INTER_NEAREST), (5, 5), 0)


def test_tracker_bridges_a_short_gap_with_flow_then_gives_up():
    R, t = pose()
    tracker = PhoneTracker(K, NO_DIST, SCREEN, max_bridge_ms=100)
    base = _texture()
    first = tracker.update(0, base, project(R, t), TAGS)
    assert first.source == "tags"
    # the whole scene (phone included) shifts 3 px right per frame; no tags readable
    results = []
    for k in range(1, 6):
        T = np.array([[1, 0, 3.0 * k], [0, 1, 0], [0, 0, 1]])
        frame = cv2.warpAffine(base, T[:2], base.shape[::-1])
        results.append((k, T, tracker.update(k * 33_000_000, frame, {}, TAGS)))
    for k, T, r in results[:3]:  # 33, 66, 99 ms: bridged
        assert r.source == "flow"
        truth = first.H @ np.linalg.inv(T)
        scene = apply_h(np.linalg.inv(truth), GRID)
        assert np.abs(SCREEN.mm(apply_h(r.H, scene) - GRID)).max() < 0.3
    assert [r.source for _, _, r in results[3:]] == ["", ""]  # past 100 ms


def test_map_gaze_uses_the_nearest_frame_and_flags_off_screen():
    R, t = pose()
    H = solve_pose(project(R, t), TAGS, K, SCREEN).H
    M = np.linalg.inv(H)
    on, off = apply_h(M, [[540, 1200]])[0], apply_h(M, [[540, 3000]])[0]
    rec = NeonRecording(path=None, K=K, dist=NO_DIST, gaze=np.array([on, off, on]),
                        gaze_t=np.array([1_000, 10_000_000, 200_000_000], dtype=np.int64), scene_t=np.array([0]))
    row = [0, 0, -5, "feed", "tags", 4, "0 1 2 3", 0.1, 400.0, 0.0, *H.ravel()]
    tracking = pd.DataFrame([row], columns=TRACKING_COLUMNS)
    g = map_gaze(rec, tracking, clock_offset_ns=5, screen_w=1080, screen_h=2400)
    assert len(g) == 2  # the third sample is 200 ms from any frame
    assert np.allclose(g.loc[0, ["x_px", "y_px"]].astype(float), [540, 1200], atol=1e-6)
    assert g["on_screen"].tolist() == [True, False]
    assert g["t_ns"].tolist() == [1_000 - 5, 10_000_000 - 5]
