"""The experiment builder (builder/src/core.js), run in Node: what it writes must
pass the same schema and checks as a hand-written study."""
import base64
import io
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest
import yaml
from PIL import Image
from pydantic import ValidationError

from conftest import EXAMPLE
from socialeyes.study.compiler import check_study
from socialeyes.study.schema import Study

CORE = Path(__file__).resolve().parents[2] / "builder" / "src" / "core.js"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is needed to run the builder's code")


def core(js: str, data=None):
    """Run `js` (an expression using Core and `data`) in Node and return its JSON result."""
    script = (f"const Core = require({json.dumps(str(CORE))});\n"
              "const data = JSON.parse(require('fs').readFileSync(0, 'utf8'));\n"
              f"process.stdout.write(JSON.stringify(({js})));\n")
    out = subprocess.run([NODE, "-e", script], input=json.dumps(data), capture_output=True, text=True,
                         encoding="utf-8", check=True)
    return json.loads(out.stdout)


def template_files(name: str) -> dict:
    return core(f"(() => {{ const t = Core.newStudy({json.dumps(name)}); Core.syncFoils(t.study, t.content);"
                " return Core.studyFiles(t.study, t.content, true); })()")


def add_placeholder_media(folder: Path) -> None:
    """The images, avatars, videos and AOIs a researcher would add."""
    import csv
    import cv2
    import numpy as np

    def rows(name):
        p = folder / name
        return list(csv.DictReader(p.open(encoding="utf-8"))) if p.exists() else []

    critical = {r["post_id"] for r in rows("posts.csv") if r["role"] == "critical"}
    for r in rows("images.csv"):
        path = folder / r["file"]
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (540, 675), (200, 180, 220)).save(path)
        if r["post_id"] in critical:
            aoi = folder / "aois" / (Path(r["file"]).stem + ".json")
            aoi.parent.mkdir(exist_ok=True)
            aoi.write_text(json.dumps({"width": 540, "height": 675, "aois": [{"name": "body", "rect": [100, 100, 400, 600]}]}))
    for r in rows("accounts.csv") + rows("stories.csv"):
        path = folder / (r.get("avatar") or r["file"])
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (270, 480), (120, 100, 160)).save(path)
    for r in rows("reels.csv"):
        path = folder / r["file"]
        path.parent.mkdir(parents=True, exist_ok=True)
        out = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 30, (180, 320))
        for _ in range(10):
            out.write(np.full((320, 180, 3), 128, np.uint8))
        out.release()


@pytest.mark.parametrize("name", ["blank", "example"])
def test_templates_build_a_valid_study(name, tmp_path):
    files = template_files(name)
    assert {"study.yaml", "accounts.csv", "posts.csv", "images.csv", "NEXT_STEPS.txt"} <= set(files)
    folder = tmp_path / name
    folder.mkdir()
    for f, text in files.items():
        (folder / f).write_text(text, encoding="utf-8")
    add_placeholder_media(folder)
    built, rep = check_study(folder)
    assert rep.errors == []
    assert rep.warnings == []
    assert built is not None


def test_example_template_is_the_example_study():
    template = core("Core.TEMPLATES.example.study")
    assert template == yaml.safe_load((EXAMPLE / "study.yaml").read_text(encoding="utf-8"))


def test_yaml_round_trip_keeps_every_value():
    study = yaml.safe_load((EXAMPLE / "study.yaml").read_text(encoding="utf-8"))
    # strings YAML would otherwise read as something else, and other awkward text
    study["title"] = "yes: a #hashtag study, “quoted” 'too'"
    study["platform"]["participant_handle"] = "no"
    study["procedure"][0]["text"] = "Line one\nline two: ends with space "
    study["labels"]["edited"]["text"] = "1.5"
    study["factors"][1]["levels"] = ["none", "on"]
    study["factors"][1]["sets"]["label"] = {"none": None, "on": "edited"}
    study["feed"]["done_button_after_s"] = None
    study["procedure"][4]["items"][0]["min_label"] = "[low]"
    text = core("Core.toYaml(data)", study)
    assert yaml.safe_load(text) == study
    Study.model_validate(yaml.safe_load(text))


@pytest.mark.parametrize("change, fragment", [
    (lambda s: s["factors"].__setitem__(0, {**s["factors"][0], "name": "my factor"}), "simple identifier"),
    (lambda s: s["procedure"].insert(0, {"id": "feed2", "type": "feed"}), "only one feed step"),
    (lambda s: s["procedure"].append({"id": "extra", "type": "instructions", "text": "x"}), "last step must be the end"),
    (lambda s: s["procedure"][1].__setitem__("id", "welcome"), "same id"),
    (lambda s: s["logging"].update(screen_recording=True,
                                   front_camera={"enabled": True, "steps": ["feed"]}), "can't both be on"),
    (lambda s: s["factors"][2]["sets"].__setitem__("image_version", "{level}"), "controlled by both"),
])
def test_builder_errors_are_schema_errors(change, fragment):
    study = yaml.safe_load((EXAMPLE / "study.yaml").read_text(encoding="utf-8"))
    change(study)
    found = core("Core.checks(data, null).filter(c => c.level === 'error').map(c => c.msg)", study)
    assert any(fragment in m for m in found), found
    with pytest.raises(ValidationError):
        Study.model_validate(study)


def test_balance_warnings():
    study = yaml.safe_load((EXAMPLE / "study.yaml").read_text(encoding="utf-8"))
    study["participants"]["n_plans"] = 10
    content = {"critical": 6, "fillers": 12, "accounts": 6, "comments": True, "stories": 0, "reels": 0, "foils": 2}
    msgs = core("Core.checks(data.s, data.c).filter(c => c.level === 'warning').map(c => c.msg)",
                {"s": study, "c": content})
    assert any("over 4 within-subject cells" in m for m in msgs)
    assert any("balanced block of 8" in m and "8 or 16" in m for m in msgs)


def test_zip_opens_with_the_right_files():
    files = {"study.yaml": "id: x\n", "posts.csv": "post_id,role\nä,critical\n"}
    data = core("Buffer.from(Core.zip(data, 'x')).toString('base64')", files)
    with zipfile.ZipFile(io.BytesIO(base64.b64decode(data))) as z:
        assert z.testzip() is None
        assert {n: z.read(n).decode("utf-8") for n in z.namelist()} == {f"x/{k}": v for k, v in files.items()}


def test_index_html_is_up_to_date():
    import importlib.util
    spec = importlib.util.spec_from_file_location("build", CORE.parents[1] / "build.py")
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    built = build._read(CORE.parents[1] / "index.html")
    assert build.render() == built, "builder/index.html is out of date: run python builder/build.py"


def test_blank_study_has_only_the_baseline_feed():
    t = core("Core.newStudy('blank')")
    s, c = t["study"], t["content"]
    assert s["feed"]["allow_likes"] is True
    assert not any(s["feed"][k] for k in ("allow_saves", "allow_shares", "allow_comment_likes", "allow_comment_typing"))
    assert not s["logging"]["sensors"] and not s["logging"]["screen_recording"]
    assert not s["logging"]["front_camera"]["enabled"] and not s["neon"]["required"]
    assert c["stories"] == 0 and c["reels"] == 0
    assert {st["type"] for st in s["procedure"]} == {"instructions", "marker_calibration", "validation", "feed", "end"}
