"""Tag size ladder (`tag_ladder` step): how often the Neon scene camera reads each tag size,
side inset and top/bottom edge gap, per way of holding the phone (CAM-165).

    python -m socialeyes.gaze.ladder <neon recording folder> <session folder> [-o OUT]

For every scene frame during the ladder, the phone's pose is solved from all tags found
(tracking.solve_pose), each tag on screen is projected into the frame to get its apparent
width in pixels, and whether it was detected is recorded. Prints detection rates per hold and
writes ladder_observations.csv (one row per tag per frame).
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

import cv2
import numpy as np
import pandas as pd

from ..session.io import Session, load_session
from .neon import NeonRecording, read_recording, undistort
from .tags import TagDetector, tag_corners
from .tracking import Screen, apply_h, clock_offset_ns, solve_pose

SETTLE_MS = 300.0   # skip frames this soon after the layout changes (the screen is redrawing)
READABLE = 0.85     # detection rate counted as "readable"

OBS_COLUMNS = ["hold", "phase", "frame", "tag_id", "kind", "value_mm", "size_mm", "apparent_px", "detected",
               "distance_mm"]


@dataclass
class Arrangement:
    hold: int
    phase: int
    start_ns: int        # session clock
    end_ns: int
    tags: dict           # tag id -> screen corners (px)
    info: dict           # tag id -> {"kind", "value_mm", "size_mm"}


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
        out.append(Arrangement(int(lad["hold"]), int(lad["phase"]), t0, t1,
                               {int(i): tag_corners(v) for i, v in r["tags"].items()},
                               {int(i): v for i, v in lad["tags"].items()}))
    return out


def observe(frames: Iterable[tuple[int, int, np.ndarray]], arr: Arrangement, K: np.ndarray, dist: np.ndarray,
            screen: Screen, detector: TagDetector) -> Iterator[list]:
    """Observation rows for one arrangement from (frame index, unix ns, gray image) frames."""
    for fi, _, gray in frames:
        raw = detector.detect(gray, want=len(arr.tags))
        dets = {i: undistort(c, K, dist) for i, c in raw.items() if i in arr.tags}
        pose = solve_pose(dets, arr.tags, K, screen)
        if pose is None:
            continue
        M = np.linalg.inv(pose.H)
        for i, corners in arr.tags.items():
            c = apply_h(M, corners)
            side = float(np.mean(np.linalg.norm(c - np.roll(c, 1, axis=0), axis=1)))
            inf = arr.info[i]
            yield [arr.hold, arr.phase, fi, i, inf["kind"], float(inf["value_mm"]), float(inf["size_mm"]), side,
                   i in dets, float(np.linalg.norm(pose.t))]


def analyse(rec: NeonRecording, session: Session) -> pd.DataFrame:
    arrs = arrangements(session)
    if not arrs:
        raise ValueError("this session has no tag_ladder arrangements (marker_layout events with 'ladder')")
    off = clock_offset_ns(session)
    screen = Screen.of(session.device)
    detector = TagDetector()
    cap = cv2.VideoCapture(str(rec.scene_video))
    rows = []
    try:
        for a in arrs:
            idx = np.where((rec.scene_t >= a.start_ns + off + SETTLE_MS * 1e6) & (rec.scene_t < a.end_ns + off))[0]
            if not len(idx):
                continue
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(idx[0]))

            def frames():
                for i in idx:
                    ok, img = cap.read()
                    if not ok:
                        return
                    yield int(i), int(rec.scene_t[i]), cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

            rows.extend(observe(frames(), a, rec.K, rec.dist, screen, detector))
            print(f"  hold {a.hold} phase {a.phase}: {len(idx)} frames", file=sys.stderr, flush=True)
    finally:
        cap.release()
    return pd.DataFrame(rows, columns=OBS_COLUMNS)


def report(obs: pd.DataFrame, focal_px: float, holds: dict[int, str] | None = None) -> str:
    """Detection rates per hold, and how far away each size stays readable."""
    lines = []
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


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m socialeyes.gaze.ladder", description=__doc__.splitlines()[0])
    p.add_argument("neon", help="Neon recording folder (native format)")
    p.add_argument("session", help="the matching session folder")
    p.add_argument("-o", "--out", help="output folder (default: analysis_out/tag_ladder/<session>)")
    args = p.parse_args(argv)
    rec = read_recording(args.neon)
    session = load_session(args.session)
    obs = analyse(rec, session)
    ev = session.events
    holds = {}
    if "instruction" in ev:
        starts = ev[(ev["type"] == "tag_ladder_hold") & (ev["status"] == "start")]
        holds = {int(r["hold"]): r["instruction"] for _, r in starts.iterrows()}
    text = report(obs, float(rec.K[0, 0]), holds)
    out = Path(args.out) if args.out else Path("analysis_out") / "tag_ladder" / Path(args.session).name
    out.mkdir(parents=True, exist_ok=True)
    obs.to_csv(out / "ladder_observations.csv", index=False)
    (out / "ladder_report.txt").write_text(text + "\n", encoding="utf-8")
    print(text)
    print(f"\nWrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
