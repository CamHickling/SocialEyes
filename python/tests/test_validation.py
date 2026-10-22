"""Validation dots: accuracy, the session's gaze offset, and its leave-one-out correction."""
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from socialeyes.gaze import validation as v
from socialeyes.gaze.tracking import TRACKING_COLUMNS

K = np.array([[1000.0, 0, 800], [0, 1000.0, 600], [0, 0, 1]])
OFFSET = np.array([0.02, -0.01])      # dot - gaze, normalised: about 1.15 deg right, 0.57 deg up
# the phone straight ahead: screen px = scene px x 2, shifted (a simple homography)
H = np.array([[2.0, 0, -400], [0, 2.0, -300], [0, 0, 1]])


def fake(n_dots=9, offset=OFFSET, noise=0.0, tagged=("val1",), seed=0):
    """A recording and session: 9 dots, 0.6 s each, gaze steady on each dot but shifted by `offset`."""
    rng = np.random.default_rng(seed)
    Hinv = np.linalg.inv(H)
    events, frames, gaze, gaze_t = [], [], [], []
    t = 1_000_000_000
    for k in range(n_dots):
        xy = np.array([150 + 350 * (k % 3), 300 + 700 * (k // 3)], float)
        events.append({"t_ns": t, "type": "validation_target", "step_id": "val1", "index": k, "x_px": xy[0], "y_px": xy[1],
                       "on_target": np.nan})
        p = Hinv @ np.append(xy, 1)
        dot_scene = p[:2] / p[2]
        for s in range(20):                     # 200 Hz gaze for 100 ms ... 600 ms after the dot shows
            ts = t + 100_000_000 + s * 25_000_000
            n = v.normalised(dot_scene, K)[0] - offset + rng.normal(0, noise, 2)
            gaze.append(v.to_pixels(n, K)[0])
            gaze_t.append(ts)
        for f in range(20):                     # 30 fps frames
            frames.append([f, t + f * 33_000_000, t + f * 33_000_000, "val1" if "val1" in tagged else "feed",
                           "tags", 4, "0 1 2 3", 0.5, 350.0, 0.0, *H.ravel()])
        events.append({"t_ns": t + 590_000_000, "type": "validation_tap", "step_id": "val1", "index": k,
                       "x_px": xy[0], "y_px": xy[1], "on_target": True})
        t += 700_000_000
    ev = pd.DataFrame(events)
    session = SimpleNamespace(
        events_of=lambda *types: ev[ev["type"].isin(types)],
        device={"screen_width_px": 1080, "screen_height_px": 2400, "xdpi": 400.0, "ydpi": 400.0})
    rec = SimpleNamespace(K=K, gaze=np.array(gaze), gaze_t=np.array(gaze_t, np.int64), undistort=lambda p: np.asarray(p, float))
    return rec, session, pd.DataFrame(frames, columns=TRACKING_COLUMNS)


def test_offset_is_found_and_corrected():
    rec, session, tracking = fake()
    dots, offset, s = v.score(rec, session, tracking, 0)
    assert s["dots_scored"] == 9 and len(dots) == 9
    assert offset == pytest.approx(OFFSET, abs=1e-6)
    # |(0.02, -0.01)| is 1.28 deg straight ahead; dots off to the side see the same shift as a little less
    assert 1.0 < s["raw_deg_median"] < 1.28
    assert s["corrected_deg_median"] < 0.01 and s["warnings"] == []
    assert s["offset_deg_xy"] == pytest.approx([1.15, -0.57], abs=0.01)
    # on screen: 2 screen px per scene px, 400 dpi
    assert dots["err_mm"].median() == pytest.approx(np.linalg.norm(OFFSET * 1000 * 2) * 25.4 / 400, rel=0.05)


def test_leave_one_out_is_honest_with_noisy_dots():
    rec, session, tracking = fake(noise=0.004, seed=3)
    dots, offset, s = v.score(rec, session, tracking, 0)
    # each dot's own error isn't used to correct it, so the corrected error stays above zero
    assert 0.02 < s["corrected_deg_median"] < s["raw_deg_median"]


def test_shift_gaze_moves_by_the_offset_and_none_leaves_it():
    g = np.array([[800.0, 600.0], [1000.0, 500.0]])
    assert v.shift_gaze(g, None, K) is g
    moved = v.shift_gaze(g, OFFSET, K)
    assert moved - g == pytest.approx(np.tile(OFFSET * 1000, (2, 1)))


def test_untracked_validation_is_a_warning_not_an_offset():
    rec, session, tracking = fake(tagged=())          # frames only in the feed: dots can't be placed
    dots, offset, s = v.score(rec, session, tracking, 0)
    assert offset is None and dots.empty
    assert any("markers.on_screen.steps" in w for w in s["warnings"])
    assert "markers.on_screen.steps" in v.report(s)


def test_too_few_dots_leave_gaze_as_recorded():
    rec, session, tracking = fake(n_dots=3)
    dots, offset, s = v.score(rec, session, tracking, 0)
    assert len(dots) == 3 and offset is None
    assert any("at least 4" in w for w in s["warnings"])


def test_a_large_offset_is_flagged():
    rec, session, tracking = fake(offset=np.array([0.07, 0.0]))     # 4 deg
    _, _, s = v.score(rec, session, tracking, 0)
    assert any("wearer profile" in w for w in s["warnings"])
