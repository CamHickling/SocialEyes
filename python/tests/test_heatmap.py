import json

import numpy as np
import pandas as pd
import pytest

from conftest import EXAMPLE
from socialeyes.gaze.fixations import map_fixations
from socialeyes.gaze.heatmap import (SessionFixations, _density, aoi_dwell, group_of, pooled_maps, render,
                                     sigma_img_px)
from socialeyes.session.io import load_session
from socialeyes.session.simulate import simulate_session
from socialeyes.study.compiler import compile_study


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    root = tmp_path_factory.mktemp("hm")
    build, _ = compile_study(EXAMPLE, root / "build")
    manifest = json.loads((build / "study.json").read_text(encoding="utf-8"))
    return root, build, manifest


def plan(build, pid):
    return json.loads((build / "plans" / f"{pid}.json").read_text(encoding="utf-8"))


def test_groups(built):
    _, build, _ = built
    p = plan(build, "P001")
    crit = next(x for x in p["feed"] if x["role"] == "critical")
    filler = next(x for x in p["feed"] if x["role"] == "filler")
    assert group_of(p, crit["post_id"], "cell") == f"{crit['cell']} | {p['group_key']}"
    assert group_of(p, filler["post_id"], "cell") == f"filler | {p['group_key']}"
    assert group_of(p, crit["post_id"], "label") == f"label={crit['conditions']['label']}"
    assert group_of(p, crit["post_id"], "comments") == f"comments={p['between']['comments']}"
    assert group_of(p, "nope", "cell") is None


def test_density_sums_to_one_and_peaks_at_the_fixation():
    fx = pd.DataFrame({"img_x": [300.0], "img_y": [100.0], "duration_ms": [200.0]})
    d = _density(fx, np.array([20.0]), 600, 800)
    assert d.sum() == pytest.approx(1.0)
    y, x = np.unravel_index(d.argmax(), d.shape)
    k = d.shape[1] / 600
    assert (x + 0.5) / k == pytest.approx(300, abs=2) and (y + 0.5) / k == pytest.approx(100, abs=2)
    # 1 degree at 350 mm on a 400-dpi screen showing the image at half size
    assert sigma_img_px(400 / 25.4, 350, 0.5) == pytest.approx(np.tan(np.radians(1)) * 350 * 400 / 25.4 * 0.5)


def fixations(image_id, post_id, points, aoi=""):
    return pd.DataFrame([{"image_id": image_id, "post_id": post_id, "img_x": x, "img_y": y, "duration_ms": d,
                          "aoi": aoi, "img_per_screen_px": 0.5} for x, y, d in points])


def test_every_participant_counts_equally(built):
    _, build, manifest = built
    p = plan(build, "P001")
    crit = next(x for x in p["feed"] if x["role"] == "critical")
    img = crit["image_id"]
    w, h = manifest["images"][img]["width"], manifest["images"][img]["height"]
    long_looker = SessionFixations("A", "a", fixations(img, crit["post_id"], [(50, 50, 400)] * 20), p, 15.7, 350)
    short_looker = SessionFixations("B", "b", fixations(img, crit["post_id"], [(w - 50, h - 50, 100)]), p, 15.7, 350)
    maps = pooled_maps([long_looker, short_looker], {img: (w, h)})
    g = next(iter(maps[img].values()))
    assert g["participants"] == 2 and g["fixations"] == 21
    top, bottom = g["map"][: g["map"].shape[0] // 2].sum(), g["map"][g["map"].shape[0] // 2:].sum()
    assert top == pytest.approx(0.5, abs=0.02) and bottom == pytest.approx(0.5, abs=0.02)


def test_aoi_dwell_counts_unlooked_aois_as_zero(built):
    _, build, _ = built
    p = plan(build, "P001")
    crit = next(x for x in p["feed"] if x["role"] == "critical")
    a = fixations(crit["image_id"], crit["post_id"], [(10, 10, 300)], aoi="face")
    b = fixations(crit["image_id"], crit["post_id"], [(10, 10, 100), (20, 20, 300)], aoi="waist")
    d = aoi_dwell([SessionFixations("A", "a", a, p, 15.7, 350), SessionFixations("B", "b", b, p, 15.7, 350)])
    face = d[d["aoi"] == "face"].iloc[0]
    assert face["participants"] == 2 and face["mean_share"] == pytest.approx(0.5)


def test_render_writes_group_maps_and_a_difference(built, tmp_path):
    _, build, manifest = built
    sessions = []
    for pid in ("P001", "P002", "P003", "P004", "P005", "P006", "P007", "P008"):
        p = plan(build, pid)
        crit = next(x for x in p["feed"] if x["post_id"] == "crit01")
        y = 100 if crit["conditions"]["label"] == "none" else 400
        sessions.append(SessionFixations(pid, pid, fixations(crit["image_id"], "crit01", [(270, y, 300)]), p, 15.7, 350))
    sizes = {i: (v["width"], v["height"]) for i, v in manifest["images"].items()}
    r = render(build, pooled_maps(sessions, sizes, by="label"), tmp_path)
    assert (tmp_path / "index.html").is_file()
    with_two = [i for i in r.images if len(i["groups"]) == 2]
    assert with_two and all(any(f.endswith("__diff.png") for f in i["files"]) for i in with_two)
    for i in r.images:
        for f in i["files"]:
            assert (tmp_path / f).is_file()


def test_fixations_land_on_the_image_under_them(built, tmp_path):
    _, build, manifest = built
    session_dir = simulate_session(build, "P003", tmp_path / "s", seed=3)
    s = load_session(session_dir)
    vp = s.viewport
    p = plan(build, "P003")
    images = {e["post_id"]: e["image_id"] for e in p["feed"]}
    # a frame in which some critical post's image is fully on screen
    frames = vp[vp["element"] == "frame"]
    img_rows = vp[(vp["element"] == "image") & vp["post_id"].str.startswith("crit")]
    row = img_rows[(img_rows["top"] > s.feed_area[1]) & (img_rows["bottom"] < s.feed_area[3])].iloc[0]
    t = int(frames[frames.index < row.name]["t_ns"].iloc[-1]) + 1_000_000
    cx, cy = (row["left"] + row["right"]) / 2, (row["top"] + row["bottom"]) / 2
    offset = 10**18
    gaze = pd.DataFrame({"unix_ns": t + offset + np.arange(10) * 5_000_000, "t_ns": t + np.arange(10) * 5_000_000,
                         "step_id": "feed", "x_px": cx, "y_px": cy, "on_screen": True})
    fix = pd.DataFrame({"start_ns": [t + offset], "end_ns": [t + offset + 45_000_000]})
    f = map_fixations(fix, gaze, s, offset, build).iloc[0]
    image_id = images[row["post_id"]]
    w, h = manifest["images"][image_id]["width"], manifest["images"][image_id]["height"]
    assert f["post_id"] == row["post_id"] and f["element"] == "image" and f["image_id"] == image_id
    # the feed may scroll a little during the fixation, moving the image under the gaze
    assert f["img_x"] == pytest.approx(w / 2, abs=2) and f["img_y"] == pytest.approx(h / 2, abs=0.03 * h)
    assert f["t_start_ns"] == t and f["duration_ms"] == 45.0 and f["mapped"] == 1.0
    assert f["img_per_screen_px"] == pytest.approx(w / (row["right"] - row["left"]), rel=1e-3)


def test_export_gaze_columns(built, tmp_path):
    from socialeyes.session.export import export_study

    root, build, manifest = built
    data = tmp_path / "data"
    session = simulate_session(build, "P001", data / "P001" / "P001-sim", seed=1)
    p = plan(build, "P001")
    crit = next(x for x in p["feed"] if x["role"] == "critical")
    s = load_session(session)
    exp = s.viewport[(s.viewport["post_id"] == crit["post_id"]) & (s.viewport["element"] == "post")]
    t0 = int(s.viewport.loc[s.viewport.index < exp.index[0]].query("element == 'frame'")["t_ns"].iloc[-1])
    fx = pd.DataFrame([
        {"fixation": 0, "t_start_ns": t0 + 500_000_000, "t_end_ns": t0 + 800_000_000, "duration_ms": 300.0,
         "post_id": crit["post_id"], "image_id": crit["image_id"], "aoi": "face", "img_x": 1, "img_y": 1},
        {"fixation": 1, "t_start_ns": t0 + 900_000_000, "t_end_ns": t0 + 1_100_000_000, "duration_ms": 200.0,
         "post_id": crit["post_id"], "image_id": crit["image_id"], "aoi": "", "img_x": 2, "img_y": 2},
    ])
    res = tmp_path / "analysis" / "P001" / "P001-sim"
    res.mkdir(parents=True)
    fx.to_csv(res / "fixations.csv", index=False)
    export_study(EXAMPLE, data, tmp_path / "out", build_for=lambda _f: build, analysis_dir=tmp_path / "analysis")
    items = pd.read_csv(tmp_path / "out" / "by_item.csv", encoding="utf-8-sig").set_index("post_id")
    row = items.loc[crit["post_id"]]
    assert row["gaze_fixations"] == 2 and row["gaze_image_ms"] == 500 and row["gaze_face_ms"] == 300
    assert row["gaze_waist_ms"] == 0 and np.isnan(row["gaze_waist_first_s"])
    assert row["gaze_face_first_s"] == pytest.approx(0.5, abs=0.05)
    book = pd.read_csv(tmp_path / "out" / "codebook.csv", encoding="utf-8-sig", keep_default_na=False)
    assert (book[book["column"].str.startswith("gaze_")]["description"] != "").all()
