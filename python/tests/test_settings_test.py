"""settings_test step: schema, compiler check, and the analysis's summary and ranking."""
import json

import numpy as np
import pandas as pd
import pytest

from conftest import edit_file
from socialeyes.gaze.settings_test import OBS_COLUMNS, ranked, report, summary
from socialeyes.study.compiler import check_study
from socialeyes.study.schema import SettingsTestExposure, SettingsTestStep


def test_defaults_are_the_planned_grid():
    s = SettingsTestStep(id="settings", type="settings_test")
    assert s.brightness == [0.30, 0.45, 0.60]
    assert [(e.mode, e.exposure_us, e.auto_bias) for e in s.exposures] == \
        [("auto", None, None), ("auto", None, -0.5), ("manual", 1000, None), ("manual", 2000, None)]
    assert len(s.holds) == 2


@pytest.mark.parametrize("bad", [{"mode": "manual"}, {"mode": "auto", "exposure_us": 1000},
                                 {"mode": "manual", "exposure_us": 1000, "auto_bias": -0.5}])
def test_exposure_rules(bad):
    with pytest.raises(ValueError):
        SettingsTestExposure(**bad)


def test_compiler_accepts_the_step_and_warns_without_auto_record(example):
    y = example / "study.yaml"
    edit_file(y, "  - {id: cal1,", "  - {id: settings, type: settings_test}\n  - {id: cal1,")
    _, rep = check_study(example)
    assert rep.errors == [] and not any("settings_test" in w for w in rep.warnings)
    text = y.read_text(encoding="utf-8")
    y.write_text(text.replace("neon:\n", "neon:\n  auto_record: false\n", 1) if "neon:\n" in text
                 else text + "\nneon:\n  auto_record: false\n", encoding="utf-8")
    _, rep = check_study(example)
    assert any("settings_test step sets the Neon scene camera" in w for w in rep.warnings)


def obs_row(variant, hold, placed, blown, fps, brightness=0.3, camera=None):
    return [variant, hold, 0, brightness, json.dumps(camera or {"ae_mode": "auto"}), 40, fps, placed, placed,
            blown, 150.0, 60.0]


def test_ranking_uses_the_worst_hold_and_leaves_out_slow_video():
    obs = pd.DataFrame([
        obs_row("a: good everywhere", 0, 0.95, 0.10, 30), obs_row("a: good everywhere", 1, 0.90, 0.12, 30),
        obs_row("b: great close, poor far", 0, 1.00, 0.05, 30), obs_row("b: great close, poor far", 1, 0.40, 0.05, 30),
        obs_row("c: slow video", 0, 1.00, 0.00, 10, camera={"ae_mode": "manual", "man_exp": "1000"}),
        obs_row("c: slow video", 1, 1.00, 0.00, 10, camera={"ae_mode": "manual", "man_exp": "1000"}),
        obs_row("d: blown out", 0, 0.95, 0.80, 30, brightness=0.6), obs_row("d: blown out", 1, 0.92, 0.85, 30, brightness=0.6),
    ], columns=OBS_COLUMNS)
    summ = summary(obs)
    assert len(summ) == 8
    order, slow = ranked(summ)
    assert slow == ["c: slow video"]
    assert order[0] == "a: good everywhere" and order.index("b: great close, poor far") > order.index("d: blown out")
    text = report(summ, {0: "normally", 1: "arm's length"})
    assert "Best: a: good everywhere" in text and "slow" in text


def test_summary_weights_by_frames():
    obs = pd.DataFrame([obs_row("a", 0, 1.0, 0.0, 30), obs_row("a", 0, 0.0, np.nan, 30)], columns=OBS_COLUMNS)
    obs.loc[1, "frames"] = 120
    s = summary(obs).iloc[0]
    assert s["placed"] == pytest.approx(40 / 160) and s["blown_out"] == 0.0 and s["frames"] == 160
