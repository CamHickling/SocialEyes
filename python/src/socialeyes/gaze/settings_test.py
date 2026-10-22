"""Settings test (`settings_test` step): which fixed screen brightness and Neon scene camera
exposure to use in phone-only sessions (CAM-165).

    python -m socialeyes.gaze.settings_test <neon recording folder> <session folder> [-o OUT]

For every setting the app showed (a marker_layout whose ladder.bars has settings_test), the scene
frames after it settled (1.2 s after an auto exposure setting, 0.3 s after a manual one) are scored
as the display calibration scores them: share of the bar tags read, share of frames that place the
phone (a pose from the tags), the post photo's share at full white (blown out) and its grey level;
plus the scene video's frame rate while the setting was on. Writes settings_observations.csv (one
row per setting shown), settings_summary.csv (per setting and hold) and a report ranking the
settings by their worst hold (display_calibration.rank), leaving out any that slow the scene video.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from ..session.io import Session, load_session
from .display_calibration import Layout, Measure, measure, rank
from .ladder import Arrangement, arrangements
from .neon import NeonRecording, SceneVideo, read_recording
from .tags import TagDetector
from .tracking import Screen, clock_offset_ns

FRAME_STEP = 2          # score every 2nd frame (the frame rate counts them all)
SLOW_VIDEO = 0.8        # a setting whose scene video runs below this share of the usual rate is left out

OBS_COLUMNS = ["variant", "hold", "phase", "brightness", "camera", "frames", "fps", "tags_read", "placed",
               "blown_out", "image_level", "margin"]


def setting_arrangements(session: Session) -> list[Arrangement]:
    """Each setting as shown, once: app 0.3.3 sometimes logged a setting's layout twice, which
    would otherwise split it in two and skip its settle time twice."""
    out: list[Arrangement] = []
    for a in arrangements(session):
        if not (a.bars and a.bars.get("settings_test")):
            continue
        prev = out[-1] if out else None
        if prev is not None and (prev.hold, prev.phase) == (a.hold, a.phase) and prev.end_ns == a.start_ns:
            prev.end_ns = a.end_ns
            prev.tags, prev.bars = a.tags, a.bars   # the later layout is the settled one
        else:
            out.append(a)
    return out


def analyse(rec: NeonRecording, session: Session) -> pd.DataFrame:
    arrs = setting_arrangements(session)
    if not arrs:
        raise ValueError("this session has no settings_test step (marker_layout events with ladder.bars.settings_test)")
    off = clock_offset_ns(session)
    screen = Screen.of(session.device)
    detector = TagDetector(family=arrs[0].family)
    rows = []
    with SceneVideo(rec.scene_video) as video:
        hold, H = None, None
        for a in arrs:
            if a.hold != hold:
                hold, H = a.hold, None
            t0 = a.start_ns + off + float(a.bars.get("settle_ms", 300)) * 1e6
            t1 = a.end_ns + off
            idx = np.where((rec.scene_t >= t0) & (rec.scene_t < t1))[0]
            fps = len(idx) / ((t1 - t0) / 1e9) if t1 > t0 else float("nan")
            image = a.bars.get("image")
            layout = Layout(a.tags, tuple(image) if image else None, screen, rec.K, rec.dist)
            frames = [g for _, g in video.gray(idx[::FRAME_STEP])]
            camera = a.bars.get("camera") or {}
            m, H = measure(frames, layout, detector, float(a.bars.get("brightness", np.nan)), camera, H)
            rows.append([a.bars["variant"], a.hold, a.phase, m.brightness, json.dumps(camera, sort_keys=True), m.frames,
                         fps, m.tags_read, m.pose_frames / m.frames if m.frames else np.nan, m.blown_out, m.image_level,
                         m.margin])
            print(f"  hold {a.hold} {a.bars['variant']}: {len(idx)} frames, {fps:.0f} fps", file=sys.stderr, flush=True)
    return pd.DataFrame(rows, columns=OBS_COLUMNS)


def summary(obs: pd.DataFrame) -> pd.DataFrame:
    """Per setting and hold, frame-weighted over the times it was shown."""
    rows = []
    for (v, h), g in obs.groupby(["variant", "hold"], sort=False):
        def avg(col):   # frame-weighted, over the times it was shown with frames to score
            ok = g[col].notna() & (g["frames"] > 0)
            return float(np.average(g.loc[ok, col], weights=g.loc[ok, "frames"])) if ok.any() else np.nan
        blown = g[g["frames"] > 0].dropna(subset=["blown_out"])
        rows.append({"variant": v, "hold": h, "brightness": g["brightness"].iloc[0], "camera": g["camera"].iloc[0],
                     "frames": int(g["frames"].sum()), "fps": float(g["fps"].mean()), "tags_read": avg("tags_read"),
                     "placed": avg("placed"), "margin": avg("margin"),
                     "blown_out": float(np.average(blown["blown_out"], weights=blown["frames"].clip(lower=1))) if len(blown) else np.nan,
                     "image_level": float(blown["image_level"].median()) if len(blown) else np.nan})
    return pd.DataFrame(rows)


def ranked(summ: pd.DataFrame) -> tuple[list[str], list[str]]:
    """The settings best first, judged by their worst hold, and those left out for a slow scene video."""
    usual = summ["fps"].median()
    slow = sorted(summ.loc[summ["fps"] < SLOW_VIDEO * usual, "variant"].unique())
    measures = []
    for v, g in summ.groupby("variant", sort=False):
        if v in slow:
            continue
        m = Measure(float(g["brightness"].iloc[0]), json.loads(g["camera"].iloc[0]), frames=int(g["frames"].sum()),
                    tags_read=float(g["placed"].min()), margin=float(g["margin"].min()),
                    blown_out=None if g["blown_out"].isna().all() else float(g["blown_out"].max()),
                    image_level=None if g["image_level"].isna().all() else float(g["image_level"].median()))
        m.variant = v
        measures.append(m)
    return [m.variant for m in rank(measures)], slow


def report(summ: pd.DataFrame, holds: dict[int, str] | None = None) -> str:
    order, slow = ranked(summ)
    hs = sorted(summ["hold"].unique())
    lines = ["Settings test: per setting and hold, frames placing the phone (tags read) / photo blown out / photo",
             "grey level in the video (0-255; detail survives at about 80-235) / scene video fps",
             "Ranked by the worst hold: most frames placing the phone, then least blown out, then the photo's grey",
             "level, then brightness (display_calibration.rank).", ""]
    for h in hs:
        lines.append(f"  hold {h}: {(holds or {}).get(h, '')}")
    lines.append("")
    lines.append(f"  {'#':>4}  {'setting':32s}" + "".join(f"  {'hold ' + str(h):29s}" for h in hs))
    rest = [v for v in summ["variant"].unique() if v not in order]
    for k, v in enumerate(order + rest):
        cells = []
        for h in hs:
            r = summ[(summ["variant"] == v) & (summ["hold"] == h)]
            if r.empty:
                cells.append(f"  {'-':29s}")
                continue
            r = r.iloc[0]
            blown = "-" if pd.isna(r["blown_out"]) else f"{r['blown_out']:.0%}"
            level = "-" if pd.isna(r["image_level"]) else f"{r['image_level']:.0f}"
            cells.append(f"  {r['placed']:4.0%} ({r['tags_read']:4.0%}) {blown:>4s} {level:>3s} {r['fps']:3.0f}  ")
        rank_no = str(k + 1) if v in order else ("slow" if v in slow else "-")
        lines.append(f"  {rank_no:>4}  {v:32s}" + "".join(cells))
    if slow:
        lines.append(f"\nLeft out, scene video below {SLOW_VIDEO:.0%} of its usual frame rate: {', '.join(slow)}")
    if order:
        lines.append(f"\nBest: {order[0]}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m socialeyes.gaze.settings_test", description=__doc__.splitlines()[0])
    p.add_argument("neon", help="Neon recording folder (native format)")
    p.add_argument("session", help="the matching session folder")
    p.add_argument("-o", "--out", help="output folder (default: analysis_out/settings_test/<session>)")
    args = p.parse_args(argv)
    session = load_session(args.session)
    obs = analyse(read_recording(args.neon), session)
    ev = session.events
    holds = {}
    if "instruction" in ev:
        starts = ev[(ev["type"] == "tag_ladder_hold") & (ev["status"] == "start")]
        holds = {int(r["hold"]): r["instruction"] for _, r in starts.iterrows()}
    summ = summary(obs)
    text = report(summ, holds)
    out = Path(args.out) if args.out else Path("analysis_out") / "settings_test" / Path(args.session).name
    out.mkdir(parents=True, exist_ok=True)
    obs.to_csv(out / "settings_observations.csv", index=False)
    summ.to_csv(out / "settings_summary.csv", index=False)
    (out / "settings_report.txt").write_text(text + "\n", encoding="utf-8")
    print(text)
    print(f"\nWrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
