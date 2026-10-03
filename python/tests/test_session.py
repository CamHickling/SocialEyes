import json

import numpy as np
import pandas as pd
import pytest

from conftest import EXAMPLE, edit_file
from socialeyes.cli import main
from socialeyes.session.analyze import analyze_session
from socialeyes.session.gestures import strokes
from socialeyes.session.io import SessionFormatError, load_session, write_session
from socialeyes.session.quality import session_quality
from socialeyes.session.simulate import simulate_session
from socialeyes.session.touch import _distance_to_polygon, occlusion, touch_targets
from socialeyes.session.viewport import Layout
from socialeyes.study.aoi import AOI, AOISet
from socialeyes.study.compiler import check_study, compile_study

MS = 1_000_000


def touches(*strokes_):
    """Build a touch table from (pointer, [(t_ms, x, y), ...]) strokes."""
    rows = []
    for pointer, pts in strokes_:
        for k, (t, x, y) in enumerate(pts):
            action = "down" if k == 0 else "up" if k == len(pts) - 1 else "move"
            rows.append({"t_ns": t * MS, "action": action, "pointer_id": pointer, "x_px": x, "y_px": y,
                         "step_id": "feed"})
    return pd.DataFrame(rows).sort_values("t_ns", kind="stable").reset_index(drop=True)


def line(t0, t1, x0, y0, x1, y1, n=10):
    return [(t0 + (t1 - t0) * k / n, x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n) for k in range(n + 1)]


# ---------------------------------------------------------------- gestures


def test_gesture_classification():
    t = touches(
        (0, [(0, 100, 100), (40, 101, 100), (80, 100, 101)]),                    # tap
        (0, [(1000, 100, 100), (1400, 102, 101), (1700, 101, 100)]),             # long press
        (0, line(3000, 3200, 500, 1500, 500, 1000) + [(3400, 500, 1000)]),       # scroll (stops before lifting)
        (0, line(5000, 5150, 500, 1500, 500, 1000)),                             # fling
        (0, [(7000, 300, 300), (7080, 300, 300)]),                               # double tap ...
        (0, [(7200, 305, 302), (7280, 305, 302)]),                               # ... second tap
    )
    g = strokes(t, px_per_dp=1.0)
    assert g["gesture"].tolist() == ["tap", "long_press", "scroll", "fling", "double_tap", "double_tap"]
    assert g.loc[3, "direction"] == "up"
    assert g.loc[3, "end_speed_dp_s"] == pytest.approx(500 / 0.15, rel=0.01)


def test_pinch_needs_two_fingers_at_once():
    t = touches((0, line(0, 300, 400, 1000, 300, 900)), (1, line(100, 400, 600, 1000, 700, 1100)))
    assert set(strokes(t, 1.0)["gesture"]) == {"pinch"}
    # lift and touch down at the same instant: still single-finger gestures
    t = touches((0, [(0, 100, 100), (80, 100, 100)]), (0, [(80, 500, 500), (160, 500, 500)]))
    assert "pinch" not in set(strokes(t, 1.0)["gesture"])


# ---------------------------------------------------------------- viewport


def viewport_rows(frames):
    """frames: [(t_ms, scroll, [(post, element, l, t, r, b), ...])]"""
    rows = []
    for k, (t, scroll, els) in enumerate(frames):
        rows.append({"t_ns": t * MS, "frame": k, "scroll_y": scroll, "post_id": "", "element": "frame"})
        rows += [{"t_ns": t * MS, "frame": k, "post_id": p, "element": e, "left": l, "top": tp, "right": r,
                  "bottom": b} for p, e, l, tp, r, b in els]
    return pd.DataFrame(rows)


def card(post, dy):
    return [(post, "post", 0, 0 + dy, 1000, 1200 + dy), (post, "header", 0, 0 + dy, 1000, 100 + dy),
            (post, "image", 0, 100 + dy, 1000, 1100 + dy), (post, "label", 0, 1000 + dy, 1000, 1100 + dy)]


def test_locate_picks_most_specific_element():
    lay = Layout(viewport_rows([(0, 0, card("a", 0)), (1000, 500, card("a", -500))]))
    r = lay.locate([500 * MS, 500 * MS, 500 * MS, 1500 * MS, -5], [10, 10, 10, 10, 10], [50, 500, 1050, 550, 50])
    assert r["element"].tolist() == ["header", "image", "label", "label", ""]
    assert r["post_id"].tolist() == ["a", "a", "a", "a", ""]
    assert r.loc[2, "image_top"] == 100  # on the label, but still over the image
    assert r.loc[3, "image_top"] == -400
    assert np.isnan(r.loc[0, "image_top"])


def test_exposure():
    area = (0, 0, 1000, 2000)
    # 0-1 s fully visible; 1-3 s the image is half above the screen; feed closes at 3 s
    lay = Layout(viewport_rows([(0, 0, card("a", 0)), (1000, 600, card("a", -600)), (3000, None, [])]))
    e = lay.exposure(3000 * MS, area).set_index("element")
    assert e.loc["image", "visible_s"] == pytest.approx(3.0)
    assert e.loc["image", "full_s"] == pytest.approx(1.0)
    assert e.loc["image", "weighted_s"] == pytest.approx(1.0 + 2.0 * 0.5)
    assert e.loc["header", "visible_s"] == pytest.approx(1.0)  # scrolled off in the second frame
    assert e.loc["image", "entries"] == 1


def test_entries_count_returns_into_view():
    frames = [(0, 0, card("a", 0)), (1000, 0, []), (2000, 0, card("a", 0)), (3000, None, [])]
    e = Layout(viewport_rows(frames)).exposure(3000 * MS, (0, 0, 1000, 2000))
    assert e.set_index("element").loc["post", "entries"] == 2
    assert e.set_index("element").loc["post", "visible_s"] == pytest.approx(2.0)


def sheet(post, top, comments=2):
    els = [(post, "sheet", 0, top, 1000, 2000)]
    els += [(post, f"sheet_comment_{i}", 0, top + 200 + 150 * i, 1000, top + 350 + 150 * i) for i in range(comments)]
    return els


def test_sheet_lies_on_top_of_the_feed():
    lay = Layout(viewport_rows([(0, 0, card("a", 0) + sheet("a", 800))]))
    r = lay.locate([0, 0, 0], [10, 10, 10], [500, 900, 1100])
    assert r["element"].tolist() == ["image", "sheet", "sheet_comment_0"]


def test_sheet_hides_the_feed_below_it():
    area = (0, 0, 1000, 2000)
    # 0-1 s no sheet; 1-2 s sheet from y = 600 (half of the image hidden); 2-3 s full screen
    frames = [(0, 0, card("a", 0)), (1000, 0, card("a", 0) + sheet("a", 600)),
              (2000, 0, card("a", 0) + sheet("a", 0)), (3000, None, [])]
    e = Layout(viewport_rows(frames)).exposure(3000 * MS, area).set_index("element")
    assert e.loc["image", "visible_s"] == pytest.approx(2.0)  # hidden while the sheet is full screen
    assert e.loc["image", "weighted_s"] == pytest.approx(1.0 + 0.5)
    assert e.loc["sheet_comment_1", "visible_s"] == pytest.approx(2.0)


# ---------------------------------------------------------------- touch mapping and occlusion


def test_touch_to_image_pixels_and_aoi():
    # image shown 1000 px wide for a 500 x 500 image: 2 screen px per image px
    lay = Layout(viewport_rows([(0, 0, card("a", 0))]))
    aois = {"img": AOISet(500, 500, (AOI("face", np.array([[200, 0], [300, 0], [300, 100], [200, 100]], float)),))}
    t = touches((0, [(10, 500, 200), (500, 500, 200), (1000, 500, 200)]))
    tt = touch_targets(t, lay, {"a": "img"}, aois, {"img": (500, 500)})
    assert tt["img_x"].tolist() == [250.0] * 3
    assert tt["img_y"].tolist() == [50.0] * 3
    assert tt["aoi"].tolist() == ["face"] * 3
    occ = occlusion(tt, aois, px_per_mm=10.0, finger_radius_mm=8.0)
    assert occ.iloc[0]["aois_covered"] == "face"
    assert occ.iloc[0]["duration_ms"] == pytest.approx(990)


def test_finger_near_aoi_counts_as_covering_it():
    lay = Layout(viewport_rows([(0, 0, card("a", 0))]))
    aois = {"img": AOISet(500, 500, (AOI("face", np.array([[200, 0], [300, 0], [300, 100], [200, 100]], float)),))}
    # 30 image px below the face = 60 screen px; radius 8 mm at 10 px/mm = 80 screen px
    t = touches((0, [(0, 500, 100 + 2 * 130), (100, 500, 100 + 2 * 130)]))
    tt = touch_targets(t, lay, {"a": "img"}, aois, {"img": (500, 500)})
    assert tt["aoi"].tolist() == ["", ""]
    assert occlusion(tt, aois, 10.0, 8.0).iloc[0]["aois_covered"] == "face"
    assert occlusion(tt, aois, 10.0, 5.0).iloc[0]["aois_covered"] == ""


def test_distance_to_polygon():
    sq = np.array([[0, 0], [10, 0], [10, 10], [0, 10]], float)
    d = _distance_to_polygon(np.array([5.0, 13.0, 5.0]), np.array([5.0, 14.0, -2.0]), sq)
    assert d == pytest.approx([5.0, 5.0, 2.0])


# ---------------------------------------------------------------- reading


def minimal_meta(**extra):
    return {"format": "socialeyes-session", "format_version": 1, "study_id": "example", "participant_id": "P001",
            "clock": {"elapsed_ns": 0, "uptime_ns": 0, "wall_ms": 0},
            "device": {"screen_width_px": 1080, "screen_height_px": 2400, "density_dpi": 420},
            "logging": {"touches": False}, **extra}


def test_load_rejects_bad_files(tmp_path):
    write_session(tmp_path / "a", minimal_meta(logging={"touches": True}), [], [])
    with pytest.raises(SessionFormatError, match="touch.csv is missing"):
        load_session(tmp_path / "a")
    write_session(tmp_path / "b", minimal_meta(), [], [{"t_ns": 0, "frame": 0, "element": "picture"}])
    with pytest.raises(SessionFormatError, match="unknown element"):
        load_session(tmp_path / "b")
    write_session(tmp_path / "c", minimal_meta(format_version=99), [], [])
    with pytest.raises(SessionFormatError, match="format_version 99"):
        load_session(tmp_path / "c")
    write_session(tmp_path / "d", minimal_meta(), [], [])
    (tmp_path / "d" / "events.jsonl").write_text('{"t_ns": 1, "type": "x"}\n{broken\n')
    with pytest.raises(SessionFormatError, match="line 2"):
        load_session(tmp_path / "d")


def test_quality_flags_problems(tmp_path):
    s = 1_000_000_000
    meta = minimal_meta(clock={"elapsed_ns": 0, "uptime_ns": 0, "wall_ms": 0})  # no end: crashed
    events = [{"t_ns": 10 * s, "type": "app_state", "state": "background"},
              {"t_ns": 14 * s, "type": "app_state", "state": "foreground"},
              {"t_ns": 20 * s, "type": "interruption", "kind": "notification"},
              {"t_ns": 30 * s, "type": "neon", "status": "disconnected"}]
    write_session(tmp_path, meta, events, [])
    q = session_quality(load_session(tmp_path))
    assert q["completed"] is False
    assert q["background_s"] == pytest.approx(4.0)
    assert q["interruptions"] == {"notification": 1}
    assert q["neon_disconnects"] == 1
    assert len(q["warnings"]) == 4
    meta["end"] = {"reason": "completed", "clock": {"elapsed_ns": 100 * s, "uptime_ns": 90 * s, "wall_ms": 0}}
    write_session(tmp_path, meta, [], [])
    q = session_quality(load_session(tmp_path))
    assert q["slept_s"] == pytest.approx(10.0)
    assert any("asleep" in w for w in q["warnings"])


# ---------------------------------------------------------------- simulated end to end


@pytest.fixture(scope="module")
def simulated(tmp_path_factory):
    root = tmp_path_factory.mktemp("sim")
    build, _ = compile_study(EXAMPLE, root / "build")
    simulate_session(build, "P003", root / "session", seed=3)
    return build, root / "session"


def test_simulated_session_round_trip(simulated):
    build, session = simulated
    r = analyze_session(session, build)
    q = r["quality"]
    assert q["completed"] and q["warnings"] == []
    plan = json.loads((build / "plans" / "P003.json").read_text())
    feed = {e["post_id"]: e for e in plan["feed"]}

    # every post was scrolled past, and each exposure row knows its condition
    images = r["exposure"][r["exposure"]["element"] == "image"].set_index("post_id")
    assert set(images.index) == set(feed)
    assert (images["visible_s"] > 0).all()
    for pid, row in images.iterrows():
        assert row["image_id"] == feed[pid]["image_id"]
        assert row["cell"] == (feed[pid]["cell"] or "")

    # labels appear only on posts in the "edited" label condition
    labelled = set(r["exposure"].query("element == 'label'")["post_id"])
    assert labelled == {p for p, e in feed.items() if e["label"]}

    # touches on images land inside the image
    on_img = r["touch_targets"].dropna(subset=["img_x"])
    assert len(on_img)
    assert on_img["img_x"].between(0, 540).all() and on_img["img_y"].between(0, 675).all()

    # each double-tap like is two double_tap strokes
    likes = r["interactions"].query("type == 'like'")
    assert (r["strokes"]["gesture"] == "double_tap").sum() == 2 * len(likes)


def test_simulation_is_reproducible(simulated, tmp_path):
    build, session = simulated
    simulate_session(build, "P003", tmp_path / "again", seed=3)
    for name in ("events.jsonl", "viewport.csv", "touch.csv"):
        assert (tmp_path / "again" / name).read_bytes() == (session / name).read_bytes()


def test_session_cli(simulated, tmp_path, capsys):
    build, session = simulated
    out = tmp_path / "analysis"
    assert main(["session", str(session), "--build", str(build), "-o", str(out)]) == 0
    assert "P003: completed" in capsys.readouterr().out
    for name in ("quality.json", "strokes.csv", "exposure.csv", "touch_targets.csv", "occlusion.csv",
                 "interactions.csv"):
        assert (out / name).is_file()


def test_sensors_are_optional(simulated, tmp_path):
    build, _ = simulated
    simulate_session(build, "P001", tmp_path / "s", sensors=True)
    s = load_session(tmp_path / "s")
    assert set(s.sensors["sensor"]) == {"accel", "gyro", "rotation"}


# ---------------------------------------------------------------- front camera


def enable_camera(study_dir, check_step=True, steps="[feed, ratings]"):
    edit_file(study_dir / "study.yaml", "    enabled: false ", "    segment_s: 30\n    enabled: true ")
    edit_file(study_dir / "study.yaml", "    steps: [feed]\n", f"    steps: {steps}\n")
    if check_step:
        edit_file(study_dir / "study.yaml", "  - {id: cal1,", "  - {id: camcheck, type: camera_check}\n  - {id: cal1,")


def test_camera_steps_must_exist(example):
    enable_camera(example, steps="[feed, nope]")
    b, rep = check_study(example)
    assert b is None and any("unknown procedure step id(s) ['nope']" in e for e in rep.errors)


def test_camera_and_screen_recording_exclusive(example):
    enable_camera(example)
    edit_file(example / "study.yaml", "  screen_recording: false", "  screen_recording: true")
    b, rep = check_study(example)
    assert b is None and any("cannot both be enabled" in e for e in rep.errors)


def test_camera_check_warnings(example):
    enable_camera(example, check_step=False)
    _, rep = check_study(example)
    assert any("no camera_check step" in w for w in rep.warnings)


@pytest.fixture(scope="module")
def camera_build(tmp_path_factory):
    import shutil
    root = tmp_path_factory.mktemp("cam")
    shutil.copytree(EXAMPLE, root / "study")
    enable_camera(root / "study")
    build, rep = compile_study(root / "study", root / "build")
    assert rep.warnings == []
    return build


def test_simulated_camera_session_is_clean(camera_build, tmp_path):
    simulate_session(camera_build, "P002", tmp_path / "s")
    q = session_quality(load_session(tmp_path / "s"))
    cam = q["camera"]
    assert q["warnings"] == []
    assert all(seg["video_frames"] == seg["frames"] for seg in cam["segments"])
    assert set(cam["step_coverage"]) == {"feed", "ratings"}
    assert min(cam["step_coverage"].values()) > 0.95


def test_camera_problems_are_flagged(camera_build, tmp_path):
    simulate_session(camera_build, "P002", tmp_path / "s")
    (tmp_path / "s" / "camera" / "front_001.mp4").unlink()
    frames = pd.read_csv(tmp_path / "s" / "camera_frames.csv")
    frames[frames["segment"] != 0].to_csv(tmp_path / "s" / "camera_frames.csv", index=False)  # rows lost
    frames = pd.read_csv(tmp_path / "s" / "camera_frames.csv")
    pd.concat([frames, frames.tail(1).assign(frame=99999, t_ns=frames["t_ns"].max() + 10**9)]) \
        .to_csv(tmp_path / "s" / "camera_frames.csv", index=False)
    warnings = " | ".join(session_quality(load_session(tmp_path / "s"))["warnings"])
    assert "front_001.mp4 is missing" in warnings
    assert "video frames but camera_frames.csv lists" in warnings
    assert "covered only" in warnings


def test_thermal_warning(tmp_path):
    events = [{"t_ns": 1, "type": "thermal", "status": "none"}, {"t_ns": 2, "type": "thermal", "status": "severe"},
              {"t_ns": 3, "type": "thermal", "status": "light"}]
    write_session(tmp_path, minimal_meta(end={"reason": "completed"}), events, [])
    q = session_quality(load_session(tmp_path))
    assert q["thermal_max"] == "severe" and any("got hot" in w for w in q["warnings"])
