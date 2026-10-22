"""The AOI editor's files (desktop/aoi_editor.py) and click-to-outline (face/outline.py)."""
import json

import numpy as np
import pytest
from PIL import Image

from socialeyes.desktop import aoi_editor as E
from socialeyes.study.aoi import load_aoi_file
from socialeyes.study.compiler import check_study


def test_images_list_critical_posts_first_with_their_aoi_files(example):
    items = E.aoi_images(example)
    needed = [x for x in items if x["needed"]]
    assert needed and items[:len(needed)] == needed                     # the ones that need AOIs come first
    first = items[0]
    assert first["aoi_file"] == f"aois/{first['image'].split('/')[-1].rsplit('.', 1)[0]}.json"
    assert first["exists"] and first["names"]
    assert any(x["kind"] == "story" and not x["needed"] for x in items)


def test_save_writes_labelme_keeps_the_old_file_and_the_study_still_checks(example):
    image = E.aoi_images(example)[0]["image"]
    d = E.load(example, image)
    assert d["src"].startswith("data:image/png;base64,") and d["aois"]
    old = (example / E.load(example, image)["aoi_file"]).read_text(encoding="utf-8")
    aois = d["aois"] + [{"name": "shirt", "points": [[10, 10], [100, 10], [100, 9999], [10, 80]]}]
    r = E.save(example, image, aois)
    saved = json.loads((example / r["aoi_file"]).read_text(encoding="utf-8"))
    assert saved["shapes"][-1]["label"] == "shirt" and saved["imageWidth"] == d["width"]
    assert saved["shapes"][-1]["points"][2] == [100, d["height"]]         # kept inside the image
    assert load_aoi_file(example / r["aoi_file"]).names()[-1] == "shirt"
    kept = list((example / E.HISTORY).glob("*.json"))
    assert len(kept) == 1 and kept[0].read_text(encoding="utf-8") == old
    _, rep = check_study(example)
    assert not rep.errors


def test_save_refuses_unnamed_duplicate_or_too_small_aois(example):
    image = E.aoi_images(example)[0]["image"]
    sq = [[0, 0], [10, 0], [10, 10]]
    for bad, msg in [([{"name": " ", "points": sq}], "needs a name"),
                     ([{"name": "a", "points": sq}, {"name": "a", "points": sq}], "two AOIs are called"),
                     ([{"name": "a", "points": sq[:2]}], "at least 3 points")]:
        with pytest.raises(ValueError, match=msg):
            E.save(example, image, bad)
    assert not (example / E.HISTORY).exists()                             # nothing was touched


def test_aois_drawn_on_another_size_are_scaled(example):
    x = E.aoi_images(example)[0]
    with Image.open(example / x["image"]) as im:
        w, h = im.size
    (example / x["aoi_file"]).write_text(json.dumps(
        {"width": w * 2, "height": h * 2, "aois": [{"name": "face", "rect": [0, 0, w, h]}]}), encoding="utf-8")
    d = E.load(example, x["image"])
    assert "scaled" in d["note"] and max(p[0] for p in d["aois"][0]["points"]) == pytest.approx(w / 2)


def _picture():
    """A dark square on a light background."""
    img = np.full((300, 240, 3), 230, np.uint8)
    img[100:200, 70:170] = (40, 60, 160)
    return img


@pytest.mark.parametrize("backend", ["sam", "mediapipe"])
def test_a_click_outlines_the_thing_under_it(backend):
    from socialeyes.face.outline import Outliner

    if backend == "sam" and not Outliner.sam_ready():
        pytest.skip("MobileSAM isn't downloaded here")
    try:
        o = Outliner(prefer=backend)
    except ImportError:
        pytest.skip("mediapipe isn't installed")
    assert o.backend == backend
    o.set_image(_picture(), "square")
    found = o.outline([(120, 150, True)])
    assert found
    xs = [p[0] for p in found[0]["polygon"]]
    ys = [p[1] for p in found[0]["polygon"]]
    assert min(xs) == pytest.approx(70, abs=6) and max(xs) == pytest.approx(170, abs=6)
    assert min(ys) == pytest.approx(100, abs=6) and max(ys) == pytest.approx(200, abs=6)
    assert o.outline([(120, 150, False)]) == []                           # only "not this": nothing
    o.close()
