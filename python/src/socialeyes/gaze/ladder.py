"""Tag size ladder (`tag_ladder` step): how often the Neon scene camera reads each tag size,
side inset and top/bottom edge gap, per way of holding the phone (CAM-165). Also `tag_bars`
steps: how often each variant (tag family, size, grey level) fitted into the app's bars reads.

    python -m socialeyes.gaze.ladder <neon recording folder> <session folder> [-o OUT]

For every scene frame during the ladder, the tags are found (with smart detection unless --plain:
a close look where the tracker predicts each tag), the phone's pose is solved from them, each tag on screen is projected into the frame to get its apparent
width in pixels, and whether it was detected is recorded. Prints detection rates per hold and
writes ladder_observations.csv (one row per tag per frame).
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

import numpy as np
import pandas as pd

from ..session.io import Session, load_session
from .neon import NeonRecording, SceneVideo, read_recording
from .tags import TagDetector, tag_corners
from .tracking import PhoneTracker, Screen, apply_h, clock_offset_ns

SETTLE_MS = 300.0   # skip frames this soon after the layout changes (the screen is redrawing)
READABLE = 0.85     # detection rate counted as "readable"

OBS_COLUMNS = ["hold", "phase", "frame", "tag_id", "kind", "value_mm", "size_mm", "apparent_px", "detected",
               "distance_mm", "family", "grey", "variant", "corner"]


@dataclass
class Arrangement:
    hold: int
    phase: int
    start_ns: int        # session clock
    end_ns: int
    tags: dict           # tag id -> screen corners (px)
    info: dict           # tag id -> {"kind", "value_mm", "size_mm"[, "family", "cells", "grey", "variant"]}
    bars: dict | None = None   # tag_bars: {"variant", "top_bar_dp", "tab_bar_dp", "feed_px"}

    @property
    def family(self) -> str:
        return next(iter(self.info.values()), {}).get("family", "tag36h11")


def arrangements(session: Session) -> list[Arrangement]:
    """Each logged ladder arrangement and how long it was on screen."""
    ev = session.events
    lay = ev[(ev["type"] == "marker_layout")]
    if "ladder" not in lay:
        return []
    lay = lay[lay["ladder"].apply(lambda v: isinstance(v, dict))]
    holds = ev[ev["type"] == "tag_ladder_hold"] if "tag_ladder_hold" in set(ev["type"]) else ev.iloc[:0]
    ends = holds[holds["status"] == "end"]["t_ns"].to_numpy(np.int64) if len(holds) else np.array([], np.int64)
    rows = lay.sort_values("t_ns").to_dict("records")
    out = []
    for k, r in enumerate(rows):
        t0 = int(r["t_ns"])
        nxt = [int(rows[k + 1]["t_ns"])] if k + 1 < len(rows) else []
        later_ends = [int(e) for e in ends if e > t0]
        t1 = min(nxt + later_ends[:1] + [session.end_ns])
        lad = r["ladder"]
        info = {int(i): v for i, v in lad["tags"].items()}
        out.append(Arrangement(int(lad["hold"]), int(lad["phase"]), t0, t1,
                               {int(i): tag_corners(v, cells=info[int(i)].get("cells", 8)) for i, v in r["tags"].items()},
                               info, lad.get("bars")))
    return out


def observe(frames: Iterable[tuple[int, int, np.ndarray]], arr: Arrangement, tracker: PhoneTracker,
            detector: TagDetector, smart: bool = True) -> Iterator[list]:
    """Observation rows for one arrangement from (frame index, unix ns, gray image) frames. The
    tracker carries over between arrangements of a hold, so smart detection knows where to look."""
    for fi, t_ns, gray in frames:
        res = tracker.track(t_ns, gray, arr.tags, detector, smart)
        pose = res if res.source == "tags" else None
        if pose is None and arr.bars is None:
            continue
        # tag_bars has no other tags to place the phone by, so every frame counts (a variant read
        # badly must not drop its own frames); its apparent width needs a pose
        M = np.linalg.inv(pose.H) if pose is not None else None
        for i, corners in arr.tags.items():
            side = float("nan")
            if M is not None:
                c = apply_h(M, corners)
                side = float(np.mean(np.linalg.norm(c - np.roll(c, 1, axis=0), axis=1)))
            inf = arr.info[i]
            yield [arr.hold, arr.phase, fi, i, inf["kind"], float(inf["value_mm"]), float(inf["size_mm"]), side,
                   i in res.detected, pose.distance_mm if pose is not None else float("nan"),
                   inf.get("family", "tag36h11"), float(inf.get("grey", 0)),
                   inf.get("variant", ""), inf.get("corner", "")]


def analyse(rec: NeonRecording, session: Session, smart: bool = True) -> pd.DataFrame:
    arrs = arrangements(session)
    if not arrs:
        raise ValueError("this session has no tag_ladder arrangements (marker_layout events with 'ladder')")
    off = clock_offset_ns(session)
    screen = Screen.of(session.device)
    detectors: dict[str, TagDetector] = {}
    tracker = PhoneTracker(rec.K, rec.dist, screen)
    rows = []
    with SceneVideo(rec.scene_video) as video:
        hold = None
        for a in arrs:
            idx = np.where((rec.scene_t >= a.start_ns + off + SETTLE_MS * 1e6) & (rec.scene_t < a.end_ns + off))[0]
            if not len(idx):
                continue
            if a.hold != hold:
                tracker.reset()
                hold = a.hold
            frames = ((i, int(rec.scene_t[i]), gray) for i, gray in video.gray(idx))
            if a.family not in detectors:
                detectors[a.family] = TagDetector(family=a.family)
            rows.extend(observe(frames, a, tracker, detectors[a.family], smart))
            print(f"  hold {a.hold} phase {a.phase}: {len(idx)} frames", file=sys.stderr, flush=True)
    return pd.DataFrame(rows, columns=OBS_COLUMNS)


def bars_table(obs: pd.DataFrame, bars: dict[str, dict] | None = None) -> pd.DataFrame:
    """tag_bars: per variant and hold, the share of frames with each tag read, with a top and a
    bottom tag read (what phone tracking needs), and with none; plus the bars' heights."""
    b = obs[obs["kind"] == "bars"].copy()
    if b.empty:
        return pd.DataFrame()
    b["top"] = b["corner"].str.startswith("top")
    per_frame = b.groupby(["variant", "hold", "phase", "frame"]).apply(
        lambda f: pd.Series({"top": bool((f["detected"] & f["top"]).any()), "bottom": bool((f["detected"] & ~f["top"]).any()),
                             "any": bool(f["detected"].any())}), include_groups=False).reset_index()
    rows = []
    for (v, h), f in per_frame.groupby(["variant", "hold"]):
        t = b[(b["variant"] == v) & (b["hold"] == h)]
        rows.append({"variant": v, "hold": h, "frames": len(f), "tag_read": t["detected"].mean(),
                     "top_and_bottom": (f["top"] & f["bottom"]).mean(), "none": 1 - f["any"].mean(),
                     "family": t["family"].iloc[0], "size_mm": t["size_mm"].iloc[0], "grey": t["grey"].iloc[0],
                     **{k: (bars or {}).get(v, {}).get(k) for k in ("top_bar_dp", "tab_bar_dp")}})
    return pd.DataFrame(rows)


def report(obs: pd.DataFrame, focal_px: float, holds: dict[int, str] | None = None,
           bars: dict[str, dict] | None = None) -> str:
    """Detection rates per hold, and how far away each size stays readable."""
    lines = []
    table = bars_table(obs, bars)
    if len(table):
        lines.append("tag_bars: share of frames with a top AND a bottom tag read (tag reads overall), per hold")
        hs = sorted(table["hold"].unique())
        lines.append(f"  {'variant':24s} {'bars dp (top/tab)':18s}" + "".join(f"  hold {h:<16d}" for h in hs))
        order = table.groupby("variant")["top_and_bottom"].mean().sort_values(ascending=False).index
        for v in order:
            t = table[table["variant"] == v].set_index("hold")
            dims = f"{t['top_bar_dp'].iloc[0] or 0:.0f}/{t['tab_bar_dp'].iloc[0] or 0:.0f}"
            cells = "".join(f"  {t.loc[h, 'top_and_bottom']:4.0%} ({t.loc[h, 'tag_read']:4.0%})       " if h in t.index
                            else " " * 24 for h in hs)
            lines.append(f"  {v:24s} {dims:18s}{cells}")
        lines.append("  (the feed's own bars are 52+strip / 50 dp; frames per cell: about 4 s x rounds x 30 fps)")
        obs = obs[obs["kind"] != "bars"]
    rate = lambda d: f"{d['detected'].mean():4.0%} ({len(d)})"  # noqa: E731
    for h, d in obs.groupby("hold"):
        frames = d["frame"].nunique()
        lines.append(f"\nhold {h}: {(holds or {}).get(h, '')}")
        lines.append(f"  {frames} frames with a pose; distance median {d['distance_mm'].median() / 10:.0f} cm "
                     f"(10-90%: {d['distance_mm'].quantile(.1) / 10:.0f}-{d['distance_mm'].quantile(.9) / 10:.0f} cm)")
        for kind, title in (("size", "size (middle)"), ("left_inset", "left inset"), ("right_inset", "right inset"),
                            ("top_gap", "top gap"), ("bottom_gap", "bottom gap")):
            k = d[d["kind"] == kind]
            if len(k):
                cells = "   ".join(f"{v:g} mm: {rate(g)}" for v, g in k.groupby("value_mm"))
                lines.append(f"  {title:14s} {cells}")
    # detection vs apparent width, from the middle column (no edge effects)
    mid = obs[obs["kind"] == "size"]
    if len(mid):
        bins = np.arange(np.floor(mid["apparent_px"].min() / 2) * 2, mid["apparent_px"].max() + 2, 2)
        lines.append("\ndetection vs apparent width (middle column, all holds)")
        cut = pd.cut(mid["apparent_px"], bins, right=False)
        threshold = None
        for b, g in mid.groupby(cut, observed=True):
            if len(g) >= 20:
                lines.append(f"  {b.left:4.0f}-{b.right:<4.0f} px  {g['detected'].mean():4.0%} ({len(g)})")
                if threshold is None and g["detected"].mean() >= READABLE:
                    threshold = b.left
        if threshold is not None:
            lines.append(f"\nreadable (>= {READABLE:.0%}) from ~{threshold:.0f} px wide: a tag of S mm is readable out to "
                         f"~{focal_px:.0f} * S / {threshold:.0f} mm")
            lines.append("  " + "   ".join(f"{s:g} mm: {focal_px * s / threshold / 10:.0f} cm"
                                            for s in sorted(mid["size_mm"].unique())))
    return "\n".join(lines)


def out_dir(args) -> Path:
    out = Path(args.out) if args.out else Path("analysis_out") / "tag_ladder" / Path(args.session).name
    out.mkdir(parents=True, exist_ok=True)
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m socialeyes.gaze.ladder", description=__doc__.splitlines()[0])
    p.add_argument("neon", help="Neon recording folder (native format)")
    p.add_argument("session", help="the matching session folder")
    p.add_argument("-o", "--out", help="output folder (default: analysis_out/tag_ladder/<session>)")
    p.add_argument("--plain", action="store_true", help="no smart detection (only the whole-frame search)")
    args = p.parse_args(argv)
    rec = read_recording(args.neon)
    session = load_session(args.session)
    obs = analyse(rec, session, smart=not args.plain)
    ev = session.events
    holds = {}
    if "instruction" in ev:
        starts = ev[(ev["type"] == "tag_ladder_hold") & (ev["status"] == "start")]
        holds = {int(r["hold"]): r["instruction"] for _, r in starts.iterrows()}
    bars = {a.bars["variant"]: a.bars for a in arrangements(session) if a.bars}
    text = report(obs, float(rec.K[0, 0]), holds, bars)
    if bars:
        bars_table(obs, bars).to_csv(out_dir(args) / "bars_summary.csv", index=False)
    out = out_dir(args)
    obs.to_csv(out / "ladder_observations.csv", index=False)
    (out / "ladder_report.txt").write_text(text + "\n", encoding="utf-8")
    print(text)
    print(f"\nWrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
