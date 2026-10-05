"""The phone loader without a phone: parsing adb output, readiness rules, verifying pushes."""
from pathlib import Path

import pytest

from socialeyes.phone.adb import Adb, AdbError, Device
from socialeyes.phone.loader import (ApkInfo, PhoneState, StudyInfo, _gradle_version, blocked, build_study,
                                     discard, expected_hashes, parse_battery, parse_df, parse_package,
                                     parse_sessions, parse_sha256sum, parse_study_hashes, readiness, warned)

# captured from a Pixel 3 (Android 12)
DUMPSYS_PACKAGE = """\
    versionCode=1 minSdk=29 targetSdk=35
    versionName=0.1.0
    runtime permissions:
        android.permission.CAMERA: granted=true, flags=[ USER_SET|USER_SENSITIVE_WHEN_GRANTED ]
"""
DUMPSYS_BATTERY = """Current Battery Service state:
  AC powered: true
  USB powered: false
  Wireless powered: false
  status: 2
  level: 98
"""
DF = """Filesystem       1K-blocks     Used Available Use% Mounted on
/dev/fuse         53082240 20123456  32958784  38% /storage/emulated
"""


def test_parse_phone_output():
    assert parse_package(DUMPSYS_PACKAGE) == (True, 1, "0.1.0", True)
    assert parse_package("Unable to find package: org.socialeyes.pictogram") == (False, None, None, None)
    assert parse_package(DUMPSYS_PACKAGE.replace("granted=true", "granted=false"))[3] is False
    assert parse_battery(DUMPSYS_BATTERY) == (98, True)
    assert parse_battery(DUMPSYS_BATTERY.replace("AC powered: true", "AC powered: false")) == (98, False)
    assert parse_df(DF) == 32958784 * 1024
    assert parse_df("df: /sdcard: No such file") is None
    h = "a" * 64
    assert parse_study_hashes(f"{h}  example/files.sha256\n", "example\nold_study\n") == {"example": h, "old_study": None}
    assert parse_sessions("/sdcard/x/files/data/example/P001/P001-20261004T201253\n"
                          "/sdcard/x/files/data/example/P002/P002-20261004T210000\n"
                          "/sdcard/x/files/data/pilot/P001/P001-20261003T100000\n") == {"example": 2, "pilot": 1}
    assert parse_sessions("") == {}
    assert parse_sha256sum(f"{h}  ./plans/P001.json\n{'b' * 64}  ./files.sha256\n") == {
        "plans/P001.json": h, "files.sha256": "b" * 64}
    assert _gradle_version('versionCode = 3\n        versionName = "0.2.0"') == (3, "0.2.0")


def phone(**kw) -> PhoneState:
    base = dict(serial="X", app_installed=True, app_version_code=1, app_version_name="0.1.0", camera_granted=True,
                battery=90, free_bytes=20 * 2**30, dnd="priority only", font_scale=1.0)
    return PhoneState(**{**base, **kw})


def study(**kw) -> StudyInfo:
    base = dict(id="example", version=1, build=Path("."), package_sha256="a" * 64, size_bytes=2**20,
                needs_camera=False)
    return StudyInfo(**{**base, **kw})


APK = ApkInfo(Path("app.apk"), 1, "0.1.0")


def levels(checks):
    return [c.level for c in checks]


def test_ready_phone():
    checks = readiness(phone(), study(), APK)
    assert not blocked(checks) and not warned(checks)
    assert any("Loads study example" in c.text for c in checks)


def test_blockers():
    assert blocked(readiness(phone(app_installed=False, app_version_code=None), study(), None))
    assert blocked(readiness(phone(), study(), APK, study_errors=["posts.csv: row 3: unknown account"]))
    assert blocked(readiness(phone(free_bytes=100 * 2**20), study(), APK))
    # camera studies need room for video
    assert not blocked(readiness(phone(free_bytes=1 * 2**30), study(), APK))
    assert blocked(readiness(phone(free_bytes=1 * 2**30), study(needs_camera=True), APK))
    # a changed study can't replace one whose sessions are still on the phone ...
    changed = phone(studies={"example": "b" * 64}, sessions={"example": 2})
    c = readiness(changed, study(), APK)
    assert blocked(c) and any("2 session(s)" in x.text for x in c)
    # ... but loading the identical version again is fine
    assert not blocked(readiness(phone(studies={"example": "a" * 64}, sessions={"example": 2}), study(), APK))
    # and other studies' sessions don't matter
    assert not blocked(readiness(phone(studies={"example": "b" * 64}, sessions={"pilot": 3}), study(), APK))


def test_missing_app_is_installed_not_blocking():
    c = readiness(phone(app_installed=False, app_version_code=None, camera_granted=None), study(), APK)
    assert not blocked(c) and any("installs it" in x.text for x in c)


def test_warnings():
    for kw, text in [({"battery": 30}, "Battery at 30%"), ({"dnd": "off"}, "Do Not Disturb is off"),
                     ({"display_changed": True}, "display size"), ({"font_scale": 1.15}, "font size is 1.15x")]:
        c = readiness(phone(**kw), study(), APK)
        assert warned(c) and not blocked(c), kw
        assert any(text in x.text for x in c if x.level == "warn"), kw


def test_update_offered_only_when_newer():
    newer = ApkInfo(Path("app.apk"), 2, "0.2.0")
    assert any("0.2.0 is available" in c.text for c in readiness(phone(), study(), newer))
    assert not any("available" in c.text for c in readiness(phone(app_version_code=2), study(), newer))


def test_build_study_and_expected_hashes(example):
    s = build_study(example)
    try:
        assert s.id == "example" and len(s.package_sha256) == 64 and s.size_bytes > 0
        assert not s.needs_camera
        hashes = expected_hashes(s.build)
        assert hashes["files.sha256"] == s.package_sha256
        assert "study.json" in hashes and "plans/P001.json" in hashes
    finally:
        discard(s)
    assert not s.build.exists()


def test_devices_and_choose(monkeypatch):
    out = {"value": "List of devices attached\n8CQX1SA3K device product:blueline model:Pixel_3 device:blueline\n"}
    monkeypatch.setattr(Adb, "run", lambda self, *a, **k: out["value"])
    adb = Adb(exe=Path("adb"))
    assert adb.devices() == [Device("8CQX1SA3K", "device", "Pixel 3")]
    assert adb.choose().serial == "8CQX1SA3K"
    out["value"] = "List of devices attached\n8CQX1SA3K unauthorized\n"
    with pytest.raises(AdbError, match="Allow"):
        Adb(exe=Path("adb")).choose()
    out["value"] = "List of devices attached\n\n"
    with pytest.raises(AdbError, match="No phone"):
        Adb(exe=Path("adb")).choose()
    out["value"] = "List of devices attached\nA device\nB device\n"
    with pytest.raises(AdbError, match="More than one"):
        Adb(exe=Path("adb")).choose()
    assert Adb(serial="B", exe=Path("adb")).choose().serial == "B"
