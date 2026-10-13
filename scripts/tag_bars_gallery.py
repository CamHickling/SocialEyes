"""CAM-165: a page comparing how each on-screen tag layout looks with how well the Neon reads it.

    python scripts/tag_bars_gallery.py SHOTS_DIR TAG_BARS_SESSION [--results BARS_SUMMARY_CSV] [-o OUT_HTML]

SHOTS_DIR holds phone screenshots: bars_v<k>.png for the k-th variant of the tag_bars step (in
study order: the first hold shows them in that order), and optionally plain_feed.png (the feed
without tags) and old_feed_bands_12mm.png (markers.on_screen: 12 mm tag36h11 bands above and
below the feed). TAG_BARS_SESSION is any tag_bars session (even one run without the glasses): its
marker_layout events give each variant's bar heights and the feed space left. --results is
bars_summary.csv from `python -m socialeyes.gaze.ladder` on a tag_bars recording; without it the
page shows the layouts with their read rates still to come.

Feed space is the height between the bars, compared with the plain feed's (sync strip + 52 dp top
bar, 50 dp tab bar).
"""
from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path

import pandas as pd

HOLDS = ["normal (36 cm)", "arm's length (53 cm)", "lap (37 cm)"]


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


def card(img: str, title: str, lines: list[str], table: str = "") -> str:
    body = "".join(f"<p>{html.escape(t)}</p>" for t in lines)
    return (f'<figure><a href="{img}"><img src="{img}" alt="{html.escape(title)}"></a>'
            f"<figcaption><h2>{html.escape(title)}</h2>{body}{table}</figcaption></figure>")


def rates_table(rows: pd.DataFrame) -> str:
    if rows.empty:
        return '<p class="todo">Read rates: not recorded yet (needs a tag_bars session with the glasses).</p>'
    cells = "".join(
        f"<tr><td>{HOLDS[int(r.hold)] if int(r.hold) < len(HOLDS) else f'hold {int(r.hold)}'}</td>"
        f"<td class='{'good' if r.top_and_bottom >= .85 else 'mid' if r.top_and_bottom >= .5 else 'bad'}'>"
        f"{r.top_and_bottom:.0%}</td><td>{r.tag_read:.0%}</td></tr>"
        for r in rows.sort_values("hold").itertuples())
    return ("<table><tr><th></th><th>top + bottom read</th><th>tags read</th></tr>" + cells + "</table>")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("shots", type=Path)
    p.add_argument("session", type=Path, help="a tag_bars session folder")
    p.add_argument("--results", type=Path, help="bars_summary.csv from socialeyes.gaze.ladder")
    p.add_argument("-o", "--out", type=Path)
    args = p.parse_args(argv)
    out = args.out or args.shots.parent / "index.html"
    results = pd.read_csv(args.results) if args.results else pd.DataFrame(columns=["variant"])
    plain = plain_feed_px(args.session)
    rel = lambda name: Path(__import__("os").path.relpath(args.shots / name, out.parent)).as_posix()  # noqa: E731

    cards = []
    if (args.shots / "plain_feed.png").is_file():
        cards.append(card(rel("plain_feed.png"), "Plain feed (no tags)",
                          [f"Feed space: {plain:.0f} px (the baseline).", "No phone tracking from the screen."]))
    if (args.shots / "old_feed_bands_12mm.png").is_file():
        cell = 12 / 8 * 395.8 / 25.4  # px per cell of a 12 mm tag36h11 tag
        band = 10 * cell + 2 * 395.8 / 25.4  # tag + 1-cell quiet zone each side, 2 mm from the edge
        feed = plain - 2 * band
        cards.append(card(rel("old_feed_bands_12mm.png"), "Used so far: 36h11 12 mm in bands",
                          [f"Feed space: {feed:.0f} px ({feed / plain - 1:+.0%}).",
                           "Accuracy check, 12 Oct, display calibrated: tags read in 100% of feed frames, "
                           "90-100% during validation (held normally)."]))
    for k, bars in enumerate(bar_layouts(args.session)):
        img = f"bars_v{k}.png"
        if not (args.shots / img).is_file():
            print(f"missing {img} ({bars['variant']})", file=sys.stderr)
            continue
        feed = float(bars["feed_px"])
        cards.append(card(rel(img), bars["variant"],
                          [f"Feed space: {feed:.0f} px ({feed / plain - 1:+.1%}).",
                           f"Top bar {bars['top_bar_dp']:.0f} dp, tab bar {bars['tab_bar_dp']:.0f} dp "
                           f"(normally 84 and 50)."],
                          rates_table(results[results["variant"] == bars["variant"]])))

    page = f"""<!doctype html><meta charset="utf-8"><title>On-screen tags: look vs. tracking</title>
<style>
 body {{ font: 14px/1.4 system-ui, sans-serif; margin: 24px; color: #222; }}
 h1 {{ font-size: 20px; }} h2 {{ font-size: 15px; margin: 6px 0; }}
 main {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); gap: 20px; }}
 figure {{ margin: 0; border: 1px solid #ddd; border-radius: 8px; padding: 10px; background: #fafafa; }}
 img {{ width: 100%; border: 1px solid #ccc; border-radius: 6px; }}
 p {{ margin: 4px 0; }} .todo {{ color: #888; font-style: italic; }}
 table {{ border-collapse: collapse; margin-top: 6px; width: 100%; }}
 td, th {{ border-bottom: 1px solid #e3e3e3; padding: 2px 4px; text-align: left; font-size: 13px; }}
 .good {{ color: #0a7a2f; font-weight: 600; }} .mid {{ color: #a66a00; }} .bad {{ color: #b3261e; }}
</style>
<h1>On-screen tags: how they look vs. how well the Neon reads them (CAM-165)</h1>
<p>Phone screenshots (Motorola Edge 40 Pro). "Top + bottom read": share of scene frames with at least
one top and one bottom tag read, which phone tracking needs. Green ≥ 85%, amber ≥ 50%.</p>
<main>{''.join(cards)}</main>
"""
    out.write_text(page, encoding="utf-8")
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
