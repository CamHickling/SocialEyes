import shutil

import numpy as np
import pytest

from conftest import EXAMPLE
from socialeyes.cli import main
from socialeyes.study.aoi import load_aoi_file, points_in_polygon

pytest.importorskip("mediapipe")
from socialeyes.face.body_aois import ImageAOIs, _solid, mask_polygon  # noqa: E402


def test_parts_become_one_polygon_with_seams():
    m = np.zeros((100, 200), bool)
    m[20:80, 10:60] = True     # a left leg
    m[20:80, 120:170] = True   # a right leg
    poly = mask_polygon(m)
    x = np.array([35.0, 145.0, 90.0, 35.0])
    y = np.array([50.0, 50.0, 50.0, 95.0])
    assert points_in_polygon(x, y, poly).tolist() == [True, True, False, False]  # the gap stays outside


def test_solid_fills_holes():
    m = np.zeros((60, 60), bool)
    m[10:50, 10:50] = True
    m[25:35, 25:35] = False
    assert _solid(m)[30, 30] and not _solid(m)[5, 5]


def test_labelme_output_reads_back(tmp_path):
    a = ImageAOIs("images/x.png", 100, 80, {"face": np.array([[10, 10], [30, 10], [30, 30]], float),
                                            "body": np.array([[0, 0], [99, 0], [99, 79], [0, 79]], float)})
    import json
    (tmp_path / "x.json").write_text(json.dumps(a.labelme("../images/x.png")), encoding="utf-8")
    s = load_aoi_file(tmp_path / "x.json")
    assert (s.width, s.height) == (100, 80) and s.names() == ["face", "body"]
    assert s.label_points(np.array([20.0, 50.0]), np.array([15.0, 50.0])).tolist() == ["face", "body"]


def test_cli_never_replaces_aois_it_cant_draw(tmp_path, capsys):
    study = tmp_path / "study"
    shutil.copytree(EXAMPLE, study)
    before = {p.name: p.read_bytes() for p in (study / "aois").iterdir()}
    # the example's images are cartoons: no person to find, so nothing may change, even with --overwrite
    assert main(["aois", str(study), "--overwrite"]) == 0
    out = capsys.readouterr().out
    assert "no person found" in out and "Review them:" in out
    assert {p.name: p.read_bytes() for p in (study / "aois").iterdir()} == before
