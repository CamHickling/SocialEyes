"""Screen brightness and Neon scene camera exposure per phone model (CAM-227).

Panels differ (OLED or LCD, peak brightness), so the brightness at which the Neon's scene camera
reads the on-screen tags without blowing out the photos is a property of the phone model. A
settings test (`settings_test` step, scored by `python -m socialeyes.gaze.settings_test ... --save`)
is run once per model and its best setting kept here. An eye-tracking study that leaves
display.brightness or neon.scene_exposure blank then gets that phone model's setting: the loader
copies it to the phone as phone_settings.json and the app fills the blanks from it (logged with
source phone_model). A study that sets them keeps its own.

Settings tested here ship with SocialEyes (TESTED); a lab's own results are kept in this computer's
settings.json under phone_models and win over them.
"""
from __future__ import annotations

from typing import Optional

from .. import settings

# key: "<manufacturer>/<model>" in lower case, as the app reports them (Build.MANUFACTURER, Build.MODEL)
TESTED: dict[str, dict] = {
    "motorola/motorola edge 40 pro": {
        "brightness": 0.30,
        # Companion's auto exposure aiming darker: its brightness control runs -64..64 on the Neon
        "scene_exposure": {"mode": "auto", "brightness": -32},
        "source": "settings test T01, 21 Oct 2026 (auto -50%; studies/pilot_neon)",
    },
}

PHONE_SETTINGS_FILE = "phone_settings.json"   # in the app's files folder, next to device_profile.json


def key(manufacturer: str, model: str) -> str:
    return f"{(manufacturer or '').strip().lower()}/{(model or '').strip().lower()}"


def lookup(manufacturer: str, model: str) -> Optional[dict]:
    """This phone model's settings: this computer's own result, else the one that ships, else None."""
    k = key(manufacturer, model)
    own = settings.load().get("phone_models", {}).get(k)
    if isinstance(own, dict):
        return dict(own)
    return dict(TESTED[k]) if k in TESTED else None


def save(manufacturer: str, model: str, brightness: float, scene_exposure: dict, source: str) -> dict:
    """Keeps a settings test's result as this phone model's setting on this computer."""
    entry = {"brightness": round(float(brightness), 3), "scene_exposure": scene_exposure, "source": source}
    data = settings.load()
    data.setdefault("phone_models", {})[key(manufacturer, model)] = entry
    settings.save(data)
    return entry


def exposure_from_camera(camera: dict) -> dict:
    """Companion's camera control values as the settings test logged them (ae_mode, man_exp, gain,
    brightness) -> a neon.scene_exposure."""
    mode = camera.get("ae_mode", "auto")
    out: dict = {"mode": mode}
    if mode == "manual":
        out["exposure_us"] = int(float(camera["man_exp"]))
        if camera.get("gain") is not None:
            out["gain"] = int(float(camera["gain"]))
    elif camera.get("brightness") is not None:
        out["brightness"] = int(float(camera["brightness"]))
    return out


def describe(entry: dict) -> str:
    e = entry.get("scene_exposure") or {}
    if e.get("mode") == "manual":
        cam = f"manual exposure {e.get('exposure_us')} µs"
    else:
        cam = "auto exposure" + (f", target brightness {e['brightness']}" if e.get("brightness") is not None else "")
    return f"screen brightness {entry.get('brightness'):g}, scene camera {cam}"


def checks(manufacturer: str, model: str, study: dict, eye_tracking: bool) -> tuple[list[tuple[str, str]], Optional[dict]]:
    """(level, text) for the loader, and the phone_settings.json to copy to the phone (None: none).

    `study` is the compiled study.json's study: its display.brightness and neon.scene_exposure."""
    if not eye_tracking:
        return [], None
    if not model:
        return [], None
    entry = lookup(manufacturer, model)
    brightness = (study.get("display") or {}).get("brightness")
    neon = study.get("neon") or {}
    exposure = neon.get("scene_exposure") if neon.get("auto_record", True) else None
    if entry is None:
        if brightness is None or exposure is None:
            return [("warn", f"No settings test on file for this phone model ({model}), and the study leaves the "
                             "screen brightness or the scene camera exposure blank: run a Settings test study once "
                             "with the glasses on this model, or set them under Recording.")], None
        return [("info", f"No settings test on file for this phone model ({model}); the study's own screen "
                         "brightness and scene camera exposure are used.")], None
    out: list[tuple[str, str]] = []
    if brightness is None or exposure is None:
        blank = " and ".join(n for n, v in (("screen brightness", brightness), ("scene camera exposure", exposure)) if v is None)
        out.append(("info", f"The study leaves the {blank} blank: this phone model's tested setting fills it "
                            f"({describe(entry)})."))
    differs = []
    if brightness is not None and abs(float(brightness) - float(entry["brightness"])) > 1e-6:
        differs.append(f"screen brightness {brightness:g}")
    if exposure is not None and exposure != entry.get("scene_exposure"):
        differs.append("its scene camera exposure")
    if differs:
        out.append(("warn", f"The study fixes {' and '.join(differs)}, which differs from this phone model's settings "
                            f"test ({describe(entry)}). Leave them blank under Recording to use the phone's."))
    elif brightness is not None and exposure is not None:
        out.append(("ok", f"The study's screen brightness and exposure match this phone model's settings test."))
    payload = {"manufacturer": manufacturer, "model": model, "brightness": entry["brightness"],
               "scene_exposure": entry.get("scene_exposure"), "source": entry.get("source", "")}
    return out, payload
