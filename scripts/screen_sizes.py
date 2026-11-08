"""CAM-227: the feed with its bar tags on a range of screen sizes, on emulators, so a layout that
breaks on some phone shows up before a phone does.

    python scripts/screen_sizes.py [--only NAME ...] [--keep-avds] [-o analysis_out/screen_sizes]

For each screen in SIZES it makes an emulator with that screen (an Android 14 image, under
.toolchain/avd/se_<name>.avd, its data wiped each time), starts it without a window, loads a copy of
studies/tag_ui with the chosen tag layout (16h5 10 mm, 3 mm from the sides, 2 mm from the top and
bottom), screenshots every feed screen (scripts/tag_ui_shots.py) and checks:

- the loader's layout checks against the device_profile.json the app writes (a rounded corner or a
  camera cut-out over a tag, too little room between the top tags for the wordmark and icons);
- the wordmark, read from the screen, clear of the top tags and not shrunk below MIN_WORDMARK_DP.

Writes <out>/<size>/<screen>.png, <out>/checks.json and <out>/index.html; exits 1 if a check failed.
Emulators only: it never runs on a phone (the look test deletes its own session data).
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python" / "src"))
sys.path.insert(0, str(Path(__file__).parent))
from socialeyes.phone.adb import APP_FILES, Adb  # noqa: E402
from socialeyes.phone.layout import layout_checks, tag_boxes  # noqa: E402
from socialeyes.phone.loader import load  # noqa: E402
from tag_ui_shots import SCREENS, Phone, capture, study_id  # noqa: E402

SDK = ROOT / ".toolchain" / "android-sdk"
AVD_HOME = ROOT / ".toolchain" / "avd"
BASE_AVD = AVD_HOME / "socialeyes_test.avd" / "config.ini"
PORT = 5580
MIN_WORDMARK_DP = 90    # the wordmark shrinks to fit (FittedWordmark); below this it stops reading as one

# name, label, width px, height px, dpi (the emulator reports it as xdpi too), cut-out overlay
SIZES = [
    ("small", "Small, 4.7 in, 720 x 1280", 720, 1280, 320, None),
    ("narrow", "Narrow, 320 dp wide", 640, 1360, 320, None),
    ("pixel3", "Pixel 3 size, 1080 x 2160", 1080, 2160, 440, None),
    ("edge40", "Edge 40 Pro size with a punch hole, 1080 x 2400", 1080, 2400, 400, "hole"),
    ("large", "Large, 1440 x 3120", 1440, 3120, 560, "corner"),
]
CUTOUTS = {"hole": "com.android.internal.display.cutout.emulation.hole",
           "corner": "com.android.internal.display.cutout.emulation.corner"}


class EmulatorPhone(Phone):
    """Patience for a software-rendered emulator: screens take seconds longer to appear than on a phone."""

    def find(self, match, tries: int = 30) -> dict:
        return super().find(match, max(tries, 30))


def make_avd(name: str, w: int, h: int, dpi: int) -> str:
    """An AVD like socialeyes_test with this screen; returns its name."""
    avd = f"se_{name}"
    folder = AVD_HOME / f"{avd}.avd"
    folder.mkdir(parents=True, exist_ok=True)
    cfg = BASE_AVD.read_text(encoding="utf-8")
    for key, value in (("hw.lcd.width", w), ("hw.lcd.height", h), ("hw.lcd.density", dpi), ("avd.name", avd),
                       ("avd.id", avd), ("showDeviceFrame", "no"), ("hw.camera.back", "none")):
        cfg = re.sub(rf"^{re.escape(key)} = .*$", f"{key} = {value}", cfg, flags=re.M)
    (folder / "config.ini").write_text(cfg, encoding="utf-8")
    (AVD_HOME / f"{avd}.ini").write_text(
        f"avd.ini.encoding=UTF-8\npath={folder}\ntarget=android-34\n", encoding="utf-8")
    return avd


def start(avd: str) -> subprocess.Popen:
    env = {**os.environ, "ANDROID_AVD_HOME": str(AVD_HOME), "ANDROID_SDK_ROOT": str(SDK)}
    return subprocess.Popen(
        [str(SDK / "emulator" / "emulator.exe"), "-avd", avd, "-port", str(PORT), "-no-window", "-no-audio",
         "-no-boot-anim", "-no-snapshot", "-wipe-data", "-gpu", "swiftshader_indirect"],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def wait_booted(adb: Adb, timeout: float = 600) -> None:
    t0 = time.time()
    while time.time() - t0 < timeout:
        # booted, and shared storage mounted (after a wipe it comes up some seconds later)
        if (adb.run("shell", "getprop sys.boot_completed", check=False).strip() == "1"
                and "ok" in adb.run("shell", "ls /sdcard/Android/data >/dev/null 2>&1 && echo ok", check=False)):
            time.sleep(5)
            return
        time.sleep(3)
    raise RuntimeError("the emulator didn't finish starting")


def stop(adb: Adb, proc: subprocess.Popen) -> None:
    adb.run("emu", "kill", check=False)
    try:
        proc.wait(60)
    except subprocess.TimeoutExpired:
        proc.kill()


def screen_study(src: Path, dest: Path) -> Path:
    """studies/tag_ui with the tag layout chosen on 21 Oct (3 mm sides, 2 mm edges)."""
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns("__pycache__"))
    y = (dest / "study.yaml").read_text(encoding="utf-8")
    y = re.sub(r"^(    size_mm: 10)$", r"\1\n    side_inset_mm: 3\n    edge_gap_mm: 2", y, count=1, flags=re.M)
    (dest / "study.yaml").write_text(y, encoding="utf-8")
    return dest


def tags_of(study: Path) -> dict:
    import yaml
    return yaml.safe_load((study / "study.yaml").read_text(encoding="utf-8"))["markers"]["on_screen"]


def wordmark_checks(phone: Phone, name: str, profile: dict, tags: dict) -> list[tuple[str, str]]:
    """The wordmark on the feed's top bar: clear of the top tags, and not shrunk to nothing."""
    nodes = [n for n in phone.nodes() if n["text"] == name and n["w"] > 0]
    if not nodes:
        return [("fail", "The wordmark isn't on screen.")]
    n = min(nodes, key=lambda n: n["y"])
    box = (n["x"] - n["w"] / 2, n["y"] - n["h"] / 2, n["x"] + n["w"] / 2, n["y"] + n["h"] / 2)
    out = []
    for corner in ("top_left", "top_right"):
        t = tag_boxes(profile, tags, quiet_zone=False)[corner]
        if box[0] < t[2] and t[0] < box[2] and box[1] < t[3] and t[1] < box[3]:
            out.append(("fail", f"The wordmark overlaps the {corner.replace('_', '-')} tag."))
    dp = n["w"] / profile.get("density", 1)
    if dp < MIN_WORDMARK_DP:
        out.append(("fail", f"The wordmark is only {dp:.0f} dp wide (under {MIN_WORDMARK_DP})."))
    return out or [("ok", f"Wordmark {dp:.0f} dp wide, clear of the tags.")]


def run_size(size: tuple, study: Path, out: Path) -> dict:
    name, label, w, h, dpi, cutout = size
    avd = make_avd(name, w, h, dpi)
    adb = Adb(f"emulator-{PORT}")
    print(f"{label}: starting {avd}…", flush=True)
    proc = start(avd)
    result = {"name": name, "label": label, "screen": [w, h, dpi], "cutout": cutout, "checks": []}
    try:
        adb.run("wait-for-device", timeout=300)
        wait_booted(adb)
        if cutout:
            adb.shell(f"cmd overlay enable {CUTOUTS[cutout]}")
            time.sleep(3)
        adb.shell("cmd notification set_dnd priority")    # Do Not Disturb, as on a session phone
        r = load(study, serial=adb.serial, update_app=True, anyway=True, progress=lambda m: print("  ", m, flush=True))
        if not r.loaded:
            raise RuntimeError(f"couldn't load the study: {r.error or [c.text for c in r.checks if c.level == 'block']}")
        phone = EmulatorPhone(adb.serial)
        adb.shell("monkey -p org.socialeyes.pictogram -c android.intent.category.LAUNCHER 1")
        phone.find(lambda n: n["text"] == "Study", tries=60)    # the first start is the slow one
        pname = re.search(r"^  name: (\S+)", (study / "study.yaml").read_text(encoding="utf-8"), re.M).group(1)
        capture(phone, study_id(study), pname, out / name)
        profile = json.loads(adb.shell(f"cat {APP_FILES}/device_profile.json"))
        result["profile"] = profile
        tags = tags_of(study)
        problems = [("fail", t) for lvl, t in layout_checks(profile, tags) if lvl == "warn"]
        result["checks"] = problems or [("ok", "Layout checks pass: no tag clipped or covered, room for the bar row.")]
        result["checks"] += wordmark_from_shot(phone, adb, study, pname, profile, tags)
    except Exception as e:  # noqa: BLE001 - one size failing shouldn't stop the others
        result["checks"].append(("fail", f"Couldn't run: {e}"))
    finally:
        stop(adb, proc)
    for lvl, t in result["checks"]:
        print(f"   {lvl}: {t}", flush=True)
    return result


def wordmark_from_shot(phone: Phone, adb: Adb, study: Path, pname: str, profile: dict, tags: dict) -> list:
    """Starts one more session to read the feed's top bar (capture() ends on the reels screen)."""
    from socialeyes.phone.adb import PACKAGE
    sid = study_id(study)
    adb.shell(f"am force-stop {PACKAGE}")
    adb.shell(f"monkey -p {PACKAGE} -c android.intent.category.LAUNCHER 1")
    time.sleep(3)
    phone.tap_text(sid)
    phone.tap(phone.find(lambda n: re.fullmatch(r"[A-Z]+\d+( ✓)?", n["text"]) is not None))
    phone.tap_text("Start session for", prefix=True, wait=1.5)
    for text in ("Start", "Continue without eye tracking", "Continue"):
        if any(n["text"] == text for n in phone.nodes()):
            phone.tap_text(text, wait=2)
    phone.find(lambda n: n["text"] == pname)
    checks = wordmark_checks(phone, pname, profile, tags)
    adb.shell(f"am force-stop {PACKAGE}")
    adb.shell(f"rm -r {APP_FILES}/data/{sid}")
    return checks


def report(out: Path, results: list[dict]) -> Path:
    head = "".join(f"<th>{html.escape(r['label'])}</th>" for r in results)
    checks = "".join(
        "<td>" + "".join(f'<p class="{lvl}">{"✓" if lvl == "ok" else "✗"} {html.escape(t)}</p>' for lvl, t in r["checks"]) + "</td>"
        for r in results)
    rows = "".join(
        f"<tr><th>{html.escape(label)}</th>" + "".join(
            f'<td><img src="{r["name"]}/{key}.png" loading="lazy" alt="{html.escape(label)}, {html.escape(r["label"])}"></td>'
            if (out / r["name"] / f"{key}.png").exists() else "<td>-</td>" for r in results) + "</tr>"
        for key, label in SCREENS)
    page = f"""<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Screen sizes</title>
<style>
:root{{--bg:#fff;--fg:#1a1a1a;--muted:#666;--line:#ddd;--ok:#1a7f37;--bad:#c62828}}
@media (prefers-color-scheme:dark){{:root{{--bg:#151515;--fg:#eee;--muted:#aaa;--line:#333;--ok:#5fd17a;--bad:#ff7b72}}}}
body{{background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif;margin:0;padding:16px}}
h1{{font-size:22px}} .wrap{{overflow-x:auto}} table{{border-collapse:collapse}}
th,td{{border-top:1px solid var(--line);padding:8px;vertical-align:top;text-align:left}}
td{{min-width:180px;max-width:240px}} img{{width:100%;border:1px solid var(--line);border-radius:10px}}
p{{margin:0 0 4px;font-size:13px}} .ok{{color:var(--ok)}} .fail{{color:var(--bad)}}
</style>
<h1>The feed with its bar tags on other screen sizes (CAM-227)</h1>
<p>Emulators (Android 14), study tag_ui with tags 16h5 10 mm, 3 mm from the sides and 2 mm from the top and bottom.</p>
<div class=wrap><table><tr><th></th>{head}</tr><tr><th>Checks</th>{checks}</tr>{rows}</table></div>
"""
    path = out / "index.html"
    path.write_text(page, encoding="utf-8")
    return path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--only", nargs="*", help="sizes to run (default: all): " + ", ".join(s[0] for s in SIZES))
    ap.add_argument("--study", type=Path, default=ROOT / "studies" / "tag_ui")
    ap.add_argument("--keep-avds", action="store_true", help="leave the emulators' folders (about 1 GB each)")
    ap.add_argument("-o", "--out", type=Path, default=ROOT / "analysis_out" / "screen_sizes")
    a = ap.parse_args()
    if any(d.serial and not d.serial.startswith("emulator-") for d in Adb().devices()):
        print("note: a phone is connected; this only uses its own emulator (emulator-%d)" % PORT, flush=True)
    study = screen_study(a.study, ROOT / "build" / "screen_sizes_src")
    sizes = [s for s in SIZES if not a.only or s[0] in a.only]
    a.out.mkdir(parents=True, exist_ok=True)
    results = []
    for size in sizes:
        results.append(run_size(size, study, a.out))
        if not a.keep_avds:
            shutil.rmtree(AVD_HOME / f"se_{size[0]}.avd", ignore_errors=True)
            (AVD_HOME / f"se_{size[0]}.ini").unlink(missing_ok=True)
    (a.out / "checks.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(report(a.out, results))
    return 1 if any(lvl == "fail" for r in results for lvl, _ in r["checks"]) else 0


if __name__ == "__main__":
    sys.exit(main())
