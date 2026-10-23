"""The phone setup guide (phone/setup.py): each step's state read from the phone, and its actions."""
import pytest

from socialeyes.phone import loader
from socialeyes.phone import setup as S
from socialeyes.phone.adb import AdbError, Device
from socialeyes.phone.loader import PhoneState


class FakeAdb:
    def __init__(self, devices, shell=None):
        self._devices = devices
        self.serial = None
        self.calls = []
        self._shell = shell or {}

    def devices(self, one_per_phone=True):
        return self._devices

    def choose(self):
        if not self._devices:
            raise AdbError("No phone found.")
        self.serial = self._devices[0].serial
        return self._devices[0]

    def shell(self, command, timeout=60, check=False):
        self.calls.append(command)
        return self._shell.get(command, "")


def by_id(g):
    return {s["id"]: s for s in g["steps"]}


def test_no_phone_starts_at_usb_debugging_and_everything_else_waits():
    g = S.guide(adb=FakeAdb([]))
    steps = by_id(g)
    assert g["next"] == "developer" and g["device"] is None
    assert all(steps[k]["status"] == "waiting" for k in ("connect", "app", "dnd", "battery"))


def test_a_phone_that_hasnt_allowed_this_computer_is_told_to_tap_allow():
    g = S.guide(adb=FakeAdb([Device("ABC", "unauthorized")]))
    assert by_id(g)["developer"]["status"] == "done"
    assert g["next"] == "connect" and "tap Allow" in by_id(g)["connect"]["detail"]


def test_a_new_phone_needs_the_app_and_settings_that_dont_need_it_are_read_anyway(monkeypatch):
    monkeypatch.setattr(loader, "read_phone", lambda adb: PhoneState(
        serial="ABC", model="Pixel 3", android="12", app_installed=False, battery=30, dnd="off", font_scale=1.15))
    g = S.guide(adb=FakeAdb([Device("ABC", "device", "Pixel_3")]))
    steps = by_id(g)
    assert g["next"] == "app" and steps["app"]["action"] == "install"
    assert steps["open"]["status"] == "waiting" and steps["ruler"]["status"] == "waiting"
    assert steps["dnd"]["status"] == "todo" and steps["display"]["status"] == "todo"
    assert steps["battery"]["status"] == "todo" and steps["battery"]["detail"] == "30%."


def test_a_ready_phone_has_nothing_left_but_the_optional_camera(monkeypatch):
    monkeypatch.setattr(loader, "read_phone", lambda adb: PhoneState(
        serial="ABC", app_installed=True, app_version_name="0.3.10", camera_granted=False, battery=90,
        dnd="priority only", font_scale=1.0, profile={"ruler_check": {"measured_x_mm": 50, "measured_y_mm": 100}}))
    g = S.guide(adb=FakeAdb([Device("ABC", "device")]))
    steps = by_id(g)
    assert g["next"] is None
    assert steps["camera"]["status"] == "optional"
    assert all(s["status"] == "done" for k, s in steps.items() if k != "camera")


def test_actions_run_on_the_phone_and_say_when_it_must_be_done_by_hand():
    adb = FakeAdb([Device("ABC", "device")], shell={"settings get global zen_mode": "1"})
    assert "Do Not Disturb" in S.do("dnd", adb=adb)
    assert "cmd notification set_dnd priority" in adb.calls
    adb = FakeAdb([Device("ABC", "device")], shell={"settings get global zen_mode": "0"})
    with pytest.raises(AdbError, match="tap Do Not Disturb"):
        S.do("dnd", adb=adb)
    adb = FakeAdb([Device("ABC", "device")])
    S.do("display", adb=adb)
    assert adb.calls == ["wm size reset", "wm density reset", "settings put system font_scale 1.0"]
    with pytest.raises(ValueError):
        S.do("uninstall", adb=adb)


def test_battery_savers_are_found_and_a_makers_own_list_is_pointed_out(monkeypatch):
    phone = dict(serial="ABC", app_installed=True, profile={}, battery=90, dnd="priority only", font_scale=1.0)
    monkeypatch.setattr(loader, "read_phone", lambda adb: PhoneState(
        **phone, power_saver=True, battery_optimized=True, manufacturer="google"))
    s = by_id(S.guide(adb=FakeAdb([Device("ABC", "device")])))["battery_saver"]
    assert s["status"] == "todo" and s["action"] == "battery_saver" and s["detail"].startswith("Battery Saver is on;")
    monkeypatch.setattr(loader, "read_phone", lambda adb: PhoneState(
        **phone, power_saver=False, battery_optimized=False, background_restricted=False, manufacturer="samsung"))
    s = by_id(S.guide(adb=FakeAdb([Device("ABC", "device")])))["battery_saver"]
    assert s["status"] == "optional" and s["action"] is None and "Sleeping apps" in s["how"][-1]


def test_exempting_the_app_runs_on_the_phone_and_says_when_it_didnt_take():
    adb = FakeAdb([Device("ABC", "device")], shell={"dumpsys deviceidle whitelist": f"user,{S.PACKAGE},10123"})
    assert "exempted" in S.do("battery_saver", adb=adb)
    assert f"cmd deviceidle whitelist +{S.PACKAGE}" in adb.calls
    with pytest.raises(AdbError, match="Unrestricted"):
        S.do("battery_saver", adb=FakeAdb([Device("ABC", "device")]))


def test_readiness_warns_about_battery_savers():
    p = PhoneState(serial="ABC", app_installed=True, power_saver=True, background_restricted=True,
                   battery_optimized=True, manufacturer="xiaomi")
    warns = [c.text for c in loader.readiness(p) if c.level == "warn"]
    assert any("Battery Saver" in t for t in warns) and any("restricted" in t for t in warns)
    assert any(t.startswith("Xiaomi phones stop apps") and "Autostart" in t for t in warns)
    assert loader.parse_background("RUN_ANY_IN_BACKGROUND: ignore; time=+1d") is True
    assert loader.parse_background("No operations.") is False
