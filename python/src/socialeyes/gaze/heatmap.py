"""Fixation heatmaps over the post images, pooled by condition (`socialeyes heatmaps`).

Every fixation on an image (fixations.csv from `socialeyes gaze`) adds a Gaussian at its image
position, weighted by its duration. The Gaussian's width is SIGMA_DEG of visual angle (about the
eye tracker's accuracy and the fovea's size), turned into image pixels with the participant's
distance from the phone (their face video's median during the feed if it was analysed, else
DISTANCE_MM), the screen's pixel density and the image's size on screen.

Each participant's map of an image is normalised to sum 1 before pooling, so every participant
counts equally however long they looked; a pooled map is the mean over the participants who
fixated the image at least once, i.e. the share of their looking time on the image that fell on
each spot. An image seen in two groups (e.g. with and without the "edited" label) also gets the
difference of the two maps.

Until the study is unblinded (session/unblinding.py) the heatmaps are blinded instead: one map per
post with every condition and version pooled, drawn over one version of its image, with no group
names, no difference maps and no aoi_dwell.csv, in analysis/heatmaps_blinded. They are for
checking the eye tracking, not for comparing conditions.
"""
from __future__ import annotations

import html
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import pandas as pd

from ..study.aoi import aoiset_from_json

SIGMA_DEG = 1.0
DISTANCE_MM = 350.0
GRID = 240  # the maps' long side, in cells


@dataclass
class SessionFixations:
    participant_id: str
    session_uid: str
    fixations: pd.DataFrame     # fixations.csv
    plan: dict                  # the participant's plan (conditions of each post)
    px_per_mm: float
    distance_mm: float


@dataclass
class HeatmapResult:
    out_dir: Optional[str] = None
    images: list = field(default_factory=list)   # {"image_id", "groups": {name: {"participants", "fixations"}}, "files"}
    page: Optional[str] = None


def group_of(plan: dict, post_id: str, by: str) -> Optional[str]:
    """The post's group for pooling: its cell (``by="cell"``), or one factor's level."""
    post = next((p for p in plan["feed"] if p["post_id"] == post_id), None)
    if post is None:
        return None
    if by == "cell":
        cell = post.get("cell") or "filler"
        between = plan.get("group_key")
        return f"{cell} | {between}" if between else cell
    level = (post.get("conditions") or {}).get(by) or (plan.get("between") or {}).get(by)
    return f"{by}={level}" if level is not None else None


def sigma_img_px(px_per_mm: float, distance_mm: float, img_per_screen_px: float, sigma_deg: float = SIGMA_DEG) -> float:
    return math.tan(math.radians(sigma_deg)) * distance_mm * px_per_mm * img_per_screen_px


def _density(fx: pd.DataFrame, sigma: np.ndarray, w: int, h: int) -> np.ndarray:
    """Duration-weighted sum of Gaussians on a grid of the image (long side GRID), summing to 1."""
    k = GRID / max(w, h)
    gw, gh = max(1, round(w * k)), max(1, round(h * k))
    xs, ys = (np.arange(gw) + 0.5) / k, (np.arange(gh) + 0.5) / k
    out = np.zeros((gh, gw))
    for (x, y, d), s in zip(fx[["img_x", "img_y", "duration_ms"]].to_numpy(float), sigma):
        gx = np.exp(-0.5 * ((xs - x) / s) ** 2)
        gy = np.exp(-0.5 * ((ys - y) / s) ** 2)
        out += d * np.outer(gy, gx) / (2 * math.pi * s * s)
    total = out.sum()
    return out / total if total > 0 else out


def pooled_maps(sessions: list[SessionFixations], sizes: dict, by: str = "cell",
                sigma_deg: float = SIGMA_DEG) -> dict:
    """image_id -> group -> {"map": mean normalised density, "participants": n, "fixations": n}."""
    per: dict = {}
    for s in sessions:
        f = s.fixations[(s.fixations["image_id"].fillna("") != "") & s.fixations["img_x"].notna()]
        for image_id, fx in f.groupby("image_id"):
            if image_id not in sizes:
                continue
            group = group_of(s.plan, fx["post_id"].iloc[0], by)
            if group is None:
                continue
            w, h = sizes[image_id]
            sig = sigma_img_px(s.px_per_mm, s.distance_mm, fx["img_per_screen_px"].fillna(1.0).to_numpy(float), sigma_deg)
            d = per.setdefault(image_id, {}).setdefault(group, {"maps": [], "fixations": 0})
            d["maps"].append(_density(fx, np.atleast_1d(sig), w, h))
            d["fixations"] += len(fx)
    return {img: {g: {"map": np.mean(d["maps"], axis=0), "participants": len(d["maps"]), "fixations": d["fixations"]}
                  for g, d in groups.items()} for img, groups in per.items()}


def aoi_dwell(sessions: list[SessionFixations], by: str = "cell") -> pd.DataFrame:
    """Per image, group and AOI: the mean over participants of the share of their fixation time on
    the image that was in the AOI (blank AOI: on the image but in none)."""
    rows = []
    for s in sessions:
        f = s.fixations[s.fixations["image_id"].fillna("") != ""]
        for image_id, fx in f.groupby("image_id"):
            group = group_of(s.plan, fx["post_id"].iloc[0], by)
            total = fx["duration_ms"].sum()
            for aoi, g in fx.groupby(fx["aoi"].fillna("")):
                rows.append({"image_id": image_id, "group": group, "participant_id": s.participant_id,
                             "aoi": aoi, "share": g["duration_ms"].sum() / total if total else 0.0})
    if not rows:
        return pd.DataFrame(columns=["image_id", "group", "aoi", "participants", "mean_share"])
    d = pd.DataFrame(rows)
    # participants who looked at the image but never at this AOI count as 0
    full = (d.pivot_table(index=["image_id", "group", "participant_id"], columns="aoi", values="share", aggfunc="sum")
            .fillna(0).stack().rename("share").reset_index())
    out = full.groupby(["image_id", "group", "aoi"]).agg(participants=("participant_id", "nunique"),
                                                          mean_share=("share", "mean")).reset_index()
    out["mean_share"] = out["mean_share"].round(4)
    return out


def base_images(images: dict) -> dict:
    """post_id -> the image a blinded map is drawn over: the post's first image in images.csv,
    whatever condition that is (images: the manifest's)."""
    out: dict = {}
    for image_id, info in images.items():
        if info.get("post_id"):
            out.setdefault(info["post_id"], image_id)
    return out


def _grid_shape(w: int, h: int) -> tuple[int, int]:
    k = GRID / max(w, h)
    return max(1, round(h * k)), max(1, round(w * k))


def pooled_by_post(sessions: list[SessionFixations], images: dict, sigma_deg: float = SIGMA_DEG) -> dict:
    """Blinded pooling: post_id -> {"image_id": base image, "map", "participants", "fixations"}, every
    condition and version of the post together. Each version's map is made on its own image and
    scaled to the base image's grid (versions of a post are the same picture, edited)."""
    import cv2

    base = base_images(images)
    per: dict = {}
    for s in sessions:
        f = s.fixations[(s.fixations["image_id"].fillna("") != "") & s.fixations["img_x"].notna()]
        for image_id, fx in f.groupby("image_id"):
            info = images.get(image_id)
            post = (info or {}).get("post_id")
            if not info or post not in base:
                continue
            sig = sigma_img_px(s.px_per_mm, s.distance_mm, fx["img_per_screen_px"].fillna(1.0).to_numpy(float), sigma_deg)
            m = _density(fx, np.atleast_1d(sig), info["width"], info["height"])
            b = images[base[post]]
            target = _grid_shape(b["width"], b["height"])
            if m.shape != target:
                m = cv2.resize(m, (target[1], target[0]), interpolation=cv2.INTER_LINEAR)
                m = m / m.sum() if m.sum() > 0 else m
            d = per.setdefault(post, {"maps": [], "fixations": 0})
            d["maps"].append(m)
            d["fixations"] += len(fx)
    return {post: {"image_id": base[post], "map": np.mean(d["maps"], axis=0), "participants": len(d["maps"]),
                   "fixations": d["fixations"]} for post, d in per.items()}


# ---------------------------------------------------------------- drawing

STYLE = """
:root{--bg:#fff;--fg:#1a1a1a;--muted:#666;--line:#ddd;--warn-bg:#fff4d6;--warn-fg:#5c4300}
@media (prefers-color-scheme:dark){:root{--bg:#151515;--fg:#eee;--muted:#aaa;--line:#333;--warn-bg:#3a2f12;--warn-fg:#f3dc9a}}
body{background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif;margin:0 auto;max-width:1200px;padding:16px}
h2{font-size:17px;margin:28px 0 8px;border-top:1px solid var(--line);padding-top:16px}
.row{display:flex;gap:16px;flex-wrap:wrap} figure{margin:0;flex:1 1 240px;max-width:360px}
img{width:100%;border-radius:8px} figcaption{font-size:13px;color:var(--muted)}
.disclaimer{background:var(--warn-bg);color:var(--warn-fg);border-radius:8px;padding:12px 16px}
"""

BLINDED_DISCLAIMER = (
    "<b>Blinded heatmaps: for checking the eye tracking, not for results.</b> Every condition and every "
    "version of a post is pooled into one map, drawn over one version of its image (the first listed in "
    "images.csv, whichever condition that is). Use them to check that looking lands on the images and the "
    "AOIs where you would expect. They are not a comparison of conditions and support no conclusions. "
    "They can still hint at a condition (for example if one version draws the eye somewhere the other "
    "doesn't), so look only as much as the check needs, and don't try to work out the conditions from them. "
    "Maps by condition, difference maps and AOI shares (aoi_dwell.csv) are made only after unblinding, "
    "which records who unblinded and when.")

UNBLINDED_NOTE = (
    "<b>Unblinded:</b> real condition names. Heatmaps are descriptive pictures of where people looked, "
    "not a test: compare conditions with your planned analysis of the tables, not by eye here.")


def render_blinded(build: Path, maps: dict, out: Path, progress: Callable[[str], None] = lambda s: None) -> HeatmapResult:
    """One PNG per post (<post_id>.png) and index.html with the disclaimer; no condition anywhere."""
    import cv2

    manifest = json.loads((build / "study.json").read_text(encoding="utf-8"))
    out.mkdir(parents=True, exist_ok=True)
    r = HeatmapResult(out_dir=str(out))
    rows = []
    for post in sorted(maps):
        m = maps[post]
        info = manifest["images"][m["image_id"]]
        bgr = cv2.imread(str(build / info["file"]), cv2.IMREAD_COLOR)
        if bgr is None:
            continue
        progress(f"Drawing post {post}…")
        k = 540 / max(bgr.shape[:2])
        base = cv2.resize(bgr, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)[:, :, ::-1].astype(float)
        aoiset = aoiset_from_json(json.loads((build / info["aoi"]).read_text(encoding="utf-8"))) if info.get("aoi") else None
        img = _overlay(base, m["map"], "inferno", float(m["map"].max()), signed=False)
        _draw_aois(img, aoiset)
        name = f"{post}.png"
        cv2.imwrite(str(out / name), img[:, :, ::-1])
        r.images.append({"post_id": post, "files": [name],
                         "groups": {"all": {"participants": m["participants"], "fixations": m["fixations"]}}})
        cap = f"{m['participants']} participant(s), {m['fixations']} fixations, all conditions together"
        rows.append(f'<section><h2>Post {html.escape(post)}</h2><div class=row><figure><img src="{name}" loading="lazy" '
                    f'alt="post {html.escape(post)}"><figcaption>{html.escape(cap)}</figcaption></figure></div></section>')
    page = f"""<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Gaze heatmaps (blinded)</title>
<style>{STYLE}</style>
<h1>Gaze heatmaps (blinded): {html.escape(manifest['study']['id'])}</h1>
<p class=disclaimer>{BLINDED_DISCLAIMER}</p>
<p>Where participants' fixations fell on each post, weighted by how long they lasted; each participant counts
equally. Brighter means more looking. White outlines are the AOIs of the image drawn.</p>
{''.join(rows) or '<p>No fixations on post images yet.</p>'}
"""
    (out / "index.html").write_text(page, encoding="utf-8")
    (out / "BLINDED.txt").write_text(
        "These heatmaps are blinded: every condition of a post pooled into one map, for checking the eye\n"
        "tracking only. Maps by condition are made after unblinding (Data tab, Unblind...).\n", encoding="utf-8")
    r.page = str(out / "index.html")
    return r



def _overlay(base: np.ndarray, density: np.ndarray, cmap: str, vmax: float, signed: bool) -> np.ndarray:
    import cv2
    from matplotlib import colormaps

    h, w = base.shape[:2]
    d = cv2.resize(density, (w, h), interpolation=cv2.INTER_CUBIC)
    if signed:
        x = np.clip(d / vmax, -1, 1) if vmax > 0 else d * 0
        rgba = colormaps[cmap]((x + 1) / 2)
        alpha = np.abs(x) ** 0.8
    else:
        x = np.clip(d / vmax, 0, 1) if vmax > 0 else d * 0
        rgba = colormaps[cmap](x)
        alpha = x ** 0.6
    grey = base.mean(axis=2, keepdims=True).repeat(3, axis=2) * 0.6 + base * 0.4  # dimmed, so colour stands out
    a = (0.85 * alpha)[..., None]
    return (grey * (1 - a) + rgba[..., :3] * 255 * a).astype(np.uint8)


def _draw_aois(img: np.ndarray, aoiset) -> None:
    import cv2

    if aoiset is None:
        return
    sx, sy = img.shape[1] / aoiset.width, img.shape[0] / aoiset.height
    for a in aoiset.aois:
        pts = (a.polygon * [sx, sy]).round().astype(np.int32)
        cv2.polylines(img, [pts], True, (255, 255, 255), max(1, img.shape[1] // 300), cv2.LINE_AA)
        x, y = pts[:, 0].min(), pts[:, 1].min()
        cv2.putText(img, a.name, (int(x) + 3, int(y) + 14), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)


def render(build: Path, maps: dict, out: Path, progress: Callable[[str], None] = lambda s: None) -> HeatmapResult:
    """PNGs per image and group (and difference maps), and index.html."""
    import cv2

    manifest = json.loads((build / "study.json").read_text(encoding="utf-8"))
    out.mkdir(parents=True, exist_ok=True)
    r = HeatmapResult(out_dir=str(out))
    rows = []
    for image_id in sorted(maps):
        groups = maps[image_id]
        info = manifest["images"][image_id]
        bgr = cv2.imread(str(build / info["file"]), cv2.IMREAD_COLOR)
        if bgr is None:
            continue
        progress(f"Drawing {image_id}…")
        k = 540 / max(bgr.shape[:2])
        base = cv2.resize(bgr, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)[:, :, ::-1].astype(float)
        aoiset = aoiset_from_json(json.loads((build / info["aoi"]).read_text(encoding="utf-8"))) if info.get("aoi") else None
        vmax = max(g["map"].max() for g in groups.values())
        cells, files = [], []
        names = sorted(groups)
        for n, g in enumerate(names):
            img = _overlay(base, groups[g]["map"], "inferno", vmax, signed=False)
            _draw_aois(img, aoiset)
            name = f"{image_id}__{n}.png"
            cv2.imwrite(str(out / name), img[:, :, ::-1])
            files.append(name)
            cells.append((name, g, f"{groups[g]['participants']} participant(s), {groups[g]['fixations']} fixations"))
        if len(names) == 2:
            diff = groups[names[0]]["map"] - groups[names[1]]["map"]
            img = _overlay(base, diff, "RdBu_r", float(np.abs(diff).max()), signed=True)
            _draw_aois(img, aoiset)
            name = f"{image_id}__diff.png"
            cv2.imwrite(str(out / name), img[:, :, ::-1])
            files.append(name)
            cells.append((name, f"{names[0]} minus {names[1]}", "red: more looking in the first, blue: in the second"))
        r.images.append({"image_id": image_id, "files": files,
                         "groups": {g: {"participants": groups[g]["participants"], "fixations": groups[g]["fixations"]}
                                    for g in names}})
        figs = "".join(f'<figure><img src="{f}" loading="lazy" alt="{html.escape(t)}"><figcaption><b>{html.escape(t)}</b>'
                       f"<br>{html.escape(c)}</figcaption></figure>" for f, t, c in cells)
        rows.append(f"<section><h2>{html.escape(image_id)}</h2><div class=row>{figs}</div></section>")
    page = f"""<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Gaze heatmaps</title>
<style>{STYLE}</style>
<h1>Gaze heatmaps: {html.escape(manifest['study']['id'])}</h1>
<p class=disclaimer>{UNBLINDED_NOTE}</p>
<p>Where participants' fixations fell on each post image, weighted by how long they lasted; each participant
counts equally. Brighter means more looking. White outlines are the AOIs. Where an image was seen in two
groups, the third map is the difference (red: more looking in the first group, blue: in the second). Per-AOI
shares are in <code>aoi_dwell.csv</code>.</p>
{''.join(rows) or '<p>No fixations on post images yet.</p>'}
"""
    (out / "index.html").write_text(page, encoding="utf-8")
    r.page = str(out / "index.html")
    return r


# ---------------------------------------------------------------- a study


def load_sessions(data_dir: Path, analysis_dir: Path, build_for: Callable[[Path], Optional[Path]],
                  default_distance_mm: float = DISTANCE_MM) -> tuple[list[SessionFixations], list, Optional[Path]]:
    """(sessions with fixations.csv, (session folder, why) skipped, a build to draw with)."""
    from ..session.io import load_session

    out, skipped, last_build = [], [], None
    for meta in sorted(data_dir.glob("*/*/session.json")):
        folder = meta.parent
        if folder.parent.name.startswith("."):
            continue
        res = analysis_dir / folder.parent.name / folder.name
        fx = res / "fixations.csv"
        if not fx.is_file():
            skipped.append((str(folder), "no fixations.csv yet (run socialeyes gaze on its Neon recording)"))
            continue
        build = build_for(folder)
        if build is None:
            skipped.append((str(folder), "the study doesn't compile"))
            continue
        s = load_session(folder)
        plan = json.loads((build / "plans" / f"{s.participant_id}.json").read_text(encoding="utf-8"))
        dist = default_distance_mm
        face = res / "face_summary.json"
        if face.is_file():
            steps = json.loads(face.read_text(encoding="utf-8")).get("steps", {})
            feed = next((v for v in steps.values() if v.get("distance_mm_median")), None)
            if feed:
                dist = float(feed["distance_mm_median"])
        out.append(SessionFixations(s.participant_id, s.meta.get("session_uid") or folder.name,
                                    pd.read_csv(fx), plan, s.px_per_mm, dist))
        last_build = build
    return out, skipped, last_build


def study_heatmaps(study_dir: Path | str, data_dir: Optional[Path | str] = None, out_dir: Optional[Path | str] = None,
                   by: str = "cell", sigma_deg: float = SIGMA_DEG,
                   progress: Callable[[str], None] = lambda s: None,
                   unblind: bool = False, unblinding=None) -> tuple[HeatmapResult, list]:
    """Blinded heatmaps (one per post, all conditions pooled) in analysis/heatmaps_blinded; with
    ``unblind`` (needs ``unblinding``, and is logged) maps by ``by``, difference maps and
    aoi_dwell.csv in analysis/heatmaps."""
    import shutil
    import tempfile

    from .. import settings
    from ..phone.unload import study_id_of
    from ..session.export import snapshot_or_none
    from ..study.compiler import compile_study

    sid = study_id_of(study_dir)
    data = Path(data_dir) if data_dir else settings.data_dir(sid)
    out = Path(out_dir) if out_dir else settings.analysis_dir(sid) / ("heatmaps" if unblind else "heatmaps_blinded")
    if unblind:
        from ..session import unblinding as ub

        ub.unblind(study_dir, data, sid, unblinding, f"heatmaps by {by}")
    tmp = Path(tempfile.mkdtemp(prefix="socialeyes-heatmaps-"))
    try:
        fresh: list = []

        def build_for(folder: Path) -> Optional[Path]:
            snap = snapshot_or_none(sid)(folder)
            if snap is not None:
                return snap
            if not fresh:
                fresh.append(compile_study(study_dir, tmp / "package")[0])
            return fresh[0]

        sessions, skipped, build = load_sessions(data, settings.analysis_dir(sid), build_for)
        if build is None:
            build = build_for(data)
        manifest = json.loads((build / "study.json").read_text(encoding="utf-8"))
        if not unblind:
            return render_blinded(build, pooled_by_post(sessions, manifest["images"], sigma_deg), out, progress), skipped
        sizes = {i: (v["width"], v["height"]) for i, v in manifest["images"].items()}
        maps = pooled_maps(sessions, sizes, by, sigma_deg)
        r = render(build, maps, out, progress)
        aoi_dwell(sessions, by).to_csv(out / "aoi_dwell.csv", index=False)
        return r, skipped
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
