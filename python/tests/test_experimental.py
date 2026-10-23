"""Experimental features: the desktop app's badges and the Python list name the same features."""
import re
from pathlib import Path

from socialeyes import experimental

UI = Path(__file__).resolve().parents[2] / "builder" / "src" / "ui.js"


def test_the_app_marks_the_same_features_with_the_same_reasons():
    js = UI.read_text(encoding="utf-8")
    block = js[js.index("const EXPERIMENTAL = {"):]
    block = block[:block.index("};")]
    found = dict(re.findall(r'^\s*(\w+): "(.*)",$', block, re.M))
    assert found == {k: why for k, (_, why) in experimental.FEATURES.items()}


def test_export_columns_are_traced_to_their_feature():
    assert experimental.column_feature("face_smile") == "face_analysis"
    assert experimental.column_feature("looking_at_phone") == "face_analysis"
    assert experimental.column_feature("gaze_waist_ms") == "gaze"
    assert experimental.column_feature("liked") is None
    assert experimental.note("gaze").startswith("Fixations and heatmaps is experimental.")
