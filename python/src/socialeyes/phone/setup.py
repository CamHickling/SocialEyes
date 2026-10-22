"""Phone setup guide (CAM-174): what a phone still needs before its first session, read from the
phone itself, one step at a time, with the next step's instructions.

``guide`` lists the steps with a status each (done, todo, optional, waiting: an earlier step comes
first); the first one to do is the "next" step. Steps the computer can do over adb carry an
``action`` that ``do`` runs (install the app, open it once, allow the camera, Do Not Disturb on,
display size back to default); the rest say what to tap on the phone. Nothing here deletes data:
the app is installed with ``install -r``, never uninstalled.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional

from .adb import PACKAGE, Adb, AdbError

ACTIONS = ("install", "open_app", "camera", "dnd", "display")


@dataclass
class Step:
    id: str
    title: str
    status: str = "waiting"          # done, todo, optional, waiting
    detail: str = ""                 # what was found
    how: list = field(default_factory=list)   # what to do, in order
    action: Optional[str] = None     # one of ACTIONS: the computer can do it
    action_label: str = ""


def _steps() -> list[Step]:
    return [
        Step("developer", "Turn on USB debugging", how=[
            "On the phone, open Settings > About phone and tap Build number 7 times (Samsung: About phone > "
            "Software information > Build number). Enter the phone's PIN if asked: \"You are now a developer\".",
            "Open Settings > System > Developer options (Samsung: Settings > Developer options) and turn on "
            "USB debugging.",
        ]),
        Step("connect", "Connect the phone to this computer", how=[
            "Plug the phone in with a USB cable that carries data (some cables only charge).",
            "Unlock the phone. When it asks \"Allow USB debugging?\", tick \"Always allow from this computer\" "
            "and tap Allow.",
            "Or, without a cable: Developer options > Wireless debugging (same Wi-Fi as this computer).",
        ]),
        Step("app", "Install the SocialEyes app", action="install", action_label="Install the app", how=[
            "Click Install the app. It goes on over the cable; nothing on the phone is removed.",
        ]),
        Step("open", "Open SocialEyes once", action="open_app", action_label="Open it on the phone", how=[
            "Click Open it on the phone (or tap the Pictogram icon). The app then describes the phone's screen "
            "(size, rounded corners, cut-outs) for the layout checks.",
        ]),
        Step("camera", "Allow the camera", action="camera", action_label="Allow the camera", how=[
            "Needed only for studies that record the participant's face. Click Allow the camera, or tap Allow "
            "when the app asks.",
        ]),
        Step("ruler", "Check the screen size with a ruler", how=[
            "Needed for eye tracking, once per phone. In SocialEyes on the phone, tap Check screen size and "
            "follow it: hold a ruler against the two lines and enter what it reads.",
        ]),
        Step("dnd", "Turn on Do Not Disturb", action="dnd", action_label="Turn it on", how=[
            "So notifications can't interrupt a session. Click Turn it on, or swipe down from the top of the "
            "phone's screen and tap Do Not Disturb.",
        ]),
        Step("display", "Keep the default display and font size", action="display", action_label="Reset them", how=[
            "Changed sizes make the feed look different from other phones. Click Reset them, or set "
            "Settings > Display > Display size and Font size back to the default.",
        ]),
        Step("battery", "Charge the battery", how=[
            "Charge the phone to at least 50% before a session; a session with the front camera uses more.",
        ]),
    ]


def guide(serial: Optional[str] = None, adb: Optional[Adb] = None) -> dict:
    """{device: {serial, model, state} or None, steps: [Step], next: id of the first step to do or None}."""
    from .loader import MIN_BATTERY, read_phone

    steps = {s.id: s for s in _steps()}
    out = {"device": None, "steps": list(steps.values()), "next": None, "error": None}
    adb = adb or Adb(serial)
    try:
        devices = adb.devices(one_per_phone=not serial)
    except AdbError as e:
        out["error"] = str(e)
        _settle(out)
        return out
    if serial:
        devices = [d for d in devices if d.serial == serial]
    if len(devices) > 1:
        out["error"] = "More than one phone is connected; choose one."
        _settle(out)
        return out
    if not devices:
        steps["developer"].status = "todo"
        steps["developer"].detail = "No phone found."
        _settle(out)
        return out
    d = devices[0]
    out["device"] = {"serial": d.serial, "model": d.model, "state": d.state}
    steps["developer"].status = "done"
    if d.state == "unauthorized":
        steps["connect"].status = "todo"
        steps["connect"].detail = "The phone is connected but hasn't allowed this computer: unlock it and tap Allow."
        _settle(out)
        return out
    if d.state != "device":
        steps["connect"].status = "todo"
        steps["connect"].detail = f"The phone is {d.state}: unplug it and plug it in again."
        _settle(out)
        return out
    steps["connect"].status = "done"
    steps["connect"].detail = "Connected" + (" over Wi-Fi." if d.wireless else " by USB.")
    adb.serial = d.serial
    try:
        p = read_phone(adb)
    except AdbError as e:
        out["error"] = str(e)
        _settle(out)
        return out
    out["device"].update(model=p.model or d.model, android=p.android)

    s = steps["app"]
    s.status = "done" if p.app_installed else "todo"
    s.detail = f"Version {p.app_version_name} is installed." if p.app_installed else "Not installed yet."
    if p.app_installed:
        s = steps["open"]
        s.status = "done" if p.profile is not None else "todo"
        s.detail = "The app has described the screen." if p.profile is not None else "Not opened yet."
        s = steps["camera"]
        s.status = "done" if p.camera_granted else "optional"
        s.detail = "Allowed." if p.camera_granted else "Not allowed yet."
        if p.profile is not None:
            s = steps["ruler"]
            rc = p.profile.get("ruler_check")
            s.status = "done" if rc else "todo"
            s.detail = (f"Checked: {rc.get('measured_x_mm', 0):g} mm for 50, {rc.get('measured_y_mm', 0):g} mm for 100."
                        if rc else "Not checked yet.")
    s = steps["dnd"]
    s.status = "todo" if p.dnd == "off" else "done" if p.dnd else "optional"
    s.detail = "Off." if p.dnd == "off" else f"On ({p.dnd})." if p.dnd else "Couldn't tell."
    s = steps["display"]
    changed = p.display_changed or (p.font_scale is not None and abs(p.font_scale - 1.0) > 1e-6)
    s.status = "todo" if changed else "done"
    s.detail = "Changed from the default." if changed else "Default."
    s = steps["battery"]
    if p.battery is not None:
        s.status = "done" if p.battery >= MIN_BATTERY else "todo"
        s.detail = f"{p.battery}%{' (charging)' if p.charging else ''}."
    _settle(out)
    return out


AFTER = {"open": "app", "camera": "app", "ruler": "open"}   # a step that needs another done first


def _settle(out: dict) -> None:
    """The first step still to do is next; steps after an unfinished connection, or before the
    step they need, wait."""
    steps = out["steps"]
    status = {s.id: s.status for s in steps}
    unconnected = False
    for s in steps:
        if s.status != "done" and (unconnected or (s.id in AFTER and status[AFTER[s.id]] != "done")):
            s.status = "waiting"
        if s.id in ("developer", "connect") and s.status != "done":
            unconnected = True
    out["next"] = next((s.id for s in steps if s.status == "todo"), None)
    out["steps"] = [asdict(s) for s in steps]


def do(action: str, serial: Optional[str] = None, adb: Optional[Adb] = None) -> str:
    """Runs one of the guide's actions on the phone; returns what happened."""
    from .loader import _install, find_apk

    if action not in ACTIONS:
        raise ValueError(f"unknown setup action {action!r}")
    adb = adb or Adb(serial)
    adb.choose()
    if action == "install":
        apk = find_apk()
        if apk is None:
            raise AdbError("There's no app file on this computer to install. Build it first (android: gradlew assembleDebug).")
        _install(adb, apk)    # install -r: an app already there keeps its data
        return f"Installed SocialEyes {apk.version_name}."
    if action == "open_app":
        out = adb.shell(f"monkey -p {PACKAGE} -c android.intent.category.LAUNCHER 1")
        if "No activities found" in out or "Error" in out:
            raise AdbError("Couldn't open SocialEyes on the phone; tap its icon instead.")
        return "Opened SocialEyes on the phone."
    if action == "camera":
        out = adb.shell(f"pm grant {PACKAGE} android.permission.CAMERA")
        if out.strip():
            raise AdbError(f"Couldn't allow the camera ({out.strip().splitlines()[-1]}); allow it on the phone instead.")
        return "Allowed the camera."
    if action == "dnd":
        out = adb.shell("cmd notification set_dnd priority")
        if adb.shell("settings get global zen_mode").strip() in ("", "0", "null"):
            raise AdbError("This phone doesn't let the computer turn on Do Not Disturb"
                           + (f" ({out.strip().splitlines()[-1]})" if out.strip() else "")
                           + "; swipe down from the top of its screen and tap Do Not Disturb.")
        return "Turned on Do Not Disturb (priority only)."
    adb.shell("wm size reset")
    adb.shell("wm density reset")
    adb.shell("settings put system font_scale 1.0")
    return "Reset the display size and font size to the phone's defaults."
