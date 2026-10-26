"""Android golden session (CAM-187): the real app runs a scripted session of the example study on a
phone or emulator, the session is copied back like any other, and what it recorded is checked
against python/tests/android_golden/expected.json. A change to the app that drops an event, a
file or an answer fails here, before a release.

    python scripts/android_golden.py [--serial emulator-5554] [--update] [--keep DIR]

Use an emulator or a test phone: it installs the newer app (install -r), loads a copy of the
example study (id android_golden, in a throwaway workspace: nothing reaches the real studies or
data folders) and runs the next participant through every step without the eye tracker. The phone
must be unlocked. --update saves this run's summary as the expected one (check the differences
first and say in the commit why they changed). An emulator: scripts/emulator.ps1 starts one.

What is compared (timing-dependent counts are checked as "at least" where a person's speed would
change them):
- the session's files, the steps in order (shown or skipped), the questionnaire, rating and
  recognition answers given (item ids per step), the event types recorded, and session.json's keys
- the analysis (session/analyze.py) runs on it and its quality report has no errors
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python" / "src"))

EXPECTED = ROOT / "python" / "tests" / "android_golden" / "expected.json"
STUDY_ID = "android_golden"
# events a session logs only when something happens to the phone: their absence isn't a failure
CIRCUMSTANTIAL = {"jank", "interruption", "app_background", "app_foreground", "screen_off", "screen_on"}
DONE_AFTER_S = 20       # the feed's "I'm done" button, sooner than the example's 60 s


# ---------------------------------------------------------------- the phone, as a person uses it


class Phone:
    def __init__(self, adb):
        self.adb = adb

    def nodes(self) -> list[dict]:
        for _ in range(3):
            self.adb.shell("uiautomator dump /sdcard/se_ui.xml", timeout=30)
            xml = self.adb.shell("cat /sdcard/se_ui.xml", timeout=30)
            if "<?xml" in xml:
                break
            time.sleep(1)
        xml = xml[xml.find("<?xml"):]
        out = []
        try:
            root = ET.fromstring(xml)
        except ET.ParseError:
            return out
        for n in root.iter("node"):
            b = [int(v) for v in re.findall(r"-?\d+", n.get("bounds", ""))]
            if len(b) != 4:
                continue
            out.append({"text": (n.get("text") or "").strip(), "desc": (n.get("content-desc") or "").strip(),
                        "cls": n.get("class", "").split(".")[-1], "click": n.get("clickable") == "true",
                        "enabled": n.get("enabled") == "true", "checked": n.get("checked") == "true",
                        "scroll": n.get("scrollable") == "true", "bounds": b,
                        "x": (b[0] + b[2]) // 2, "y": (b[1] + b[3]) // 2})
        return out

    @staticmethod
    def find(nodes, label, exact=True):
        hit = [n for n in nodes if label in (n["text"], n["desc"])]
        if not hit and not exact:
            hit = [n for n in nodes if label.lower() in (n["text"] + " " + n["desc"]).lower()]
        return hit

    def tap_xy(self, x, y):
        self.adb.shell(f"input tap {x} {y}")

    def tap(self, nodes, label, exact=True) -> bool:
        hit = self.find(nodes, label, exact)
        if not hit:
            return False
        n = hit[-1]
        self.tap_xy(n["x"], n["y"])
        return True

    def swipe(self, x1, y1, x2, y2, ms=400):
        self.adb.shell(f"input swipe {x1} {y1} {x2} {y2} {ms}")

    def size(self) -> tuple[int, int]:
        m = re.search(r"(\d+)x(\d+)", self.adb.shell("wm size"))
        return (int(m.group(1)), int(m.group(2))) if m else (1080, 2160)

    def wake(self) -> None:
        self.adb.shell("input keyevent KEYCODE_WAKEUP")
        self.adb.shell("settings put secure immersive_mode_confirmations confirmed")  # no "Viewing full screen" notice


def texts(nodes) -> str:
    return " | ".join(n["text"] or n["desc"] for n in nodes if n["text"] or n["desc"])


# ---------------------------------------------------------------- the study, in a throwaway workspace


def prepare(work: Path) -> Path:
    """A copy of the example study as android_golden, and settings that keep its data in `work`."""
    import yaml

    study = work / "studies" / STUDY_ID
    shutil.copytree(ROOT / "studies" / "example", study,
                    ignore=shutil.ignore_patterns("__pycache__", "make_placeholders.py", "sources.csv", "aoi_history"))
    path = study / "study.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["id"] = STUDY_ID
    data["title"] = "Android golden session"
    data["feed"]["done_button_after_s"] = DONE_AFTER_S
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    settings = work / "settings.json"
    # cleared from the phone once copied and checked, so the next run starts with an empty phone
    settings.write_text(json.dumps({"studies": {STUDY_ID: {"data_dir": str(work / "data"), "clear_after_unload": True}}}),
                        encoding="utf-8")
    os.environ["SOCIALEYES_SETTINGS"] = str(settings)
    return study


# ---------------------------------------------------------------- the session, screen by screen


CONTINUE = ("Continue", "Next", "Done", "Finish", "Submit", "OK", "Got it")


class Driver:
    """Runs a participant through every step the way a person would: reads the screen, answers
    what it asks (the middle of every scale, alternating yes and no), browses the feed (one like,
    one comments sheet) and goes on. Deterministic choices, so two runs record the same answers."""

    def __init__(self, phone: Phone, log=print):
        self.p = phone
        self.log = log
        self.w, self.h = phone.size()
        self.started = False      # Start was tapped
        self.in_session = False   # a screen of the session has been seen since
        self.liked = self.commented = False
        self.feed_since = None
        self.recog_n = 0
        self.last, self.same = "", 0

    def run(self, timeout_s: float = 900) -> None:
        end = time.time() + timeout_s
        while time.time() < end:
            nodes = self.p.nodes()
            screen = texts(nodes)
            if screen == self.last:
                self.same += 1
                if self.same >= 30:   # rating and recognition trials look alike: only a long run is stuck
                    raise RuntimeError(f"stuck on: {screen[:400]}")
            else:
                self.last, self.same = screen, 0
            if self.step(nodes, screen):
                return
            time.sleep(1.2)
        raise RuntimeError("the session didn't finish in time")

    def step(self, nodes, screen) -> bool:
        """One action on the current screen; True when the session is over."""
        p = self.p
        if "Start the next participant" in screen:
            if self.in_session:
                return True        # back on the setup screen: the session ended
            self.started = True
            self.log("start")
            p.tap(nodes, "Start the next participant", exact=False)
            return False
        self.in_session = self.in_session or self.started
        if self.started and any(k in screen for k in ("Thank you", "session is over", "Session saved")) and not p.find(nodes, "Continue"):
            return True
        if p.tap(nodes, "Start session", exact=False) or p.tap(nodes, "Continue without eye tracking"):
            return False
        if "Profile photo" in screen and p.tap(nodes, "Skip"):
            return False
        if p.find(nodes, "Home") and p.find(nodes, "Reels"):
            return self.feed(nodes)
        if self.answer(nodes, screen):
            time.sleep(.6)    # Continue turns on once the answer is in
            nodes = p.nodes()
        for label in CONTINUE:
            if p.tap(nodes, label):
                return False
        p.swipe(self.w // 2, int(self.h * .75), self.w // 2, int(self.h * .35))   # more items below
        return False

    def feed(self, nodes) -> bool:
        p = self.p
        self.feed_since = self.feed_since or time.time()
        if p.tap(nodes, "I'm done"):
            self.log("feed: I'm done")
            return False
        comment = p.find(nodes, "Comment")
        if comment and not self.liked:
            c = comment[0]
            p.tap_xy(c["x"] - (c["bounds"][2] - c["bounds"][0]) - 40, c["y"])   # Like sits left of Comment
            self.liked = True
            self.log("feed: like")
        elif comment and not self.commented:
            p.tap_xy(comment[0]["x"], comment[0]["y"])
            time.sleep(2)
            p.adb.shell("input keyevent KEYCODE_BACK")
            self.commented = True
            self.log("feed: comments sheet")
        else:
            p.swipe(self.w // 2, int(self.h * .7), self.w // 2, int(self.h * .4), 500)
        return False

    def answer(self, nodes, screen) -> bool:
        """Answers every question on the screen; True if there were any."""
        p = self.p
        answered = False
        if p.find(nodes, "Yes") and p.find(nodes, "No"):    # recognition: "did you see exactly this image?"
            self.recog_n += 1
            p.tap(nodes, "Yes" if self.recog_n % 2 else "No")
            answered = True
            time.sleep(.8)
            nodes = p.nodes()
        digits = sorted((n for n in nodes if re.fullmatch(r"\d", n["text"])), key=lambda n: (n["y"], n["x"]))
        rows: dict = {}
        for n in digits:
            rows.setdefault(n["y"] // 40, []).append(n)
        for row in rows.values():       # a scale: tap its middle point
            row.sort(key=lambda n: n["x"])
            mid = row[len(row) // 2]
            p.tap_xy(mid["x"], mid["y"])
            answered = True
        # a visual analogue scale has no node of its own: its end labels sit side by side under it
        tv = [n for n in nodes if n["text"] and n["cls"] == "TextView" and not n["text"].isdigit()]
        for a in ([] if digits else tv):
            for b in tv:
                if a is not b and abs(a["y"] - b["y"]) < 6 and a["bounds"][2] <= b["bounds"][0] + 2 \
                        and a["bounds"][0] < self.w * .2 and b["bounds"][2] > self.w * .8:
                    p.tap_xy(int(self.w * .6), a["bounds"][1] - 80)
                    answered = True
        return answered


# ---------------------------------------------------------------- what the session recorded


def summarize(session: Path) -> dict:
    """What a change to the app must not lose, independent of the participant's plan and timing."""
    from socialeyes.session.analyze import analyze_session
    from socialeyes.session.export import _responses
    from socialeyes.session.io import load_session

    s = load_session(session)
    meta = json.loads((session / "session.json").read_text(encoding="utf-8"))
    ends = s.events_of("step_end")
    resp = _responses(s)
    answers = {}
    for step_id, g in resp.groupby("step_id", sort=False):
        trials = g[g["trial"] >= 0]
        answers[step_id] = {"items": sorted(g["item_id"].astype(str).unique()),
                            "trials": int(trials["trial"].nunique()) if len(trials) else 0}
    counts = s.events["type"].value_counts()
    quality = analyze_session(session)["quality"]
    return {
        "files": sorted(p.relative_to(session).as_posix() for p in session.rglob("*") if p.is_file()),
        "session_json_keys": sorted(meta),
        "steps_shown": s.events_of("step_start")["step_id"].tolist(),
        "steps_skipped": s.events_of("step_skipped")["step_id"].tolist() if len(s.events_of("step_skipped")) else [],
        "steps_ended": [f"{r.step_id}:{r.reason}" for r in ends.itertuples()] if len(ends) else [],
        "answers": answers,
        "event_types": sorted(set(counts.index) - CIRCUMSTANTIAL),
        "at_least": {k: int(counts.get(k, 0)) for k in ("like", "comments_open", "scroll", "touch")
                     if k in counts.index},
        "completed": bool(quality.get("completed")),
    }


def compare(got: dict, want: dict) -> list[str]:
    """Differences that fail the test: anything missing or changed; counts only when they drop."""
    out = []
    for key, w in want.items():
        g = got.get(key)
        if key == "event_types":    # a new kind of event is reported, not failed
            out += [f"event_types: missing {sorted(set(w) - set(g))}"] if set(w) - set(g) else []
            if set(g) - set(w):
                print(f"note: new event types {sorted(set(g) - set(w))} (--update to expect them)")
        elif key == "at_least":
            out += [f"at_least.{k}: {g.get(k, 0)} < {n}" for k, n in w.items() if (g or {}).get(k, 0) < n]
        elif g != w:
            if isinstance(w, list) and isinstance(g, list):
                out.append(f"{key}: missing {sorted(set(w) - set(g))}, new {sorted(set(g) - set(w))}"
                           if set(w) != set(g) else f"{key}: order changed")
            else:
                out.append(f"{key}: expected {json.dumps(w)[:300]}, got {json.dumps(g)[:300]}")
    return out


# ---------------------------------------------------------------- the run


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--serial", help="the phone or emulator (adb devices); needed when more than one is connected")
    ap.add_argument("--update", action="store_true", help="save this run's summary as the expected one")
    ap.add_argument("--keep", help="keep the workspace (study, session, summary) in this folder")
    args = ap.parse_args(argv)

    from socialeyes.phone import loader, unload
    from socialeyes.phone.adb import Adb

    work = Path(args.keep) if args.keep else Path(tempfile.mkdtemp(prefix="socialeyes-golden-"))
    if args.keep and work.exists() and any(work.iterdir()):
        print(f"error: {work} isn't empty", file=sys.stderr)
        return 2
    work.mkdir(parents=True, exist_ok=True)
    analysis = ROOT / "analysis_out" / STUDY_ID
    had_analysis = analysis.exists()
    try:
        study = prepare(work)
        print("Loading the study (and the app, if it's newer)…")
        r = loader.load(study, serial=args.serial, update_app=True, anyway=True, progress=lambda s: print(" ", s))
        if r.error or loader.blocked(r.checks):
            print(f"error: couldn't load: {r.error or [c.text for c in r.checks if c.level == 'block']}", file=sys.stderr)
            return 1
        adb = Adb(args.serial)
        adb.choose()
        phone = Phone(adb)
        phone.wake()
        adb.shell("am force-stop org.socialeyes.pictogram")
        adb.shell("monkey -p org.socialeyes.pictogram -c android.intent.category.LAUNCHER 1")
        time.sleep(3)
        print("Running the session (a few minutes)…")
        Driver(phone, log=lambda s: print(" ", s)).run()
        print("Copying it from the phone…")
        u = unload.unload(study, serial=args.serial, progress=lambda s: print(" ", s))
        copied = [s for s in u.sessions if s.copied]
        if u.error or len(copied) != 1:
            print(f"error: unloading: {u.error or [vars(s) for s in u.sessions]}", file=sys.stderr)
            return 1
        session = work / "data" / copied[0].participant_id / copied[0].session_uid
        got = summarize(session)
        text = json.dumps(got, indent=2) + "\n"
        (work / "summary.json").write_text(text, encoding="utf-8")
        if args.update:
            EXPECTED.parent.mkdir(parents=True, exist_ok=True)
            EXPECTED.write_text(text, encoding="utf-8")
            print(f"Saved {EXPECTED.relative_to(ROOT)}: check its diff before committing.")
            return 0
        if not EXPECTED.is_file():
            print(f"error: no {EXPECTED.relative_to(ROOT)} yet: run with --update first", file=sys.stderr)
            return 1
        diff = compare(got, json.loads(EXPECTED.read_text(encoding="utf-8")))
        for d in diff:
            print(f"FAIL {d}")
        print("PASS: the session recorded everything expected." if not diff else f"{len(diff)} difference(s).")
        return 1 if diff else 0
    finally:
        if not had_analysis:
            shutil.rmtree(analysis, ignore_errors=True)   # the unload's analysis of this throwaway study
        if not args.keep:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
