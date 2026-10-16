"""CAM-165: how the app looks with the screen tags in its bars. Screenshots of every feed screen
(top of the feed, scrolled, comments, a story, reels), with the tags and without, side by side.

    python scripts/tag_ui_shots.py [--serial S] [--study studies/tag_ui] [--skip-load] [-o analysis_out/tag_ui]

Loads the study (markers.on_screen layout bars) and a copy of it with the tags off (id
<study>_plain) onto the phone, installing a newer app if there is one, then for each starts a
session, steps through the screens with adb and saves a screenshot of each. The sessions are
abandoned part-way and then deleted from the phone (only these two look-test studies' data).
Writes <out>/<variant>/<screen>.png and <out>/index.html. The phone must be unlocked.
"""
from __future__ import annotations

import argparse
import html
import re
import shutil
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "python" / "src"))
from socialeyes.phone.adb import APP_FILES, PACKAGE, Adb  # noqa: E402
from socialeyes.phone.loader import load  # noqa: E402

SCREENS = [
    ("feed", "Top of the feed"),
    ("done", "With the \"I'm done\" button"),
    ("scrolled", "Scrolled to a post"),
    ("comments", "Comments sheet"),
    ("story", "A story"),
    ("reels", "Reels"),
]


class Phone:
    def __init__(self, serial: str | None):
        self.adb = Adb(serial)

    def nodes(self, tries: int = 4) -> list[dict]:
        """Every node of the screen's accessibility tree: text, content-desc and bounds."""
        for _ in range(tries):
            self.adb.shell("uiautomator dump /sdcard/se_ui.xml >/dev/null 2>&1")
            xml = self.adb.run("exec-out", "cat /sdcard/se_ui.xml", check=False)
            if "<hierarchy" in xml:
                out = []
                for n in ET.fromstring(xml[xml.index("<?xml"):] if "<?xml" in xml else xml).iter("node"):
                    x0, y0, x1, y1 = map(int, re.findall(r"\d+", n.get("bounds", "[0,0][0,0]")))
                    out.append({"text": n.get("text", ""), "desc": n.get("content-desc", ""), "clickable": n.get("clickable") == "true",
                                "x": (x0 + x1) // 2, "y": (y0 + y1) // 2, "w": x1 - x0, "h": y1 - y0})
                return out
            time.sleep(1)
        raise RuntimeError("couldn't read the screen (uiautomator dump failed); is the phone unlocked?")

    def find(self, match, tries: int = 5) -> dict:
        for _ in range(tries):
            hits = [n for n in self.nodes() if match(n)]
            if hits:
                return min(hits, key=lambda n: n["y"])
            time.sleep(1)
        raise RuntimeError("not found on screen")

    def tap(self, n: dict, wait: float = 1.0) -> None:
        self.adb.shell(f"input tap {n['x']} {n['y']}")
        time.sleep(wait)

    def tap_text(self, text: str, wait: float = 1.0, prefix: bool = False) -> None:
        self.tap(self.find(lambda n: n["text"].startswith(text) if prefix else n["text"] == text), wait)

    def shot(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.adb.run_bytes("exec-out", "screencap -p"))

    def key(self, name: str, wait: float = 1.0) -> None:
        self.adb.shell(f"input keyevent {name}")
        time.sleep(wait)

    def tab(self, k: int) -> dict:
        """Tab bar button k (0 Home, 1 Reels). The app draws under the hidden navigation bar, below
        the area uiautomator reports, so the buttons are cut off there: a taller tab bar (with tags)
        shows the top of each icon, a plain one only the clickable boxes' top edge, ~33 dp above the
        bottom of the screen."""
        w, h = self.size()
        dens = self.density()
        nodes = self.nodes()
        icon = [n for n in nodes if n["desc"] == ("Home", "Reels")[k] and n["w"] > 0]
        if icon:  # the icon's top is visible; it is 26 dp tall
            return {"x": icon[0]["x"], "y": int(icon[0]["y"] - icon[0]["h"] / 2 + 13 * dens)}
        cut = sorted((n for n in nodes if n["clickable"] and 0 < n["h"] < 10 and n["w"] > 40 and n["y"] > h * 0.8),
                     key=lambda n: n["x"])
        return {"x": cut[k]["x"], "y": int(h - 33 * dens)}

    def density(self) -> float:
        """Pixels per dp."""
        return int(re.findall(r"density: (\d+)", self.adb.shell("wm density"))[-1]) / 160

    def size(self) -> tuple[int, int]:
        w, h = map(int, re.search(r"(\d+)x(\d+)", self.adb.shell("wm size")).groups())
        return w, h


def _run_bytes(self: Adb, *args: str) -> bytes:
    import subprocess
    cmd = [str(self.exe), *(["-s", self.serial] if self.serial else []), *args]
    return subprocess.run(cmd, capture_output=True, timeout=60, check=True).stdout


Adb.run_bytes = _run_bytes


def plain_copy(study: Path, dest: Path) -> Path:
    """The study with its on-screen tags off and its id + `_plain`."""
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(study, dest, ignore=shutil.ignore_patterns("__pycache__"))
    y = (dest / "study.yaml").read_text(encoding="utf-8")
    y = re.sub(r"^id: (\S+)", r"id: \1_plain", y, count=1, flags=re.M)
    y = re.sub(r"^title: (.*)$", r"title: \1 (no tags)", y, count=1, flags=re.M)
    y = re.sub(r"^markers:\n(?:[ #].*\n|\n)*?(?=^\S)", "", y, count=1, flags=re.M)
    (dest / "study.yaml").write_text(y, encoding="utf-8")
    return dest


def study_id(study: Path) -> str:
    return re.search(r"^id: (\S+)", (study / "study.yaml").read_text(encoding="utf-8"), re.M).group(1)


def capture(phone: Phone, sid: str, phone_name: str, out: Path) -> None:
    """Starts a session of study `sid` (platform name `phone_name`) and screenshots each screen into `out`."""
    w, h = phone.size()
    phone.adb.shell(f"am force-stop {PACKAGE}")
    phone.adb.shell(f"monkey -p {PACKAGE} -c android.intent.category.LAUNCHER 1")
    time.sleep(3)
    phone.tap_text(sid)
    pid = phone.find(lambda n: re.fullmatch(r"[A-Z]+\d+( ✓)?", n["text"]) is not None)
    phone.tap(pid)
    phone.tap_text("Start session for", prefix=True, wait=1.5)
    for text in ("Start", "Continue without eye tracking", "Continue"):  # "already has data", no glasses, a welcome step
        if any(n["text"] == text for n in phone.nodes()):
            phone.tap_text(text, wait=2)
    phone.find(lambda n: n["text"] == phone_name)  # the feed is up
    phone.shot(out / "feed.png")
    phone.find(lambda n: n["text"] == "I'm done", tries=30)
    phone.shot(out / "done.png")
    phone.adb.shell(f"input swipe {w // 2} {h * 7 // 10} {w // 2} {h * 3 // 10} 400")
    time.sleep(1.5)
    phone.shot(out / "scrolled.png")
    phone.tap(phone.find(lambda n: n["desc"] == "Comment" and h * 0.15 < n["y"] < h * 0.85), wait=1.5)
    phone.shot(out / "comments.png")
    phone.key("KEYCODE_BACK", 1.5)
    phone.tap(phone.tab(0), wait=3)  # Home: back to the top
    # the first story circle after "Your story": the next label on the same row
    nodes = phone.nodes()
    yours = next(n for n in nodes if n["text"] == "Your story")
    tray = sorted((n for n in nodes if n["text"] and abs(n["y"] - yours["y"]) < 20 and n["x"] > yours["x"]),
                  key=lambda n: n["x"])
    for _ in range(3):  # a tap while the feed still scrolls only stops it
        phone.tap({"x": tray[0]["x"], "y": tray[0]["y"] - int(50 * phone.density())}, wait=1.2)  # its circle
        if any(n["text"].startswith("Reply to") for n in phone.nodes()):
            break
    phone.shot(out / "story.png")
    phone.key("KEYCODE_BACK", 1.5)
    phone.tap(phone.tab(1), wait=2.5)
    phone.shot(out / "reels.png")
    phone.key("KEYCODE_BACK", 1.0)
    phone.adb.shell(f"am force-stop {PACKAGE}")
    phone.adb.shell(f"rm -r {APP_FILES}/data/{sid}")  # the look test's own abandoned session


def report(out: Path, variants: list[tuple[str, str]]) -> Path:
    rows = []
    for key, label in SCREENS:
        cells = "".join(
            f'<figure><img src="{v}/{key}.png" loading="lazy" alt="{html.escape(label)}, {html.escape(t)}">'
            f"<figcaption>{html.escape(t)}</figcaption></figure>"
            for v, t in variants if (out / v / f"{key}.png").exists()
        )
        rows.append(f"<section><h2>{html.escape(label)}</h2><div class=row>{cells}</div></section>")
    page = f"""<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Tags in the app's bars</title>
<style>
:root{{--bg:#fff;--fg:#1a1a1a;--muted:#666;--line:#ddd}}
@media (prefers-color-scheme:dark){{:root{{--bg:#151515;--fg:#eee;--muted:#aaa;--line:#333}}}}
body{{background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif;margin:0 auto;max-width:1100px;padding:16px}}
h1{{font-size:22px}} h2{{font-size:17px;margin:28px 0 8px;border-top:1px solid var(--line);padding-top:16px}}
.row{{display:flex;gap:16px;flex-wrap:wrap}} figure{{margin:0;flex:1 1 240px;max-width:340px}}
img{{width:100%;border:1px solid var(--line);border-radius:12px}} figcaption{{color:var(--muted);font-size:13px}}
</style>
<h1>Screen tags in the app's bars: how it looks</h1>
<p>AprilTag 16h5, 10 mm, black, in the corners of the top bar and the tab bar (<code>markers.on_screen</code>
layout <code>bars</code>), against the same feed without tags. Stories, reels and the comments sheet leave
both bars uncovered so the tags stay visible.</p>
{''.join(rows)}
"""
    path = out / "index.html"
    path.write_text(page, encoding="utf-8")
    return path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--serial")
    ap.add_argument("--study", type=Path, default=Path("studies/tag_ui"))
    ap.add_argument("--skip-load", action="store_true", help="the studies are on the phone already")
    ap.add_argument("-o", "--out", type=Path, default=Path("analysis_out/tag_ui"))
    a = ap.parse_args()
    plain = plain_copy(a.study, Path("build") / f"{study_id(a.study)}_plain_src")
    if not a.skip_load:
        for s in (a.study, plain):
            r = load(s, serial=a.serial, update_app=True, anyway=True, progress=lambda m: print(" ", m, flush=True))
            if not r.loaded:
                print(f"error: couldn't load {s}: {r.error or [c for c in r.checks]}", file=sys.stderr)
                return 1
    phone = Phone(a.serial)
    variants = [("plain", "No tags"), ("bars", "Tags in the bars")]
    for (v, label), s in zip(variants, (plain, a.study)):
        print(f"{label}: {study_id(s)}", flush=True)
        name = re.search(r"^  name: (\S+)", (s / "study.yaml").read_text(encoding="utf-8"), re.M).group(1)
        capture(phone, study_id(s), name, a.out / v)
    print(report(a.out, variants))
    return 0


if __name__ == "__main__":
    sys.exit(main())
