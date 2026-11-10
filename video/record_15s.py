"""Capture the raw material for the 15-second SocialEyes clip (video/shotlist-15s.md).

Everything comes from the example study's placeholder images. No pilot data,
sessions or real stimuli are read, and nothing outside video/build/ and the
private emulator folder is written.

Steps (each can be run on its own with --only):
  phone    Boots a private Pixel 3 emulator (its own AVD folder, no window),
           loads a feed-only copy of the example study, starts a session,
           saves screenshots while scrolling, stitches them into one tall
           image of the feed, then scrolls back to the labelled post and
           records a double-tap like with `adb shell screenrecord`.
           (The emulator records scrolling at ~16 fps, so the edit scrolls
           through the stitched screenshots instead; every pixel is the app's.)
  builder  Renders the guided builder's Design page with the example study,
           scrolling, frame by frame in a hidden Edge window (Playwright).
  heatmap  Draws a heatmap of SIMULATED fixations on the labelled post with
           SocialEyes's own heatmap code (gaze/heatmap.py).

Output: video/build/raw15/ (gitignored). Then run video/edit_15s.py.

Needs: numpy, Pillow, pandas, matplotlib, pyyaml, playwright (uses installed
Microsoft Edge), and the project toolchain (.toolchain/android-sdk).

    python video/record_15s.py                  # all steps
    python video/record_15s.py --only builder   # one step
"""

import argparse
import io
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parent.parent
RAW = REPO / "video" / "build" / "raw15"
WORK = REPO / "video" / "build" / "work"
SDK = REPO / ".toolchain" / "android-sdk"
ADB = SDK / "platform-tools" / "adb.exe"
EMULATOR = SDK / "emulator" / "emulator.exe"
SOURCE_AVD = REPO / ".toolchain" / "avd" / "se_pixel3.avd"
PORT = 5580
SERIAL = f"emulator-{PORT}"
APP = "org.socialeyes.pictogram"
APK = REPO / "android" / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"

STEP_PX = 600          # drag distance per screenshot
SHOTS = 16             # screenshots down the feed


# --- adb ---------------------------------------------------------------------

def adb(*args, check=True):
    r = subprocess.run([str(ADB), "-s", SERIAL, *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"adb {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout


def grab():
    png = subprocess.run([str(ADB), "-s", SERIAL, "exec-out", "screencap", "-p"],
                         capture_output=True, check=True).stdout
    return np.asarray(Image.open(io.BytesIO(png)).convert("RGB"))


def ui_nodes():
    import re
    import xml.etree.ElementTree as ET
    for _ in range(10):   # the dump fails while the system is busy; try again
        adb("shell", "uiautomator", "dump", "/sdcard/ui.xml", check=False)
        xml = adb("exec-out", "cat", "/sdcard/ui.xml", check=False)
        if "<" in xml:
            break
        time.sleep(2)
    else:
        return []
    out = []
    for n in ET.fromstring(xml[xml.index("<"):]).iter("node"):
        m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", n.get("bounds", ""))
        if m:
            out.append((n.get("text") or n.get("content-desc") or "", tuple(map(int, m.groups()))))
    return out


def tap_text(text, exact=False, timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        for t, (x0, y0, x1, y1) in ui_nodes():
            if (t == text) if exact else (text.lower() in t.lower()):
                adb("shell", "input", "tap", str((x0 + x1) // 2), str((y0 + y1) // 2))
                return
        time.sleep(1)
    raise TimeoutError(f"'{text}' never appeared on the phone")


def visible(text):
    return any(text.lower() in t.lower() for t, _ in ui_nodes())


def drag(dy, steps=20, x=540):
    """Slow drag by dy px (positive scrolls down), held still at the end so there's no fling."""
    y0 = 1700 if dy > 0 else 400
    adb("shell", "input", "motionevent", "DOWN", str(x), str(y0))
    for k in range(1, steps + 1):
        adb("shell", "input", "motionevent", "MOVE", str(x), str(int(y0 - dy * k / steps)))
    time.sleep(0.6)
    adb("shell", "input", "motionevent", "UP", str(x), str(int(y0 - dy)))
    time.sleep(1.0)


def load_avg():
    import re
    return float(re.search(r"load average: ([\d.]+)", adb("shell", "uptime")).group(1))


# --- emulator ----------------------------------------------------------------

def avd_home():
    return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "SocialEyes-video" / "avd"


def ensure_emulator():
    """Boots the private 'se_video' AVD (created from se_pixel3's settings) unless it is running."""
    if SERIAL in subprocess.run([str(ADB), "devices"], capture_output=True, text=True).stdout:
        if APP not in adb("shell", "pm", "list", "packages", APP):
            adb("install", "-r", str(APK))
        return None
    home = avd_home()
    avd = home / "se_video.avd"
    fresh = not avd.exists()
    if fresh:
        avd.mkdir(parents=True)
        cfg = [l for l in (SOURCE_AVD / "config.ini").read_text().splitlines()
               if not l.startswith(("disk.dataPartition.path", "avd.id", "avd.name"))]
        (avd / "config.ini").write_text("\n".join(cfg) + "\n")
        (home / "se_video.ini").write_text(f"avd.ini.encoding=UTF-8\npath={avd}\ntarget=android-34\n")
    env = dict(os.environ, ANDROID_AVD_HOME=str(home), ANDROID_SDK_ROOT=str(SDK))
    args = [str(EMULATOR), "-avd", "se_video", "-port", str(PORT), "-no-window", "-no-audio",
            "-no-boot-anim", "-no-snapshot", "-memory", "3072", "-cores", "4", "-gpu", "host"]
    if fresh:
        args.append("-wipe-data")
    proc = subprocess.Popen(args, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("Booting the private emulator...")
    deadline = time.time() + 600
    while time.time() < deadline:
        r = subprocess.run([str(ADB), "-s", SERIAL, "shell", "getprop", "sys.boot_completed"],
                           capture_output=True, text=True)
        if r.stdout.strip() == "1":
            break
        time.sleep(5)
    else:
        raise TimeoutError("the emulator didn't boot")
    while time.time() < deadline:   # wait for storage and for the post-boot load to settle
        probe = "mkdir -p /sdcard/Android/data && touch /sdcard/Download/.probe && rm /sdcard/Download/.probe && echo ok"
        if "ok" in adb("shell", probe, check=False) and load_avg() < 5:
            break
        time.sleep(10)
    if fresh:
        adb("install", "-r", str(APK))
    return proc


def feed_only_study():
    """A copy of the example study whose procedure is welcome -> feed -> end (same posts and images)."""
    import yaml
    dst = WORK / "study" / "example"
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(REPO / "studies" / "example", dst,
                    ignore=shutil.ignore_patterns("__pycache__", "build"))
    y = yaml.safe_load((dst / "study.yaml").read_text(encoding="utf-8"))
    y["procedure"] = [s for s in y["procedure"] if s["id"] in ("welcome", "feed", "end")]
    if "markers" in y and "on_screen" in y["markers"]:
        y["markers"]["on_screen"]["steps"] = ["feed"]
    (dst / "study.yaml").write_text(yaml.safe_dump(y, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return dst


def load_study(study):
    """`socialeyes load` with an empty data folder, so no session history reaches the phone."""
    empty = WORK / "empty_data"
    empty.mkdir(parents=True, exist_ok=True)
    settings = WORK / "settings.json"
    settings.write_text(json.dumps({"studies": {"example": {"data_dir": str(empty)}}}))
    exe = REPO / ".toolchain" / "env" / "Scripts" / "socialeyes.exe"
    env = dict(os.environ, SOCIALEYES_SETTINGS=str(settings), PYTHONIOENCODING="utf-8")
    for attempt in range(4):   # storage can still be settling just after boot
        if subprocess.run([str(exe), "load", "--serial", SERIAL, "--anyway", str(study)], env=env).returncode == 0:
            return
        time.sleep(15)
    raise RuntimeError("socialeyes load failed")


def start_feed(timeout=180):
    """From a fresh app start to the feed: react to whichever screen is showing."""
    adb("shell", "settings", "put", "global", "hide_error_dialogs", "1")
    adb("shell", "cmd", "notification", "set_dnd", "priority")
    adb("shell", "am", "force-stop", APP)
    adb("shell", "monkey", "-p", APP, "-c", "android.intent.category.LAUNCHER", "1")
    deadline = time.time() + timeout
    while time.time() < deadline:
        texts = {t: b for t, b in ui_nodes() if t}
        def press(label):
            x0, y0, x1, y1 = texts[label]
            adb("shell", "input", "tap", str((x0 + x1) // 2), str((y0 + y1) // 2))
        start = next((t for t in texts if t.startswith("Start the next participant")), None)
        if any(t in texts for t in ("Your story",)) or any(t.endswith(" likes") for t in texts):
            time.sleep(2)
            return
        if start:
            press(start)
        elif "Continue without eye tracking" in texts:
            press("Continue without eye tracking")
        elif "Got it" in texts:
            press("Got it")
        elif "Continue" in texts:
            press("Continue")
        time.sleep(3)
    raise TimeoutError("couldn't get from the app's start screen to the feed")


# --- stitching ---------------------------------------------------------------

def scroll_rows(shots):
    """Rows that scroll with the feed (between the fixed top and bottom bars), and the step."""
    a = shots[0].astype(np.int16)
    b = shots[1].astype(np.int16)
    h = a.shape[0]
    mid = slice(h // 3, 2 * h // 3)
    step = min(range(300, 900), key=lambda s: np.abs(a[mid][s:] - b[mid][:-s]).mean())
    moving = np.zeros(h, bool)
    for y in range(h):
        if y + step >= h:
            continue
        diffs_s, diffs_m = [], []
        for x, z in zip(shots, shots[1:]):
            x16, z16 = x.astype(np.int16), z.astype(np.int16)
            diffs_m.append(np.abs(z16[y, 100:] - x16[y + step, 100:]).mean())
            diffs_s.append(np.abs(z16[y, 100:] - x16[y, 100:]).mean())
        moving[y] = np.mean(diffs_m) < 0.5 and np.mean(diffs_s) > 0.0
    ys = np.where(moving)[0]
    top, bot = int(ys.min()), int(ys.max()) + 1
    # rows below `bot` that can't be tested (y + step >= h) belong to the feed until the bottom bar
    for y in range(bot, h):
        if all(np.abs(shots[0][y, 100:].astype(int) - s[y, 100:].astype(int)).max() < 6 for s in shots[1:]):
            bot = y
            break
    return top, bot, step


def stitch(shots, top, bot, step):
    offs = [0]
    for x, z in zip(shots, shots[1:]):
        a, b = x[top:bot].astype(np.int16).mean(axis=2), z[top:bot].astype(np.int16).mean(axis=2)
        n = bot - top
        s = min(range(step - 40, step + 40), key=lambda s: np.abs(a[s:] - b[:n - s]).mean())
        offs.append(offs[-1] + s)
    h = offs[-1] + (bot - top)
    strip = np.zeros((h, shots[0].shape[1], 3), np.uint8)
    for i in reversed(range(len(shots))):
        strip[offs[i]:offs[i] + bot - top] = shots[i][top:bot]
    err = max(np.abs(shots[i][top:bot].astype(int) - strip[offs[i]:offs[i] + bot - top]).mean()
              for i in range(len(shots)))
    return strip, err


def offset_in(strip, im, top, bot):
    s = strip.astype(np.int16).mean(axis=2)
    a = im[top:bot].astype(np.int16).mean(axis=2)
    n = bot - top
    best = min((np.abs(s[o:o + n:8] - a[::8]).mean(), o) for o in range(0, s.shape[0] - n, 2))[1]
    return min((np.abs(s[k:k + n] - a).mean(), k)
               for k in range(max(0, best - 3), min(best + 4, s.shape[0] - n + 1)))[::-1]


def labelled_post(strip):
    """(image top, image bottom) of the first post carrying the 'edited' banner."""
    col = strip[:, 900].astype(int)
    dark = np.where((np.ptp(col, axis=1) < 8) & (col[:, 0] > 40) & (col[:, 0] < 100))[0]
    white = strip[:, 20:1060].min(axis=(1, 2)) > 245
    first = dark[0]
    run_end = first
    while run_end + 1 < len(col) and run_end + 1 in set(dark[:400]):
        run_end += 1
    y = first
    while not white[y]:
        y -= 1
    return int(y + 1), int(run_end)


# --- steps -------------------------------------------------------------------

def step_phone():
    proc = ensure_emulator()
    load_study(feed_only_study())
    start_feed()
    shots_dir = RAW / "phone_shots"
    if shots_dir.exists():
        shutil.rmtree(shots_dir)
    shots_dir.mkdir(parents=True)
    shots = [grab()]
    for _ in range(SHOTS - 1):
        drag(STEP_PX)
        shots.append(grab())
    for i, s in enumerate(shots):
        Image.fromarray(s).save(shots_dir / f"s{i:02d}.png")
    top, bot, step = scroll_rows(shots)
    strip, err = stitch(shots, top, bot, step)
    print(f"Feed rows {top}..{bot} scroll (step {step} px); stitched {strip.shape[0]} px, error {err:.3f}")
    if err > 0.5:
        raise RuntimeError("the screenshots don't stitch exactly; nothing was saved")
    Image.fromarray(strip).save(RAW / "feed_strip.png")
    Image.fromarray(shots[0][:top]).save(RAW / "topbar_plain.png")
    Image.fromarray(shots[-1][:top]).save(RAW / "topbar_done.png")
    Image.fromarray(shots[0][bot:]).save(RAW / "botbar.png")

    # back to the labelled post, then record the like
    img_top, img_bot = labelled_post(strip)
    target = img_top - 120
    o, _ = offset_in(strip, grab(), top, bot)
    for _ in range(25):
        diff = target - o
        if abs(diff) <= 1:
            break
        move = max(-1500, min(1500, diff))
        drag(move + (22 if move > 0 else -22))
        o, _ = offset_in(strip, grab(), top, bot)
    cy = top + (img_top + img_bot) // 2 - o
    rec = subprocess.Popen([str(ADB), "-s", SERIAL, "shell", "screenrecord", "--bit-rate", "16000000",
                            "--time-limit", "5", "/sdcard/like.mp4"])
    time.sleep(1.5)
    adb("shell", f"input tap 540 {cy}; input tap 540 {cy}")
    rec.wait()
    adb("pull", "/sdcard/like.mp4", str(RAW / "like.mp4"))
    (RAW / "phone.json").write_text(json.dumps({"top": top, "bot": bot, "target": int(o),
                                                "img_top": img_top, "img_bot": img_bot}, indent=2))
    print(f"Like recorded at feed offset {o} (target {target})")
    if proc:
        adb("emu", "kill", check=False)


def step_builder():
    from playwright.sync_api import sync_playwright
    out = RAW / "builder"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    n, hold = 120, 12
    ease = lambda p: p * p * (3 - 2 * p)  # noqa: E731
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1180, "height": 540}, device_scale_factor=2)
        page.goto((REPO / "builder" / "index.html").as_uri())
        page.set_input_files("#open-file", str(REPO / "studies" / "example" / "study.yaml"))
        page.wait_for_timeout(800)
        page.get_by_text("Design", exact=True).first.click()
        page.wait_for_timeout(800)
        page.evaluate("document.documentElement.style.scrollBehavior='auto'")
        end = page.evaluate("document.documentElement.scrollHeight - innerHeight")
        for i in range(n):
            q = min(max((i - hold) / (n - 2 * hold), 0), 1)
            page.evaluate(f"window.scrollTo(0, {end * ease(q):.1f})")
            page.screenshot(path=str(out / f"f{i:03d}.png"))
        browser.close()
    print(f"Builder: {n} frames")


def step_heatmap():
    import pandas as pd
    sys.path.insert(0, str(REPO / "python" / "src"))
    from socialeyes.gaze.heatmap import _density, _overlay, sigma_img_px

    pos = json.loads((RAW / "phone.json").read_text())
    strip = np.asarray(Image.open(RAW / "feed_strip.png").convert("RGB"))
    base = strip[pos["img_top"]:pos["img_bot"] + 1].astype(float)   # the post as shown, label included
    h, w = base.shape[:2]
    rng = np.random.default_rng(7)
    # SIMULATED fixations (not participant data): face, torso/waist, label, legs
    clusters = [((540, 0.20 * h), 9, 60), ((540, 0.50 * h), 14, 80), ((520, 0.60 * h), 8, 70),
                ((300, 0.955 * h), 6, 50), ((540, 0.80 * h), 4, 80)]
    rows = [(cx + rng.normal(0, sp), cy + rng.normal(0, sp), rng.uniform(150, 450))
            for (cx, cy), n, sp in clusters for _ in range(n)]
    fx = pd.DataFrame(rows, columns=["img_x", "img_y", "duration_ms"])
    sigma = np.full(len(fx), sigma_img_px(px_per_mm=17.3, distance_mm=350.0, img_per_screen_px=1.0))
    dens = _density(fx, sigma, w, h)
    Image.fromarray(_overlay(base, dens, "inferno", float(dens.max()), signed=False)).save(RAW / "heatmap.png")
    print(f"Heatmap: {len(fx)} simulated fixations")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--only", choices=["phone", "builder", "heatmap"], nargs="*")
    args = parser.parse_args()
    RAW.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    steps = args.only or ["phone", "builder", "heatmap"]
    for name in steps:
        print(f"== {name}")
        {"phone": step_phone, "builder": step_builder, "heatmap": step_heatmap}[name]()


if __name__ == "__main__":
    main()
