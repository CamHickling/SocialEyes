"""Unblinding: the go-ahead (name + typed phrase), its log, and heatmaps blinded until then."""
import json

import numpy as np
import pandas as pd
import pytest

from conftest import EXAMPLE
from socialeyes.gaze.heatmap import SessionFixations, base_images, pooled_by_post, render_blinded
from socialeyes.session import unblinding as ub
from socialeyes.study.compiler import compile_study


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    root = tmp_path_factory.mktemp("ub")
    build, _ = compile_study(EXAMPLE, root / "build")
    manifest = json.loads((build / "study.json").read_text(encoding="utf-8"))
    return root, build, manifest


def plan(build, pid):
    return json.loads((build / "plans" / f"{pid}.json").read_text(encoding="utf-8"))


def fixations(image_id, post_id, points):
    return pd.DataFrame([{"image_id": image_id, "post_id": post_id, "img_x": x, "img_y": y, "duration_ms": d,
                          "aoi": "", "img_per_screen_px": 0.5} for x, y, d in points])


@pytest.mark.parametrize("name, typed", [("", "unblind s1"), (" A ", "unblind s1"), ("Ada", "unblind S1"),
                                         ("Ada", "unblind"), ("Ada", "")])
def test_go_ahead_needs_a_name_and_the_exact_phrase(name, typed, tmp_path):
    with pytest.raises(ValueError):
        ub.record(tmp_path, "s1", 1, ub.Unblinding(name, typed), "tables", 3)
    assert not (tmp_path / ub.LOG).exists()


def test_log_is_added_to_never_rewritten(tmp_path):
    ub.record(tmp_path, "s1", 2, ub.Unblinding("Ada Lovelace", "unblind s1"), "tables", 3)
    ub.record(tmp_path, "s1", 2, ub.Unblinding("Grace Hopper", " unblind s1 "), "heatmaps by cell", 4)
    rows = ub.history(tmp_path)
    assert [r["researcher"] for r in rows] == ["Ada Lovelace", "Grace Hopper"]
    assert rows[0]["study_version"] == "2" and rows[1]["sessions"] == "4" and rows[0]["unblinded_at"]
    assert list(rows[0]) == ub.COLUMNS
    assert ub.history(tmp_path / "none") == []


def test_unblind_without_go_ahead_refuses(tmp_path):
    with pytest.raises(ValueError, match="unblind example"):
        ub.unblind(EXAMPLE, tmp_path, "example", None, "tables")


def test_blinded_heatmaps_pool_every_version_into_one_map_per_post(built, tmp_path):
    _, build, manifest = built
    images = manifest["images"]
    base = base_images(images)
    sessions, versions = [], set()
    for pid in ("P001", "P002", "P003", "P004"):
        p = plan(build, pid)
        crit = next(x for x in p["feed"] if x["post_id"] == "crit01")
        versions.add(crit["image_id"])
        sessions.append(SessionFixations(pid, pid, fixations(crit["image_id"], "crit01", [(270, 300, 300)]), p, 15.7, 350))
    assert len(versions) == 2  # both versions seen: pooled anyway
    maps = pooled_by_post(sessions, images)
    assert list(maps) == ["crit01"]
    m = maps["crit01"]
    assert m["image_id"] == base["crit01"] and m["participants"] == 4 and m["fixations"] == 4
    assert m["map"].sum() == pytest.approx(1.0)

    r = render_blinded(build, maps, tmp_path)
    assert sorted(f.name for f in tmp_path.iterdir()) == ["BLINDED.txt", "crit01.png", "index.html"]
    page = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "class=disclaimer" in page and "not for results" in page
    # nothing names a condition, a version or an image
    for word in ("original", "retouched", "edited", "appearance", "neutral", "minus", *versions):
        assert word not in page.lower(), word
    assert r.images[0]["groups"] == {"all": {"participants": 4, "fixations": 4}}


def test_study_heatmaps_blinded_by_default_and_logged_when_unblinded(built, tmp_path):
    from socialeyes.gaze.heatmap import study_heatmaps
    from socialeyes.session.simulate import simulate_session

    _, build, _ = built
    data = tmp_path / "data"
    simulate_session(build, "P001", data / "P001" / "P001-sim", seed=1)
    with pytest.raises(ValueError):
        study_heatmaps(EXAMPLE, data_dir=data, out_dir=tmp_path / "u", unblind=True)
    assert not (data / ub.LOG).exists()
    r, _ = study_heatmaps(EXAMPLE, data_dir=data, out_dir=tmp_path / "b")
    assert r.page.endswith("index.html") and (tmp_path / "b" / "BLINDED.txt").is_file()
    assert not (tmp_path / "b" / "aoi_dwell.csv").exists()
    study_heatmaps(EXAMPLE, data_dir=data, out_dir=tmp_path / "u", unblind=True,
                   unblinding=ub.Unblinding("Ada Lovelace", "unblind example"))
    assert (tmp_path / "u" / "aoi_dwell.csv").is_file()
    assert [r["what"] for r in ub.history(data)] == ["heatmaps by cell"]
