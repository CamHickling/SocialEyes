"""Screen brightness and scene camera exposure per phone model (CAM-227): the table, the loader's
checks and what it gives the phone, and saving a settings test's best setting."""
import json
from pathlib import Path

import pandas as pd
import pytest

from socialeyes.gaze.settings_test import OBS_COLUMNS, save_best, summary
from socialeyes.phone import models
from socialeyes.phone.loader import PhoneState, StudyInfo, phone_settings, readiness, warned
from socialeyes.phone.loader import ApkInfo

EDGE = {"manufacturer": "motorola", "model": "motorola edge 40 pro"}
TAGS = {"steps": ["feed"], "layout": "bars", "family": "tag16h5", "size_mm": 10}


@pytest.fixture(autouse=True)
def own_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("SOCIALEYES_SETTINGS", str(tmp_path / "settings.json"))


def recording(brightness=None, exposure=None, auto_record=True):
    return {"display": {"brightness": brightness}, "neon": {"auto_record": auto_record, "scene_exposure": exposure}}


def test_the_edge_40_pro_ships_with_its_tested_setting():
    e = models.lookup("motorola", "motorola edge 40 pro")
    assert e["brightness"] == 0.30 and e["scene_exposure"] == {"mode": "auto", "brightness": -32}
    assert models.lookup("Motorola", " Motorola Edge 40 Pro ") == e     # as the app or adb may spell it
    assert models.lookup("Google", "Pixel 3") is None


def test_a_saved_result_wins_over_the_shipped_one():
    models.save("motorola", "motorola edge 40 pro", 0.45, {"mode": "manual", "exposure_us": 1000}, "lab test")
    assert models.lookup(**EDGE)["brightness"] == 0.45


def test_exposure_from_the_logged_camera_values():
    assert models.exposure_from_camera({"ae_mode": "auto", "brightness": "-32"}) == {"mode": "auto", "brightness": -32}
    assert models.exposure_from_camera({"ae_mode": "auto"}) == {"mode": "auto"}
    assert models.exposure_from_camera({"ae_mode": "manual", "man_exp": "1000"}) == {"mode": "manual", "exposure_us": 1000}


def test_blank_settings_are_filled_from_the_phone_model():
    out, payload = models.checks(EDGE["manufacturer"], EDGE["model"], recording(), eye_tracking=True)
    assert [lvl for lvl, _ in out] == ["info"] and "fills it" in out[0][1]
    assert payload["brightness"] == 0.30 and payload["scene_exposure"]["brightness"] == -32
    assert payload["model"] == "motorola edge 40 pro"


def test_a_study_that_differs_from_the_phone_model_is_flagged_but_keeps_its_own():
    out, payload = models.checks(EDGE["manufacturer"], EDGE["model"],
                                 recording(0.6, {"mode": "manual", "exposure_us": 2000}), eye_tracking=True)
    assert [lvl for lvl, _ in out] == ["warn"] and "differs" in out[0][1]
    assert payload is not None    # the app only fills blanks, so the study's own still apply
    out, _ = models.checks(EDGE["manufacturer"], EDGE["model"],
                           recording(0.30, {"mode": "auto", "brightness": -32}), eye_tracking=True)
    assert [lvl for lvl, _ in out] == ["ok"]


def test_an_untested_phone_model():
    out, payload = models.checks("Google", "Pixel 3", recording(), eye_tracking=True)
    assert payload is None and out[0][0] == "warn" and "Settings test" in out[0][1]
    out, _ = models.checks("Google", "Pixel 3", recording(0.3, {"mode": "auto"}), eye_tracking=True)
    assert out[0][0] == "info"


def test_studies_without_eye_tracking_are_left_alone():
    assert models.checks(EDGE["manufacturer"], EDGE["model"], recording(), eye_tracking=False) == ([], None)


def test_the_loader_reads_the_model_from_the_apps_profile():
    phone = PhoneState(serial="X", app_installed=True, app_version_code=1, app_version_name="0.1.0", battery=90,
                       free_bytes=20 * 2**30, dnd="priority only", font_scale=1.0, model="motorola_edge_40_pro",
                       profile={**EDGE, "screen_width_px": 1080, "screen_height_px": 2400, "density": 2.625,
                                "xdpi": 394.0, "ydpi": 394.0, "ruler_check": {"measured_x_mm": 50, "measured_y_mm": 100}})
    study = StudyInfo(id="s", version=1, build=Path("."), package_sha256="a" * 64, size_bytes=1, needs_camera=False,
                      tags=TAGS, recording=recording())
    assert phone_settings(phone, study)[1]["brightness"] == 0.30
    checks = readiness(phone, study, ApkInfo(Path("app.apk"), 1, "0.1.0"))
    assert any("fills it" in c.text for c in checks) and not warned(checks)


def test_saving_the_settings_tests_best(tmp_path):
    obs = pd.DataFrame([
        ["auto -50%, 0.30", 0, 0, 0.30, json.dumps({"ae_mode": "auto", "brightness": "-32"}), 40, 30, 0.95, 0.95, 0.05, 150.0, 60.0],
        ["manual 1000, 0.60", 0, 0, 0.60, json.dumps({"ae_mode": "manual", "man_exp": "1000"}), 40, 30, 0.50, 0.50, 0.05, 150.0, 60.0],
    ], columns=OBS_COLUMNS)

    class S:
        device = {"manufacturer": "Google", "model": "Pixel 3"}

    entry = save_best(summary(obs), S(), "settings test T01")
    assert entry["brightness"] == 0.30 and entry["scene_exposure"] == {"mode": "auto", "brightness": -32}
    assert models.lookup("google", "pixel 3") == entry and "auto -50%" in entry["source"]
