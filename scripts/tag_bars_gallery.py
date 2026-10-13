"""CAM-165: a report on the on-screen tag options: how each looks in the app and how well the Neon reads it.

    python scripts/tag_bars_gallery.py SHOTS_DIR TAG_BARS_SESSION [--results BARS_SUMMARY_CSV]
        [--test LABEL NEON_DIR SESSION_DIR BARS_SUMMARY_CSV ...] [--plain LABEL BARS_SUMMARY_CSV ...]
        [--notes NOTES_FILE] [--chosen VARIANT] [-o OUT_HTML]

SHOTS_DIR holds phone screenshots: bars_v<k>.png for the k-th variant of the tag_bars step (in
study order: the first hold shows them in that order), and optionally plain_feed.png (the feed
without tags) and old_feed_bands_12mm.png (markers.on_screen: 12 mm tag36h11 bands above and
below the feed). TAG_BARS_SESSION is any tag_bars session (even one run without the glasses): its
marker_layout events give each variant's bar heights and the feed space left.

--test (repeatable) adds a tag_bars recording: a label, its Neon folder, its session folder and
bars_summary.csv from `python -m socialeyes.gaze.ladder`. Each gets a chart (detection_by_distance_<n>.png
next to the page) and a column in the results and settings tables, with its screen brightness, scene
camera setting and frame rate read from the recording. --plain gives the same recording analysed with
`--plain` (no smart detection): its chart then shows what smart detection adds. --results is the
bars_summary.csv whose read rates go under the screenshots (default: the first --test's). --notes is a
text file of extra findings, one per line (HTML allowed), listed in the summary.

Feed space is the height between the bars, compared with the plain feed's (sync strip + 52 dp top
bar, 50 dp tab bar).
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1] / "python" / "src"))
from socialeyes.markers import tag_image  # noqa: E402

# The tag_bars study's holds, in recording order, with the median distance measured in run 1 (12 Oct).
HOLDS = ["normal (36 cm)", "arm's length (53 cm)", "lap (37 cm)"]
HOLD_COLOURS = ["#2e7d32", "#1565c0", "#ef6c00"]
FAMILY_CELLS = {"tag36h11": 8, "tag25h9": 7, "tag16h5": 6}  # cells across, black border included
GOOD, FAIR = 0.85, 0.5

GLOSSARY = """
<dl class="glossary">
 <dt>36h11, 25h9, 16h5</dt>
 <dd>The AprilTag family: which set of codes the tags come from. The first number is how many black/white
 data squares the code has (36 = a 6 × 6 grid, 25 = 5 × 5, 16 = 4 × 4). The number after the "h" is how
 many of those squares must be misread before one tag can be mistaken for another (11, 9, 5).
 With fewer squares, each square is bigger on a tag of the same size, so the camera can read it from
 farther away; the cost is fewer different tags (587, 35, 30) and more chance of a false read. That is
 why 16h5 reads are only accepted when every square is right.</dd>
 <dt>10 mm</dt>
 <dd>The tag's width on the phone screen, outer edge of the black border to outer edge. Around it is a
 white margin one square wide, which the camera needs to find the tag. What matters for reading is the
 size of one square: 36h11 14 mm, 25h9 12 mm and 16h5 10 mm all have squares of about 1.7 mm.</dd>
 <dt>grey 40%</dt>
 <dd>The tag's black is drawn as a 40% grey instead, to make it less noticeable. Without it, the black is full black.</dd>
 <dt>feed −4.5%</dt>
 <dd>How much less room the feed has than the plain app, because the top bar and tab bar grow to fit
 the tags (they're 84 dp and 50 dp without tags).</dd>
 <dt>Normal, lap, arm's length</dt>
 <dd>How the wearer was asked to hold the phone. The distance in brackets is the median distance from
 the glasses to the phone measured in that recording.</dd>
 <dt>Top + bottom read</dt>
 <dd>The share of scene-camera frames in which at least one tag in the top bar and one in the tab bar
 were read. Tracking the phone well needs both. 85% or more counts as good.</dd>
 <dt>Smart detection</dt>
 <dd>A second, closer look at each spot where a tag should be (predicted from where the phone was a moment
 before) when the search of the whole frame missed it.</dd>
</dl>
"""

PLANNED_TESTS = [
    "<b>Exposure × brightness grid.</b> The app sets each combination itself through Companion's API "
    "(no laptop): screen 0.30, 0.45 and 0.60 × scene camera auto, auto biased darker, manual 1000 µs and "
    "manual 2000 µs. Held normally and at arm's length.",
    "<b>Frame rate check.</b> Whether a manual exposure drops the scene video to 10 fps (run 2 did, from the "
    "moment the calibration set 2000 µs, and never recovered) or whether that was the phone throttling.",
    "<b>Two rooms.</b> The best two settings again in a bright room (window, overhead lights) and a dim one: "
    "the screen lights itself, so a fixed exposure should not depend on the room, but glare can.",
    "<b>Real feed.</b> One feed session with the chosen settings fixed in the study (display.brightness, "
    "neon.scene_exposure): read rates while scrolling, stories, reels and comments.",
]


# ---------------------------------------------------------------- data

def bar_layouts(session: Path) -> list[dict]:
    """Each variant's bars, in the order the first hold showed them (= study order)."""
    seen, out = set(), []
    for line in (session / "events.jsonl").read_text(encoding="utf-8").splitlines():
        e = json.loads(line)
        bars = (e.get("ladder") or {}).get("bars") if e.get("type") == "marker_layout" else None
        if bars and bars["variant"] not in seen:
            seen.add(bars["variant"])
            out.append(bars)
    return out


def plain_feed_px(session: Path) -> float:
    """The plain feed's height between its bars, from the session's screen and sync strip."""
    meta = json.loads((session / "session.json").read_text(encoding="utf-8"))
    d = meta["device"]
    dp = d["density_dpi"] / 160
    sync_dp = 16  # the sync patch strip (display.sync_patch: 16 dp + 16) above a 52 dp top bar
    return d["screen_height_px"] - (max(24, sync_dp + 16) + 52 + 50.5) * dp


@dataclass
class TestRun:
    """A tag_bars recording and the screen/camera settings it ran with."""
    label: str
    summary: pd.DataFrame        # bars_summary.csv
    screen: str
    camera: str
    fps: float
    distance_cm: dict            # hold -> median distance
    started: str = ""
    plain: pd.DataFrame | None = None   # the same recording analysed without smart detection

    def rate(self, variant: str, hold: int, plain: bool = False) -> float:
        df = self.plain if plain else self.summary
        if df is None:
            return float("nan")
        r = df[(df["variant"] == variant) & (df["hold"] == hold)]["top_and_bottom"]
        return float(r.iloc[0]) if len(r) else float("nan")

    def holds(self) -> list[int]:
        """Holds nearest first."""
        return sorted((int(h) for h in self.summary["hold"].unique()), key=lambda h: self.distance_cm.get(h, _hold_cm(h)))

    def hold_name(self, h: int) -> str:
        base = _hold_label(h).split(" (")[0]
        return f"{base} ({self.distance_cm[h]:.0f} cm)" if h in self.distance_cm else _hold_label(h)


def load_test(label: str, neon: Path, session: Path, summary_csv: Path) -> TestRun:
    """Settings in force during the tag_bars step, from the session log and the Neon recording."""
    events = [json.loads(line) for line in (session / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    bars = [e for e in events if e.get("type") == "step_start" and e.get("step_type") == "tag_bars"]
    t0 = bars[0]["t_ns"] if bars else events[-1]["t_ns"]
    end = next((e["t_ns"] for e in events if e.get("type") == "step_end" and bars and e.get("step_id") == bars[0]["step_id"]),
               events[-1]["t_ns"])
    before = [e for e in events if e["t_ns"] <= t0]
    window = [e for e in before if e.get("type") == "display_setting" and e.get("brightness") is not None]
    if window:
        how = {"display_calibration_result": "chosen by the laptop's display calibration"}.get(
            window[-1].get("source"), "set by the study")
        screen = f"{window[-1]['brightness']:.2f}, {how}"
    else:
        system = [e["value"] for e in events if e.get("type") == "brightness" and e["t_ns"] <= end]
        lo, hi = min(system, default=float("nan")), max(system, default=float("nan"))
        screen = f"phone's own setting, {lo:.2f}" + (f"–{hi:.2f} (auto-brightness)" if hi - lo > 0.01 else "")
    cams = [e["camera"] for e in before if e.get("type") == "neon" and e.get("status") == "scene_camera_set"]
    cam = cams[-1] if cams else None
    camera = ("Companion's own setting (the app didn't change it)" if cam is None else
              f"manual {cam.get('man_exp')} µs" if cam.get("ae_mode") == "manual" else "auto")
    t = np.fromfile(neon / "Neon Scene Camera v1 ps1.time", "<i8")
    meta = json.loads((session / "session.json").read_text(encoding="utf-8"))
    off = int(meta["clock"]["wall_ms"]) * 1_000_000 - int(meta["clock"]["elapsed_ns"])
    sel = t[(t >= t0 + off) & (t <= end + off)]
    fps = 1e9 / float(np.median(np.diff(sel))) if len(sel) > 2 else float("nan")
    obs_csv = summary_csv.parent / "ladder_observations.csv"
    dist = {}
    if obs_csv.is_file():
        obs = pd.read_csv(obs_csv, usecols=["hold", "distance_mm"])
        dist = {int(h): d for h, d in (obs.groupby("hold")["distance_mm"].median() / 10).round().items()}
    started = meta.get("started_wall", "")
    try:
        when = dt.datetime.fromisoformat(started)
        started = f"{when.day} {when:%b %Y, %H:%M}"
    except ValueError:
        pass
    return TestRun(label, pd.read_csv(summary_csv), screen, camera, fps, dist, started)


def _hold_label(h: int) -> str:
    return HOLDS[h] if h < len(HOLDS) else f"hold {h}"


def _hold_cm(h: int) -> float:
    label = _hold_label(h)
    return float(label.split("(")[1].split()[0]) if "(" in label else 1e9 + h


def _cls(rate: float) -> str:
    return "good" if rate >= GOOD else "fair" if rate >= FAIR else "poor"


def _pct(rate: float) -> str:
    return "–" if not np.isfinite(rate) else f"{rate:.0%}"


# ---------------------------------------------------------------- figures

def tag_thumbnail(family: str, size_mm: float, grey: float, px_per_mm: float = 4.0) -> np.ndarray:
    """A tag of the variant's family, drawn at its size (px_per_mm) and grey level, with a 1-cell margin."""
    cells = FAMILY_CELLS[family]
    ppc = max(1, round(size_mm * px_per_mm / cells))
    img = tag_image(0, px_per_cell=ppc, quiet_cells=1, family=family)
    return np.where(img < 128, round(grey * 255), 255).astype(np.uint8)


def chart(run: TestRun, feed_lost: dict[str, float], chosen: str | None, out: Path) -> None:
    """Grouped bars: one group per variant (most feed space lost first), one bar per hold, nearest
    hold first, with a picture of each variant's tag (to scale) under its name. With run.plain (the
    same recording without smart detection) each bar is that read rate, extended in a lighter,
    hatched shade up to the rate with smart detection."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.offsetbox import AnnotationBbox, OffsetImage
    from matplotlib.patches import Patch

    results = run.summary
    variants = sorted(results["variant"].unique(), key=lambda v: (-feed_lost.get(v, 0), v))
    holds = run.holds()
    x, w = np.arange(len(variants)), 0.8 / len(holds)
    fig, ax = plt.subplots(figsize=(11.5, 6.6))
    fig.subplots_adjust(left=0.07, right=0.93, top=0.9, bottom=0.32)
    ax.grid(axis="y", color="#e6e6e6", lw=0.8)
    ax.set_axisbelow(True)
    handles = []
    for i, h in enumerate(holds):
        colour = HOLD_COLOURS[h % len(HOLD_COLOURS)]
        xs = x + (i - (len(holds) - 1) / 2) * w
        smart = np.array([run.rate(v, h) * 100 for v in variants])
        base = smart if run.plain is None else np.array([run.rate(v, h, plain=True) * 100 for v in variants])
        ax.bar(xs, base, w * 0.92, color=colour)
        if run.plain is not None:
            gain = np.clip(smart - base, 0, None)
            ax.bar(xs, gain, w * 0.92, bottom=base, facecolor=colour, alpha=0.3, hatch="////", edgecolor=colour, lw=0)
        for xi, b, s_ in zip(xs, base, smart):
            if np.isfinite(s_):
                ax.text(xi, max(b, s_) + 1, f"{s_:.0f}", ha="center", va="bottom", fontsize=9)
                if run.plain is not None and s_ - b >= 7:
                    ax.text(xi, (b + s_) / 2, f"+{s_ - b:.0f}", ha="center", va="center", fontsize=7.5,
                            color="black", fontweight="bold", rotation=90)
        handles.append(Patch(color=colour, label=run.hold_name(h).capitalize()))
    if run.plain is not None:
        handles.append(Patch(facecolor="#bbbbbb", alpha=0.6, edgecolor="#555", hatch="////",
                             label="extra frames read with smart detection"))
    ax.axhline(GOOD * 100, color="#888", ls="--", lw=1)
    ax.text(1.005, GOOD * 100, f"{GOOD:.0%}\n= good", color="#666", ha="left", va="center", fontsize=9,
            transform=ax.get_yaxis_transform())
    ax.set_xlim(-0.6, len(variants) - 0.4)
    ax.set_ylim(0, 108)
    ax.set_yticks(range(0, 101, 20))
    ax.set_ylabel("Frames with a top AND a bottom tag read (%)", fontsize=11)
    names = [v.replace(" grey", "\ngrey") for v in variants]  # keep long names from running into the next
    ax.set_xticks(x, [f"{n}\nfeed −{feed_lost[v]:.1f}%" if v in feed_lost else n for n, v in zip(names, variants)],
                  fontsize=10)
    for label, v in zip(ax.get_xticklabels(), variants):
        if v == chosen:
            label.set_fontweight("bold")
    for xi, v in zip(x, variants):
        r = results[results["variant"] == v].iloc[0]
        thumb = tag_thumbnail(r["family"], float(r["size_mm"]), float(r["grey"]), px_per_mm=4.5)
        ax.add_artist(AnnotationBbox(OffsetImage(np.dstack([thumb] * 3), zoom=1.0), (xi, -0.18),
                                     xycoords=("data", "axes fraction"), box_alignment=(0.5, 1), frameon=True, pad=0,
                                     bboxprops={"edgecolor": "#c8c8c8", "linewidth": 0.8},
                                     annotation_clip=False))
    fig.text(0.5, 0.015, "Tags drawn to scale (the same scale for all); the grey outline marks the white margin "
             "each tag needs.", ha="center", fontsize=9, color="#666")
    ax.legend(handles=handles, loc="lower center", bbox_to_anchor=(0.5, 1.0), ncols=len(handles), frameon=False,
              fontsize=10)
    ax.spines[["top", "right"]].set_visible(False)
    fig.savefig(out, dpi=150)
    plt.close(fig)


# ---------------------------------------------------------------- report sections

def section(num: str, anchor: str, title: str, body: str) -> str:
    return f'<section id="{anchor}"><h2><span class="num">{num}</span>{html.escape(title)}</h2>{body}</section>'


def summary_section(runs: list[TestRun], feed_lost: dict, chosen: str | None, thumb: str, notes: list[str]) -> str:
    if not runs:
        return "<p class='todo'>No recordings yet.</p>"
    out = []
    if chosen:
        rows = "".join(
            f"<tr><th>{html.escape(r.label)}</th>"
            + "".join(f"<td><span class='{_cls(r.rate(chosen, h))}'>{_pct(r.rate(chosen, h))}</span>"
                      + (f"<span class='was'> from {_pct(r.rate(chosen, h, True))}</span>"
                         if r.plain is not None and r.rate(chosen, h) - r.rate(chosen, h, True) >= 0.02 else "")
                      + f"<div class='sub'>{html.escape(r.hold_name(h))}</div></td>" for h in r.holds())
            + "</tr>" for r in runs)
        out.append(f"""
<div class="decision">
 <img src="{thumb}" alt="{html.escape(chosen)}">
 <div>
  <div class="label">Chosen tag</div>
  <div class="big">AprilTag {html.escape(chosen)}, black</div>
  <p>In the four corners of the app's top bar and tab bar. It costs {feed_lost.get(chosen, float('nan')):.1f}% of the
  feed's height, less than half of what tags of the same readability in the 36h11 family cost
  ({feed_lost.get('36h11 14 mm', float('nan')):.1f}% for 36h11 14 mm).</p>
  <table class="key"><tr><th></th><th colspan="3">Frames with a top and a bottom tag read (smart detection; from = without)</th></tr>{rows}</table>
 </div>
</div>""")
    found, parts = [], []
    for r in runs:
        ok = [v for v in r.summary["variant"].unique() if all(r.rate(v, h) >= GOOD for h in r.holds())]
        ok.sort(key=lambda v: feed_lost.get(v, 0))
        parts.append(f"{html.escape(r.label)}: " + (", ".join(html.escape(v) for v in ok) if ok else "none"))
    found.append(f"<b>Options read well (≥ {GOOD:.0%}) at every distance.</b> " + "; ".join(parts) + ".")
    parts = []
    for r in runs:
        if r.plain is None:
            continue
        gains = [(r.rate(v, h) - r.rate(v, h, True), v, h) for v in r.summary["variant"].unique() for h in r.holds()]
        gains = [g for g in gains if np.isfinite(g[0])]
        if gains:
            g, v, h = max(gains)
            parts.append(f"{html.escape(r.label)}: {np.mean([x[0] for x in gains]) * 100:+.0f} points on average, "
                         f"at most {g * 100:+.0f} ({html.escape(v)}, {html.escape(r.hold_name(h).split(' (')[0])})")
    if parts:
        found.append("<b>Smart detection</b> helps most where reading is hard. " + "; ".join(parts) + ".")
    found += notes
    out.append("<h3>Findings</h3><ul class='findings'>" + "".join(f"<li>{f}</li>" for f in found) + "</ul>")
    return "".join(out)


def method_section(runs: list[TestRun]) -> str:
    return f"""
<p>The app's <code>tag_bars</code> study step shows the feed with each tag option fitted into its top bar and tab
bar, one option at a time for 4 seconds, every option twice per hold (forwards, then backwards). The wearer
held the phone three ways in turn: normally, at arm's length and low near the lap. The Neon glasses
recorded the scene camera throughout; afterwards every scene frame is searched for the tags on screen at that
moment (<code>python -m socialeyes.gaze.ladder</code>), once with the whole-frame search only and once with smart
detection added.</p>
<p>The measure is the share of frames in which at least one top tag and one bottom tag were read: with both,
the phone's position can be worked out precisely; frames without either are bridged by optical flow for a short
while only. Every frame with reads also had to give a consistent phone pose (corners within 2 px), which they
all did, so the extra reads from smart detection are real.</p>
<h3>Reading the names</h3>
{GLOSSARY}"""


def results_section(runs: list[TestRun], figures: list[str], variants: list[str], chosen: str | None,
                    feed_lost: dict) -> str:
    out = []
    for k, (r, fig) in enumerate(zip(runs, figures), start=1):
        out.append(f"""<figure class="chart"><a href="{fig}"><img src="{fig}" alt="Figure {k}"></a>
<figcaption><b>Figure {k}. {html.escape(r.label)}.</b> Share of frames with a top and a bottom tag read, per tag
option and way of holding the phone. Screen: {html.escape(r.screen)}. Scene camera: {html.escape(r.camera)},
{r.fps:.0f} fps.{' The hatched part of each bar is what smart detection adds.' if r.plain is not None else ''}</figcaption></figure>""")
    if runs:
        head = "".join(f"<th colspan='{len(r.holds())}' class='run'>{html.escape(r.label)}</th>" for r in runs)
        sub = "".join(f"<th class='sub'>{html.escape(r.hold_name(h))}</th>" for r in runs for h in r.holds())
        rows = []
        for v in variants:
            name = f"<b>{html.escape(v)}</b>" if v == chosen else html.escape(v)
            cells = "".join(f"<td class='{_cls(r.rate(v, h))}'>{_pct(r.rate(v, h))}</td>" for r in runs for h in r.holds())
            rows.append(f"<tr{' class=chosen-row' if v == chosen else ''}><th>{name}</th>"
                        f"<td class='num'>−{feed_lost.get(v, float('nan')):.1f}%</td>{cells}</tr>")
        out.append(f"""<table class="data"><caption><b>Table 1.</b> Frames with a top and a bottom tag read
(smart detection), every option and recording. Green ≥ {GOOD:.0%}, amber ≥ {FAIR:.0%}.</caption>
<tr><th rowspan="2">Tag option</th><th rowspan="2">Feed</th>{head}</tr><tr>{sub}</tr>{''.join(rows)}</table>""")
    return "".join(out)


def tests_section(runs: list[TestRun]) -> str:
    head = "".join(f"<th>{html.escape(r.label)}</th>" for r in runs)
    setting = lambda name, f: f"<tr><th>{name}</th>" + "".join(f"<td>{html.escape(f(r))}</td>" for r in runs) + "</tr>"  # noqa: E731
    rows = [setting("Recorded", lambda r: r.started),
            setting("Screen brightness", lambda r: r.screen),
            setting("Scene camera exposure", lambda r: r.camera),
            setting("Scene video", lambda r: f"{r.fps:.0f} fps"),
            setting("Distances (median)", lambda r: ", ".join(r.hold_name(h) for h in r.holds())),
            setting("Smart detection compared", lambda r: "yes" if r.plain is not None else "no")]
    planned = "".join(f"<li>{t}</li>" for t in PLANNED_TESTS)
    return f"""
<h3>Done</h3>
<table class="data settings"><caption><b>Table 2.</b> The recordings and the settings they ran with (read from
each recording).</caption><tr><th></th>{head}</tr>{''.join(rows)}</table>
<h3>Still to test: the scene camera exposure and the screen brightness</h3>
<p>All run on the phone and glasses alone (the laptop only loads the study and unloads the data), with the
chosen tags in the bars. For each setting: tags read at each distance, how much of the post image is blown out in
the scene video, and the scene video's frame rate.</p>
<ol class="planned">{planned}</ol>"""


def card(img: str, title: str, lines: list[str], table: str = "", chosen: bool = False) -> str:
    body = "".join(f"<p>{html.escape(t)}</p>" for t in lines)
    badge = ' <span class="badge">chosen</span>' if chosen else ""
    return (f'<figure class="shot{" chosen-card" if chosen else ""}"><a href="{img}"><img src="{img}" alt="{html.escape(title)}"></a>'
            f"<figcaption><h4>{html.escape(title)}{badge}</h4>{body}{table}</figcaption></figure>")


def rates_table(rows: pd.DataFrame) -> str:
    if rows.empty:
        return '<p class="todo">Read rates: not recorded yet.</p>'
    cells = "".join(
        f"<tr><td>{_hold_label(int(r.hold)).split(' (')[0]}</td><td class='{_cls(r.top_and_bottom)}'>"
        f"{r.top_and_bottom:.0%}</td></tr>"
        for r in sorted(rows.itertuples(), key=lambda r: _hold_cm(int(r.hold))))
    return "<table class='mini'><tr><th></th><th>top + bottom read</th></tr>" + cells + "</table>"


CSS = """
 :root { --ink: #1d2433; --muted: #5b6475; --rule: #dde1e8; --accent: #0a6b3a; --bg-soft: #f6f7f9; }
 * { box-sizing: border-box; }
 body { font: 15px/1.55 -apple-system, "Segoe UI", system-ui, sans-serif; color: var(--ink); margin: 0; background: #fff; }
 .page { max-width: 1120px; margin: 0 auto; padding: 40px 48px 80px; }
 header.title { border-bottom: 3px solid var(--ink); padding-bottom: 18px; margin-bottom: 8px; }
 header .kicker { text-transform: uppercase; letter-spacing: .08em; font-size: 12px; color: var(--muted); }
 h1 { font: 600 30px/1.2 Georgia, "Times New Roman", serif; margin: 6px 0 10px; }
 header .meta { color: var(--muted); font-size: 13px; }
 nav.toc { background: var(--bg-soft); border: 1px solid var(--rule); border-radius: 6px; padding: 12px 18px; margin: 22px 0 8px; font-size: 14px; }
 nav.toc b { display: block; margin-bottom: 4px; }
 nav.toc ul { margin: 0; padding: 0; list-style: none; columns: 2; }
 nav.toc .num { display: inline-block; width: 22px; color: var(--muted); }
 nav.toc a { color: var(--ink); text-decoration: none; } nav.toc a:hover { text-decoration: underline; }
 section { margin-top: 38px; }
 h2 { font: 600 22px/1.3 Georgia, "Times New Roman", serif; border-bottom: 1px solid var(--rule); padding-bottom: 6px; margin: 0 0 14px; }
 h2 .num { color: var(--muted); margin-right: 10px; }
 h3 { font-size: 16px; margin: 24px 0 8px; }
 h4 { font-size: 14px; margin: 8px 0 4px; }
 p { margin: 6px 0 10px; max-width: 860px; }
 code { font-size: 13px; background: var(--bg-soft); padding: 1px 4px; border-radius: 3px; }
 .decision { display: flex; gap: 22px; align-items: flex-start; border: 1px solid var(--rule); border-left: 5px solid var(--accent);
             background: #f3faf6; border-radius: 6px; padding: 18px 20px; }
 .decision img { width: 92px; border: 1px solid #c8c8c8; background: #fff; image-rendering: pixelated; flex: none; }
 .decision .label { text-transform: uppercase; letter-spacing: .08em; font-size: 11px; color: var(--accent); font-weight: 700; }
 .decision .big { font: 600 21px/1.3 Georgia, serif; margin: 2px 0 6px; }
 table { border-collapse: collapse; }
 table.key { margin-top: 10px; font-size: 14px; }
 table.key th, table.key td { padding: 4px 14px 4px 0; text-align: left; vertical-align: top; }
 table.key td span:first-child { font-size: 17px; font-weight: 700; }
 .was { color: var(--muted); font-size: 12px; } .sub { color: var(--muted); font-size: 12px; font-weight: 400; }
 ul.findings li { margin: 5px 0; max-width: 900px; }
 dl.glossary { display: grid; grid-template-columns: 190px 1fr; gap: 6px 18px; max-width: 980px; }
 dl.glossary dt { font-weight: 600; } dl.glossary dd { margin: 0; color: #333; }
 figure.chart { margin: 18px 0 28px; }
 figure.chart img { width: 100%; border: 1px solid var(--rule); border-radius: 4px; }
 figcaption { font-size: 13px; color: var(--muted); margin-top: 6px; max-width: 980px; }
 figcaption b { color: var(--ink); }
 table.data { font-size: 13.5px; margin: 10px 0 24px; width: 100%; }
 table.data caption { caption-side: top; text-align: left; font-size: 13px; color: var(--muted); padding-bottom: 8px; }
 table.data caption b { color: var(--ink); }
 table.data th, table.data td { border-bottom: 1px solid var(--rule); padding: 6px 8px; text-align: left; }
 table.data th.run { text-align: center; border-bottom: 2px solid var(--ink); }
 table.data td { text-align: center; } table.data td.num { color: var(--muted); }
 table.data tr.chosen-row { background: #f3faf6; }
 table.settings td { text-align: left; vertical-align: top; }
 .good { color: #0a6b3a; font-weight: 700; } .fair { color: #a66a00; font-weight: 600; } .poor { color: #b3261e; }
 ol.planned li { margin: 6px 0; max-width: 900px; }
 .shots { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 18px; }
 figure.shot { margin: 0; border: 1px solid var(--rule); border-radius: 6px; padding: 10px; background: var(--bg-soft); }
 figure.shot img { width: 100%; border: 1px solid #ccc; border-radius: 4px; }
 figure.shot p { font-size: 12.5px; margin: 2px 0; }
 figure.chosen-card { border: 2px solid var(--accent); }
 .badge { background: var(--accent); color: #fff; border-radius: 3px; padding: 0 5px; font-size: 11px; vertical-align: 2px; }
 table.mini { font-size: 12.5px; margin-top: 6px; width: 100%; }
 table.mini td, table.mini th { border-bottom: 1px solid var(--rule); padding: 2px 4px; text-align: left; }
 .todo { color: #888; font-style: italic; }
 @media print { .page { padding: 0; } nav.toc { display: none; } section { break-inside: avoid-page; }
                figure.chart, table.data { break-inside: avoid; } a { color: inherit; text-decoration: none; } }
"""


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("shots", type=Path)
    p.add_argument("session", type=Path, help="a tag_bars session folder")
    p.add_argument("--results", type=Path, help="bars_summary.csv for the read rates under the screenshots")
    p.add_argument("--test", nargs=4, action="append", default=[], metavar=("LABEL", "NEON", "SESSION", "SUMMARY"),
                   help="a tag_bars recording: label, Neon folder, session folder, bars_summary.csv")
    p.add_argument("--plain", nargs=2, action="append", default=[], metavar=("LABEL", "SUMMARY"),
                   help="bars_summary.csv of a --test recording analysed with --plain: its chart shows "
                        "what smart detection adds")
    p.add_argument("--notes", type=Path, help="extra findings for the summary, one per line (HTML allowed)")
    p.add_argument("--chosen", default="16h5 10 mm", help="the variant to highlight (default: %(default)s)")
    p.add_argument("-o", "--out", type=Path)
    args = p.parse_args(argv)
    out = args.out or args.shots.parent / "index.html"
    plain = plain_feed_px(args.session)
    rel = lambda path: Path(os.path.relpath(path, out.parent)).as_posix()  # noqa: E731

    layouts = bar_layouts(args.session)
    feed_lost = {b["variant"]: (1 - float(b["feed_px"]) / plain) * 100 for b in layouts}
    variants = sorted(feed_lost, key=lambda v: (-feed_lost[v], v))
    chosen = args.chosen if args.chosen in feed_lost else None

    runs = [load_test(label, Path(n), Path(s), Path(c)) for label, n, s, c in args.test]
    plains = {label: pd.read_csv(c) for label, c in args.plain}
    figures = []
    for k, run in enumerate(runs, start=1):
        run.plain = plains.get(run.label)
        png = out.parent / f"detection_by_distance_{k}.png"
        chart(run, feed_lost, chosen, png)
        figures.append(rel(png))
    results = (pd.read_csv(args.results) if args.results else runs[0].summary if runs
               else pd.DataFrame(columns=["variant"]))

    thumb = ""
    if chosen and len(results):
        r = results[results["variant"] == chosen]
        if len(r):
            png = out.parent / "chosen_tag.png"
            cv2.imwrite(str(png), tag_thumbnail(r.iloc[0]["family"], float(r.iloc[0]["size_mm"]), float(r.iloc[0]["grey"]), 12))
            thumb = rel(png)
    notes = [line.strip() for line in args.notes.read_text(encoding="utf-8").splitlines()
             if line.strip()] if args.notes else []

    cards = []
    if (args.shots / "plain_feed.png").is_file():
        cards.append(card(rel(args.shots / "plain_feed.png"), "Plain feed (no tags)",
                          [f"Feed space: {plain:.0f} px (the baseline).", "No phone tracking from the screen."]))
    if (args.shots / "old_feed_bands_12mm.png").is_file():
        cell = 12 / 8 * 395.8 / 25.4  # px per cell of a 12 mm tag36h11 tag
        band = 10 * cell + 2 * 395.8 / 25.4  # tag + 1-cell quiet zone each side, 2 mm from the edge
        feed = plain - 2 * band
        cards.append(card(rel(args.shots / "old_feed_bands_12mm.png"), "Used so far: 36h11 12 mm in bands",
                          [f"Feed space: {feed:.0f} px ({feed / plain - 1:+.0%}).",
                           "Accuracy check, 12 Oct: tags read in 100% of feed frames, 90–100% during validation."]))
    bar_cards = []
    for k, bars in enumerate(layouts):
        img = args.shots / f"bars_v{k}.png"
        if not img.is_file():
            print(f"missing {img.name} ({bars['variant']})", file=sys.stderr)
            continue
        v, feed = bars["variant"], float(bars["feed_px"])
        bar_cards.append((-feed_lost[v], card(
            rel(img), v,
            [f"Feed space: {feed:.0f} px ({feed / plain - 1:+.1%}).",
             f"Top bar {bars['top_bar_dp']:.0f} dp, tab bar {bars['tab_bar_dp']:.0f} dp (normally 84 and 50)."],
            rates_table(results[results["variant"] == v]) if len(results) else "", chosen=v == args.chosen)))
    cards += [c for _, c in sorted(bar_cards, key=lambda t: t[0])]

    sections = [
        ("1", "summary", "Summary", summary_section(runs, feed_lost, chosen, thumb, notes)),
        ("2", "method", "What was tested", method_section(runs)),
        ("3", "results", "Results", results_section(runs, figures, variants, chosen, feed_lost)),
        ("4", "tests", "Tests", tests_section(runs) if runs else "<p class='todo'>No recordings yet.</p>"),
        ("A", "screenshots", "Appendix: the layouts on the phone",
         "<p>Phone screenshots (Motorola Edge 40 Pro), from most to least feed space lost. Read rates under each "
         f"are from {html.escape(runs[0].label) if runs and not args.results else 'the --results recording'}.</p>"
         f"<div class='shots'>{''.join(cards)}</div>"),
    ]
    toc = "".join(f'<li><span class="num">{n}</span><a href="#{a}">{html.escape(t)}</a></li>' for n, a, t, _ in sections)
    recordings = "; ".join(f"{html.escape(r.label)} ({html.escape(r.started)})" for r in runs) or "none yet"
    page = f"""<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>On-screen tags for phone tracking: test report</title>
<style>{CSS}</style>
<div class="page">
<header class="title">
 <div class="kicker">SocialEyes · Test report · CAM-165</div>
 <h1>On-screen tags for phone tracking: how they look vs. how well the glasses read them</h1>
 <div class="meta">Report generated {dt.date.today().day} {dt.date.today():%b %Y} · Motorola Edge 40 Pro with Pupil Labs Neon ·
 Recordings: {recordings}</div>
</header>
<nav class="toc"><b>Contents</b><ul>{toc}</ul></nav>
{''.join(section(n, a, t, b) for n, a, t, b in sections)}
</div>
</html>
"""
    out.write_text(page, encoding="utf-8")
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
