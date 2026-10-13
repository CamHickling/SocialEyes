"""CAM-165 option 1: can the feed's own images keep track of the phone?

The app logs where every post image is on screen in every frame it draws (viewport.csv), and the
study package has the images, so for any scene frame we know what most of the screen showed. Given
a rough phone pose (the last tag pose, some frames old), the scene frame is warped onto the screen
and aligned with the expected images (ECC, a direct intensity alignment that tolerates the
screen's brightness and contrast in the video). This tests that against the tag pose:

    python scripts/content_tracking_test.py NEON_FOLDER SESSION_FOLDER PACKAGE_FOLDER OUT_DIR [EVERY]

PACKAGE_FOLDER is the compiled study package the session ran (data/<study>/builds/<hash>);
OUT_DIR caches the tag scan (for CAM-210 runs: analysis_out/tracking_pnp/<run>).

On feed frames with a reference tag pose (tags at the top and bottom; every EVERY-th, default 2):
  0. Exposure: how much of the known content the video resolves (not blown out).
  1. Latency: the app logs a frame when it draws it; the screen shows it a little later. The delay
     that best lines the content up with the tag pose.
  2. Agreement (N = 0): content alignment started from the reference itself; how far it moves
     away from the tags (the floor on its accuracy here).
  3. Bridging (N > 0): as if the tags had been missed for N frames. Error vs the reference of:
     keeping the old pose; flow (as in socialeyes gaze); and content alignment started from the
     old pose or from flow. An alignment is rejected (and its starting estimate kept) when its
     correlation is under MIN_CC or it moves the estimate by more than MAX_SHIFT_MM.
Also by scroll speed: content that moves fast is harder to place in time.

Results are printed and saved to OUT_DIR/content_results.json, with a few example images.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from tracking_reference import Frame, Run, load_run, stats, table  # noqa: E402
from socialeyes.gaze.neon import SceneVideo  # noqa: E402
from socialeyes.gaze.tracking import apply_h  # noqa: E402

SCALE = 0.25                  # screen px -> working px (270 x 600 for the Edge 40 Pro)
MIN_CC = 0.6                  # ECC correlation needed to accept an alignment
MIN_CONTENT = 0.15            # share of the screen that must be known content
MIN_USABLE = 0.04             # ... and not blown out in the video
SATURATED = 245               # scene pixel value from which the video is treated as blown out
MAX_SHIFT_MM = 8.0            # content may move the prior by at most this (else it's a mis-lock)
PRIOR_FRAMES = (0, 3, 8, 15, 30, 60)
LATENCIES_MS = (-30, 0, 15, 30, 45, 60, 100)
MODELS = ("shift", "shift+rotation")


class Content:
    """What the screen showed at a given time: post images placed from viewport.csv."""

    def __init__(self, run: Run, package: Path):
        s = run.session
        vp = s.viewport
        self.frame_t = vp.groupby("frame")["t_ns"].first().sort_index()
        self.rows = {k: g for k, g in vp.groupby("frame")}
        plan = json.loads((package / "plans" / f"{s.participant_id}.json").read_text(encoding="utf-8"))
        self.image_of = {p["post_id"]: p["image_id"] for p in plan["feed"]}
        self.package = package
        self.feed_area = s.feed_area
        self.w, self.h = int(run.screen.w * SCALE), int(run.screen.h * SCALE)
        self._img: dict[str, np.ndarray] = {}
        self.scroll = vp[vp["element"] == "frame"].set_index("t_ns")["scroll_y"].astype(float)

    def image(self, image_id: str) -> np.ndarray:
        if image_id not in self._img:
            path = next(self.package.glob(f"media/images/{image_id}.*"))
            self._img[image_id] = cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2GRAY).astype(np.float32)
        return self._img[image_id]

    def at(self, t_ns: int) -> Optional[tuple[np.ndarray, np.ndarray]]:
        """(canvas, mask) in working px for session time t_ns, or None if a sheet covered the
        feed or too little of the screen was known."""
        k = int(np.searchsorted(self.frame_t.to_numpy(), t_ns, side="right")) - 1
        if k < 0:
            return None
        rows = self.rows[self.frame_t.index[k]]
        if (rows["element"].isin(["sheet", "story", "reel"]) & (rows["top"] < self.feed_area[3])).any():
            return None
        canvas = np.zeros((self.h, self.w), np.float32)
        mask = np.zeros((self.h, self.w), np.uint8)
        x0a, y0a, x1a, y1a = (int(round(v * SCALE)) for v in self.feed_area)
        for _, r in rows[rows["element"] == "image"].iterrows():
            img = self.image(self.image_of[r["post_id"]])
            L, T, R, B = (r[c] * SCALE for c in ("left", "top", "right", "bottom"))
            if R - L < 4 or B - T < 4:
                continue
            # place the image into its rectangle, clipped to the feed area
            M = np.array([[(R - L) / img.shape[1], 0, L], [0, (B - T) / img.shape[0], T]], np.float32)
            warped = cv2.warpAffine(img, M, (self.w, self.h), flags=cv2.INTER_AREA, borderValue=0)
            inside = cv2.warpAffine(np.full(img.shape, 255, np.uint8), M, (self.w, self.h), flags=cv2.INTER_NEAREST)
            clip = np.zeros_like(mask)
            clip[max(y0a, 0):y1a, max(x0a, 0):x1a] = 255
            inside &= clip
            canvas[inside > 0] = warped[inside > 0]
            mask |= inside
        # the label banner over an image isn't in the image file
        for _, r in rows[rows["element"] == "label"].iterrows():
            L, T, R, B = (int(round(r[c] * SCALE)) for c in ("left", "top", "right", "bottom"))
            mask[max(T, 0):max(B, 0), max(L, 0):max(R, 0)] = 0
        mask = cv2.erode(mask, np.ones((3, 3), np.uint8))  # edges are where timing errors bite
        if mask.mean() / 255 < MIN_CONTENT:
            return None
        return canvas, mask

    def scroll_speed(self, t_ns: int) -> float:
        """Scroll speed (screen px/s) around t_ns."""
        s = self.scroll[(self.scroll.index > t_ns - 100_000_000) & (self.scroll.index < t_ns + 100_000_000)]
        if len(s) < 2:
            return 0.0
        return float(abs(s.iloc[-1] - s.iloc[0]) / ((s.index[-1] - s.index[0]) / 1e9))


class Aligner:
    def __init__(self, run: Run):
        self.run = run
        w, h = int(run.screen.w * SCALE), int(run.screen.h * SCALE)
        u, v = np.meshgrid(np.arange(w), np.arange(h))
        self.grid = np.c_[u.ravel(), v.ravel()].astype(np.float64) / SCALE  # screen px of each working px
        self.shape = (h, w)
        self.S = np.diag([SCALE, SCALE, 1.0])

    def warp_scene(self, gray: np.ndarray, H: np.ndarray) -> np.ndarray:
        """The raw scene frame resampled onto the screen (working px), assuming mapping H."""
        Hinv = np.linalg.inv(H)
        p = np.c_[self.grid, np.ones(len(self.grid))] @ Hinv.T
        p = p[:, :2] / p[:, 2:]
        raw = self.run.rec.distort(p).astype(np.float32).reshape(*self.shape, 2)
        return cv2.remap(gray, raw[..., 0], raw[..., 1], cv2.INTER_LINEAR, borderValue=0).astype(np.float32)

    def usable(self, warped: np.ndarray, mask: np.ndarray) -> np.ndarray:
        """Known content that the video still resolves: the scene camera exposes for the room, so
        much of the screen is blown out."""
        valid = mask & ((warped > 0) & (warped < SATURATED)).astype(np.uint8) * 255
        return cv2.erode(valid, np.ones((3, 3), np.uint8))

    def align(self, gray: np.ndarray, H_prior: np.ndarray, canvas: np.ndarray, mask: np.ndarray,
              model: str = "shift"):
        """Refined scene->screen homography and the alignment's correlation (H None if it failed
        or moved further than MAX_SHIFT_MM from the prior). The warp between the prior and the
        content is a shift, or a shift then a shift + rotation. Freer warps (affine, homography)
        drift on the small patches of screen the video resolves."""
        warped = self.warp_scene(gray, H_prior)
        valid = self.usable(warped, mask)
        if valid.mean() / 255 < MIN_USABLE:
            return None, 0.0
        crit = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 100, 1e-5)
        W = np.eye(2, 3, dtype=np.float32)
        try:
            cc, W = cv2.findTransformECC(canvas, warped, W, cv2.MOTION_TRANSLATION, crit, valid, 5)
            if model == "shift+rotation":
                cc, W = cv2.findTransformECC(canvas, warped, W, cv2.MOTION_EUCLIDEAN, crit, valid, 5)
        except cv2.error:
            return None, 0.0
        W = np.vstack([W.astype(np.float64), [0, 0, 1]])
        # ECC: warped(W x) ~ canvas(x); x is the true screen position (working px), W x where the
        # prior put it
        H = np.linalg.inv(self.S) @ np.linalg.inv(W) @ self.S @ H_prior
        H /= H[2, 2]
        moved = np.linalg.norm(self.run.screen.mm(apply_h(H, apply_h(np.linalg.inv(H_prior), self.run.grid))
                                                  - self.run.grid), axis=1).max()
        return (H if moved <= MAX_SHIFT_MM else None), float(cc)


def feed_frames(run: Run) -> list[Frame]:
    return [f for f in run.frames if f.step == "feed"]


def read_frames(run: Run, indices) -> dict[int, np.ndarray]:
    with SceneVideo(run.rec.scene_video) as video:  # in order: seeking lands on the wrong frames
        return dict(video.gray(sorted(indices)))


def flow_chain(run: Run, by_i: dict, f0: Frame, f1: Frame) -> Optional[np.ndarray]:
    """f0's tag mapping carried to f1 by the cached flow (None if flow failed on the way)."""
    H = f0.pose.H
    for k in range(f0.i + 1, f1.i + 1):
        c = by_i.get(k)
        if c is None or c.G is None:
            return None
        H = H @ np.linalg.inv(c.G)
    return H


def main(rec: Path, session: Path, package: Path, out_dir: Path, every: int = 2):
    run = load_run(rec, session, out_dir)
    content, aligner = Content(run, package), Aligner(run)
    by_i = {f.i: f for f in run.frames}
    refs = [f for f in feed_frames(run) if f.ref][::every]
    print(f"{run.name}: {len(refs)} feed frames with a reference pose (every {every})")
    gray = read_frames(run, {f.i for f in refs})
    session_t = lambda f, lat_ms: f.t - run.offset_ns - int(lat_ms * 1e6)  # noqa: E731
    err = lambda f, H: float(np.mean(run.transfer_err_mm(f.pose.H, H)))  # noqa: E731
    res = {"run": run.name, "reference_frames": len(refs)}

    # 0. how much of the screen is known content, and how much of that the video resolves
    shares, known = [], 0
    for f in refs:
        c = content.at(session_t(f, 0))
        if c is not None:
            known += 1
            usable = aligner.usable(aligner.warp_scene(gray[f.i], f.pose.H), c[1])
            shares.append(float((usable > 0).mean() / max((c[1] > 0).mean(), 1e-9)))
    res["content_known_share"] = round(known / max(len(refs), 1), 3)
    res["content_resolved_share"] = stats(shares)
    print(f"0. Content known (images on screen, no sheet) in {known / max(len(refs), 1):.0%} of them; "
          f"of that content the video resolves (not blown out) a median {np.median(shares):.0%}")

    # 1. latency: shift-only alignment from the reference pose
    lat_rows, best = [], None
    for lat in LATENCIES_MS:
        errs = []
        for f in refs:
            c = content.at(session_t(f, lat))
            if c is not None:
                H, cc = aligner.align(gray[f.i], f.pose.H, *c)
                if H is not None and cc >= MIN_CC:
                    errs.append(err(f, H))
        s = stats(errs)
        lat_rows.append([f"{lat} ms", s["n"], s["median"], s["p90"]])
        if s["median"] is not None and (best is None or s["median"] < best[1]):
            best = (lat, s["median"])
    latency = best[0] if best else 0
    res["latency_ms"] = {"best": latency, "scan": lat_rows}
    print("\n" + table("1. Display latency: shift-only alignment from the reference pose, mm", lat_rows,
                       ["latency", "accepted", "median", "p90"]))

    # 2 and 3. agreement (N = 0) and bridging (N > 0): from the old tag pose, or from flow
    speeds = (0, 300, 1500, float("inf"))
    rows = []
    for n in PRIOR_FRAMES:
        cases = []
        for f in refs:
            p = by_i.get(f.i - n)
            if p is not None and p.pose is not None and p.segment == f.segment:
                c = content.at(session_t(f, latency))
                if c is not None:
                    cases.append((f, p, c, flow_chain(run, by_i, p, f) if n else p.pose.H))
        hold = [err(f, p.pose.H) for f, p, _, _ in cases]
        flow = [err(f, Hf) if Hf is not None else np.nan for f, _, _, Hf in cases]
        r = {"frames": len(cases), "keep_old_pose": stats(hold), "flow": stats(flow),
             "flow_failed": int(np.sum(np.isnan(flow)))}
        row = [n, len(cases), fmt(stats(hold)), fmt(stats(flow))]
        for model in MODELS:
            for start in ("old pose", "flow"):
                acc, out, by_speed = 0, [], {}
                for (f, p, c, Hf), h, fl in zip(cases, hold, flow):
                    prior, fallback = (p.pose.H, h) if start == "old pose" or Hf is None else (Hf, fl)
                    H, cc = aligner.align(gray[f.i], prior, *c, model=model)
                    if H is None or cc < MIN_CC:
                        out.append(fallback)
                        continue
                    acc += 1
                    out.append(err(f, H))
                    v = content.scroll_speed(session_t(f, latency))
                    band = next(f"{a}-{b}" if b != float("inf") else f"{a}+"
                                for a, b in zip(speeds[:-1], speeds[1:]) if v < b)
                    by_speed.setdefault(band, []).append(out[-1])
                key = f"{model} from {start}"
                r[key] = {"accepted": acc, "error": stats(out), "by_scroll_px_s": {b: stats(v) for b, v in sorted(by_speed.items())}}
                row.append(f"{acc / max(len(cases), 1):.0%}: {fmt(stats(out))}")
        rows.append(row)
        res[f"prior_{n}"] = r
        print(f"  prior {n} frames done", flush=True)
    print("\n" + table("2-3. Tags missed for N frames: error vs reference, mm (median / p90). Content columns: share"
                       " accepted, and error using content where accepted, else the starting estimate", rows,
                       ["N frames", "cases", "keep old pose", "flow", *[f"{m} from {s}" for m in MODELS
                                                                     for s in ("old pose", "flow")]]))
    for n in PRIOR_FRAMES:
        sp = res[f"prior_{n}"]["shift from old pose"]["by_scroll_px_s"]
        print(f"  shift from old pose, by scroll speed, N={n:>2}: " +
              "   ".join(f"{b} px/s {fmt(v)} (n={v['n']})" for b, v in sp.items()))

    # examples: expected content | scene with the old pose | after the shift | with the reference
    k = 0
    for f in refs:
        p = by_i.get(f.i - 8)
        c = content.at(session_t(f, latency))
        if k >= 4 or p is None or p.pose is None or c is None or err(f, p.pose.H) < 1.5:
            continue
        H, _ = aligner.align(gray[f.i], p.pose.H, *c)
        panels = [c[0], aligner.warp_scene(gray[f.i], p.pose.H)]
        panels += [aligner.warp_scene(gray[f.i], H)] if H is not None else []
        panels.append(aligner.warp_scene(gray[f.i], f.pose.H))
        cv2.imwrite(str(out_dir / f"content_example_{k}.png"), np.hstack([np.clip(x, 0, 255).astype(np.uint8) for x in panels]))
        k += 1
    out = out_dir / "content_results.json"
    out.write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(f"\nsaved {out} (example images: expected | old pose | content shift | reference)")


def fmt(s: dict) -> str:
    return f"{s['median']} / {s['p90']}" if s["n"] else "-"


if __name__ == "__main__":
    if len(sys.argv) not in (5, 6):
        sys.exit(__doc__)
    main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]),
         int(sys.argv[5]) if len(sys.argv) == 6 else 2)
