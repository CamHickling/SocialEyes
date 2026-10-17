import json
import math

import numpy as np
import pandas as pd
import pytest

from conftest import EXAMPLE, edit_file
from socialeyes.cli import main
from socialeyes.face.analyze import (AWAY_HEAD_DEG, MODEL, _classify_looking, _eye_offset, analyze_faces, focal_px,
                                     head_angles, summarize)
from socialeyes.session.io import load_session
from socialeyes.session.simulate import simulate_session
from socialeyes.study.compiler import compile_study

pytest.importorskip("mediapipe")


def rot_y(deg):
    a = math.radians(deg)
    return np.array([[math.cos(a), 0, math.sin(a), 0], [0, 1, 0, 0], [-math.sin(a), 0, math.cos(a), 0], [0, 0, 0, 1]])


def rot_x(deg):
    a = math.radians(deg)
    return np.array([[1, 0, 0, 0], [0, math.cos(a), -math.sin(a), 0], [0, math.sin(a), math.cos(a), 0], [0, 0, 0, 1]])


def test_head_angles():
    assert head_angles(np.eye(4)) == pytest.approx((0, 0, 0), abs=1e-9)
    yaw, pitch, roll = head_angles(rot_y(30))
    assert yaw == pytest.approx(30) and pitch == pytest.approx(0, abs=1e-9)
    yaw, pitch, _ = head_angles(rot_x(-20))  # the face's forward vector tilts up
    assert pitch == pytest.approx(20) and yaw == pytest.approx(0, abs=1e-9)


def test_eye_offset():
    pts = np.zeros((478, 2))
    iris = (468, 469, 470, 471, 472)
    eye = {"outer": 33, "inner": 133, "top": 159, "bottom": 145}
    pts[33], pts[133], pts[159], pts[145] = (0, 10), (20, 10), (10, 5), (10, 15)
    pts[468] = (10, 10)
    assert _eye_offset(pts, iris, eye) == pytest.approx((0, 0))
    pts[468] = (15, 7.5)  # toward the image's right and up
    assert _eye_offset(pts, iris, eye) == pytest.approx((0.5, 0.5))


def test_focal_length_from_the_session_or_assumed():
    class S:
        meta = {"camera": {"width": 1024, "height": 768, "focal_px": 800.0}}

    assert focal_px(S, 1024) == (pytest.approx(800.0), False)
    S.meta = {"camera": {"width": 1024, "height": 768}}
    f, assumed = focal_px(S, 1024)
    assert assumed and f == pytest.approx(1024 / 2 / math.tan(math.radians(37.5)))


def frames(n=100, **cols):
    d = {"segment": 0, "frame": np.arange(n), "t_ns": np.arange(n) * 33_000_000, "step_id": "feed", "faces": 1,
         "face": 1, "yaw_deg": 0.0, "pitch_deg": -10.0, "roll_deg": 0.0, "distance_mm": 300.0, "eye_x": 0.0,
         "eye_y": 0.0, "looking": np.nan}
    d.update(cols)
    return pd.DataFrame(d)


def test_looking_away_against_the_sessions_own_pose():
    f = frames()
    f.loc[80:89, "yaw_deg"] = AWAY_HEAD_DEG + 15  # turned away
    f.loc[90:94, "eye_x"] = 0.8                    # eyes away, head still
    f.loc[95:, "face"] = 0
    steps = pd.DataFrame({"step_id": ["feed"], "step_type": ["feed"], "start_ns": [0], "end_ns": [10**12]})
    _classify_looking(f, steps)
    assert (f.loc[:79, "looking"] == 1).all()
    assert (f.loc[80:94, "looking"] == 0).all()
    assert f.loc[95:, "looking"].isna().all()


def test_summary_warnings():
    f = frames(faces=1)
    f["looking"] = 1
    f.loc[:39, "face"] = 0
    f.loc[50:59, "faces"] = 2

    class S:
        participant_id, meta = "P1", {"session_uid": "u"}

    s = summarize(f, S, focal_assumed=True)
    st = s["steps"]["feed"]
    assert st["face_share"] == 0.6 and st["multi_face_share"] == 0.1 and st["distance_mm_median"] == 300.0
    text = " ".join(s["warnings"])
    assert "face visible in only 60%" in text and "more than one face in 10%" in text and "field of view" in text


@pytest.fixture(scope="module")
def camera_session(tmp_path_factory):
    root = tmp_path_factory.mktemp("face")
    study = root / "study"
    import shutil
    shutil.copytree(EXAMPLE, study)
    edit_file(study / "study.yaml", "    enabled: false             # step before", "    enabled: true              # step before")
    build, _ = compile_study(study, root / "build")
    session = simulate_session(build, "P001", root / "data" / "P001" / "P001-sim")
    return study, build, session, root


def test_simulated_video_has_no_face(camera_session):
    _, _, session, _ = camera_session
    assert MODEL.is_file()
    r = analyze_faces(session)
    s = load_session(session)
    assert len(r.frames) == len(s.camera_frames)
    assert (r.frames["face"] == 0).all() and r.frames["looking"].isna().all()
    assert set(r.frames["step_id"]) <= set(s.step_windows()["step_id"]) | {""}
    assert any("face visible in only 0%" in w for w in r.summary["warnings"])


def test_cli_face_with_blur(camera_session, tmp_path, capsys):
    import cv2

    _, _, session, _ = camera_session
    assert main(["face", str(session), "-o", str(tmp_path / "out"), "--blur"]) == 0
    out = capsys.readouterr().out
    assert "face in 0%" in out
    assert {p.name for p in (tmp_path / "out").iterdir()} >= {"face.csv", "face_expressions.csv", "face_summary.json",
                                                              "camera_blurred"}
    s = load_session(session)
    for seg, g in s.camera_frames.groupby("segment"):
        cap = cv2.VideoCapture(str(tmp_path / "out" / "camera_blurred" / f"front_{int(seg):03d}.mp4"))
        assert int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) == len(g)
        cap.release()


def test_export_face_columns(camera_session, tmp_path):
    from socialeyes.session.export import export_study

    study, build, session, root = camera_session
    r = export_study(study, root / "data", tmp_path / "out", build_for=lambda _f: build,
                     analysis_dir=tmp_path / "analysis")
    assert r.sessions == 1
    assert (tmp_path / "analysis" / "P001" / "P001-sim" / "face_summary.json").is_file()
    row = pd.read_csv(tmp_path / "out" / "by_session.csv", encoding="utf-8-sig").iloc[0]
    assert row["face_present"] == 0 and "face visible in only 0%" in row["face_warnings"]
    summary = json.loads((tmp_path / "analysis" / "P001" / "P001-sim" / "face_summary.json").read_text())
    assert summary["participant_id"] == "P001"
    # without the analysis and without running it, the columns are there but blank
    r = export_study(study, root / "data", tmp_path / "out2", build_for=lambda _f: build,
                     analysis_dir=tmp_path / "none", faces=False)
    row = pd.read_csv(tmp_path / "out2" / "by_session.csv", encoding="utf-8-sig").iloc[0]
    assert "face_present" in row.index and row.isna()["face_present"]


def test_short_looks_away_count_as_looking():
    from socialeyes.face.analyze import _drop_short

    t = np.arange(20) * 33_000_000  # 30 fps
    away = np.zeros(20, bool)
    away[2:4] = True    # 2 frames: a glance or a blink
    away[8:18] = True   # 10 frames (0.3 s): looking away
    out = _drop_short(away, t, 0.25)
    assert not out[2:4].any() and out[8:18].all() and not out[:8].any()


def test_blur_leaves_no_detail_in_the_face_box():
    from socialeyes.face.blur import _cover

    rng = np.random.default_rng(0)
    img = rng.integers(0, 255, (400, 300, 3), dtype=np.uint8)
    _cover(img, (50, 60, 250, 340))
    box = img[60:340, 50:250].astype(float)
    # neighbouring pixels differ by at most a few levels: a smooth smear, nothing to recognise
    assert np.abs(np.diff(box, axis=0)).max() <= 3 and np.abs(np.diff(box, axis=1)).max() <= 3
    assert np.abs(np.diff(img[:50].astype(float), axis=1)).mean() > 50  # outside the box: untouched


def test_study_faces_and_the_app_calls(camera_session, tmp_path, monkeypatch):
    from socialeyes import settings
    from socialeyes.desktop.app import Api

    study, build, session, root = camera_session
    monkeypatch.setenv("SOCIALEYES_SETTINGS", str(tmp_path / "settings.json"))
    monkeypatch.setattr(settings, "workspace", lambda: tmp_path / "ws")
    settings.set_study("example", data_dir=str(root / "data"))
    api = Api()
    st = api.data_status(str(study))["ok"]
    assert st["faces"] == {"videos": 1, "analysed": 0} and st["gaze"]["sessions"] == 0
    r = api.data_faces(str(study), True)["ok"]
    assert r == {"videos": 1, "analysed": 1, "blurred": 1, "skipped": []}
    res = tmp_path / "ws" / "analysis_out" / "example" / "P001" / "P001-sim"
    assert (res / "face_summary.json").is_file() and (res / "camera_blurred").is_dir()
    assert api.data_status(str(study))["ok"]["faces"]["analysed"] == 1
    assert api.data_faces(str(study), True)["ok"]["analysed"] == 0  # nothing left to do
    h = api.data_heatmaps(str(study), "label")["ok"]
    assert h["images"] == 0 and len(h["skipped"]) == 1 and h["page"].endswith("index.html")
    a = api.aois_draw(str(study), False)["ok"]
    assert a["written"] == [] and len(a["empty"]) == 16 and a["review"].endswith("index.html")
