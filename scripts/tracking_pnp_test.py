"""CAM-165 phone-tracking test: can fewer tags + better maths keep track of the phone?

Offline, on accuracy_check recordings made with on-screen tags (CAM-210 runs 2 and 3: tags
0/1 in a band at the top of the screen, 2/3 at the bottom, during val1, feed and val2):

    python scripts/tracking_pnp_test.py data/cam210c/neon data/cam210c/app/<session> [out_dir]

Compares, per scene frame:
  H     a free scene->screen homography from the visible tags (what cam210_accuracy.py does)
  PnP   the phone's 3-D pose from the tags' corners, Neon's scene camera intrinsics and the tags'
        real positions in mm (IPPE + LM refinement); one tag is enough
  +flow PnP, with frames that have no usable tags bridged by optical flow of the non-scrolling
        top/bottom bands from the last good frame

Four tests:
  1. Tag subsets: on frames where all 4 tags were found, hide tags (top 2 only, bottom 2 only,
     one top + one bottom, one tag) and measure how far each method's mapping lands from the
     4-tag reference, in mm on the screen.
  2. Coverage: share of frames that get a usable mapping from the tags actually found.
  3. Gaps: from a good frame, bridge N frames with flow alone and compare with the reference.
  4. Gaze at the validation dots (no reference needed): error in mm and degrees per method,
     as recorded and after a per-session shift (leave-one-out over the dots).

Results are printed and saved to out_dir/results.json. Detections are cached in out_dir.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from cam210_accuracy import SceneVideo, black_square, detect, load_app, load_neon, undistort  # noqa: E402

ON_SCREEN_STEPS = ("val1", "feed", "val2")
TOP, BOTTOM = (0, 1), (2, 3)
SUBSETS = {
    "all 4": (0, 1, 2, 3),
    "top 2": TOP,
    "bottom 2": BOTTOM,
    "top-left + bottom-right": (0, 2),
    "top-left only": (0,),
    "bottom-right only": (2,),
}
H_MAX_ERR_SCREEN_PX = 15.0    # same rejection rule as cam210_accuracy.fit
PNP_MAX_RMS_SCENE_PX = 2.0    # PnP rejection: corner reprojection RMS in scene pixels
BAND_PX = 260                 # top/bottom bands (screen px) that don't scroll: used for flow
WINDOW_NS = 500_000_000       # gaze window before each validation tap (as in CAM-210)
GAP_FRAMES = (1, 3, 8, 15, 30, 60)


# ---------------------------------------------------------------- geometry

class Screen:
    """Screen pixels <-> mm on the screen plane (z = 0), from the device's real dpi."""

    def __init__(self, dev: dict):
        self.w, self.h = dev["screen_width_px"], dev["screen_height_px"]
        self.mm_per_px = np.array([25.4 / dev["xdpi"], 25.4 / dev["ydpi"]])
        self.S = np.diag([*self.mm_per_px, 1.0])  # screen px -> mm (homogeneous)
        xs, ys = np.linspace(54, self.w - 54, 5), np.linspace(120, self.h - 120, 9)
        self.grid = np.array([[x, y] for y in ys for x in xs])  # where gaze could land

    def mm(self, px: np.ndarray) -> np.ndarray:
        return px * self.mm_per_px


def h_apply(H, pts):
    return cv2.perspectiveTransform(np.asarray(pts, np.float64).reshape(-1, 1, 2), H).reshape(-1, 2)


def fit_h(dets: dict, tags: dict, ids) -> np.ndarray | None:
    """Scene->screen homography from the given tags (None if they fit badly)."""
    use = [i for i in ids if i in dets]
    if not use:
        return None
    src, dst = np.vstack([dets[i] for i in use]), np.vstack([tags[i] for i in use])
    H, _ = cv2.findHomography(src, dst, cv2.RANSAC if len(use) > 1 else 0, 3.0)
    if H is None:
        return None
    return H if np.linalg.norm(h_apply(H, src) - dst, axis=1).max() <= H_MAX_ERR_SCREEN_PX else None


def fit_pnp(dets: dict, tags: dict, ids, K, scr: Screen, prev_R=None):
    """Phone pose from the given tags -> (scene->screen homography, R, t), or None.
    With one tag IPPE gives two mirror-image poses: take the one nearest the previous pose,
    else the one with the lower reprojection error."""
    use = [i for i in ids if i in dets]
    if not use:
        return None
    img = np.vstack([dets[i] for i in use]).astype(np.float64)
    obj = np.hstack([scr.mm(np.vstack([tags[i] for i in use])), np.zeros((4 * len(use), 1))])
    n, rvecs, tvecs, errs = cv2.solvePnPGeneric(obj, img, K, None, flags=cv2.SOLVEPNP_IPPE)
    if not n:
        return None
    cands = []
    for rv, tv, e in zip(rvecs, tvecs, np.ravel(errs)):
        R = cv2.Rodrigues(rv)[0]
        if tv[2, 0] <= 0:
            continue
        cands.append((R, rv, tv, float(e)))
    if not cands:
        return None
    if prev_R is not None and len(use) == 1:
        R, rv, tv, _ = min(cands, key=lambda c: np.linalg.norm(cv2.Rodrigues(c[0] @ prev_R.T)[0]))
    else:
        R, rv, tv, _ = min(cands, key=lambda c: c[3])
    rv, tv = cv2.solvePnPRefineLM(obj, img, K, None, rv, tv)
    proj = cv2.projectPoints(obj, rv, tv, K, None)[0].reshape(-1, 2)
    if np.sqrt(np.mean(np.sum((proj - img) ** 2, axis=1))) > PNP_MAX_RMS_SCENE_PX:
        return None
    R = cv2.Rodrigues(rv)[0]
    screen_to_scene = K @ np.column_stack([R[:, 0], R[:, 1], tv.ravel()]) @ scr.S
    return np.linalg.inv(screen_to_scene), R, tv.ravel()


def transfer_err_mm(H_ref, H_est, scr: Screen) -> np.ndarray:
    """For each grid point: take its scene position under the reference, map it back with the
    estimate, and measure how far it lands from where it should (mm on the screen)."""
    scene = h_apply(np.linalg.inv(H_ref), scr.grid)
    return np.linalg.norm(scr.mm(h_apply(H_est, scene) - scr.grid), axis=1)


# ---------------------------------------------------------------- one pass over the video

def scan(rec: Path, session: Path, out: Path):
    """Detect tags in every frame of the on-screen steps, and the frame-to-frame motion of the
    top/bottom bands (optical flow). Cached in out/scan.json."""
    cache = out / "scan.json"
    if cache.exists():
        d = json.loads(cache.read_text(encoding="utf-8"))
        return [{"i": f["i"], "t": f["t"], "step": f["step"],
                 "dets": {int(k): np.array(v) for k, v in f["dets"].items()},
                 "G": None if f["G"] is None else np.array(f["G"])} for f in d]

    K, dist, _, _, scene_t = load_neon(rec)
    meta, events, offsets = load_app(session)
    off = offsets[0]
    scr = Screen(meta["device"])
    steps, layout = {}, {}
    for e in events:
        if e["type"] == "step_start":
            steps.setdefault(e["step_id"], {})["start"] = e["t_ns"] + off
        elif e["type"] == "step_end":
            steps.setdefault(e["step_id"], {})["end"] = e["t_ns"] + off
        elif e["type"] == "marker_layout" and e.get("on_screen"):
            layout = {int(k): black_square(v) for k, v in e["tags"].items()}
    bands = [np.array([[0, 0], [scr.w, 0], [scr.w, BAND_PX], [0, BAND_PX]], np.float64),
             np.array([[0, scr.h - BAND_PX], [scr.w, scr.h - BAND_PX], [scr.w, scr.h], [0, scr.h]], np.float64)]

    from pupil_apriltags import Detector
    detector = Detector(families="tag36h11", quad_decimate=1.0, decode_sharpening=0.25, nthreads=4)
    video = SceneVideo(rec / "Neon Scene Camera v1 ps1.mp4")
    frames = []
    for step in ON_SCREEN_STEPS:
        if step not in steps:
            continue
        end = steps[step].get("end", scene_t[-1])  # no step_end when the session was stopped
        idx = np.where((scene_t >= steps[step]["start"]) & (scene_t <= end))[0]
        prev_gray, last_H = None, None
        for n, (i, gray) in enumerate(video.gray(idx)):
            dets = detect(detector, gray, K, dist)
            G = None
            if prev_gray is not None and last_H is not None:
                G = band_flow(prev_gray, gray, last_H, bands, K, dist)
            H = fit_h(dets, layout, layout)
            if H is not None:
                last_H = H
            elif G is not None:
                last_H = last_H @ np.linalg.inv(G)
            frames.append({"i": int(i), "t": int(scene_t[i]), "step": step, "dets": dets, "G": G})
            prev_gray = gray
            if n % 300 == 0:
                print(f"  {step}: frame {n}/{len(idx)}", flush=True)
    cache.write_text(json.dumps([{**f, "dets": {k: v.tolist() for k, v in f["dets"].items()},
                                  "G": None if f["G"] is None else f["G"].tolist()} for f in frames]), encoding="utf-8")
    return frames


def distort(pts, K, dist):
    """Undistorted scene pixels -> pixels in the raw (distorted) video frame."""
    xn = np.hstack([pts, np.ones((len(pts), 1))]) @ np.linalg.inv(K).T
    return cv2.projectPoints(xn, np.zeros(3), np.zeros(3), K, dist)[0].reshape(-1, 2)


def band_flow(prev, cur, H_prev, bands, K, dist):
    """Homography taking (undistorted) scene points in the previous frame to this frame, from
    features tracked inside the top/bottom bands (they don't scroll with the feed)."""
    mask = np.zeros_like(prev)
    Hinv = np.linalg.inv(H_prev)
    for b in bands:
        poly = distort(h_apply(Hinv, b), K, dist)
        cv2.fillConvexPoly(mask, np.round(poly).astype(np.int32), 255)
    mask = cv2.dilate(mask, np.ones((15, 15), np.uint8))
    p0 = cv2.goodFeaturesToTrack(prev, 200, 0.01, 5, mask=mask)
    if p0 is None or len(p0) < 8:
        return None
    p1, st, _ = cv2.calcOpticalFlowPyrLK(prev, cur, p0, None, winSize=(21, 21), maxLevel=3)
    good = st.ravel() == 1
    if good.sum() < 8:
        return None
    a, b = undistort(p0[good].reshape(-1, 2), K, dist), undistort(p1[good].reshape(-1, 2), K, dist)
    G, inl = cv2.findHomography(a, b, cv2.RANSAC, 1.5)
    return G if G is not None and inl.sum() >= 8 else None


# ---------------------------------------------------------------- tests

def per_frame(frames, layout, ids, K, scr, method):
    """Scene->screen homography per frame from the tags in `ids` (None where it fails)."""
    out, prev_R = [], None
    for f in frames:
        if method == "H":
            out.append(fit_h(f["dets"], layout, ids))
        else:
            r = fit_pnp(f["dets"], layout, ids, K, scr, prev_R)
            out.append(None if r is None else r[0])
            if r is not None:
                prev_R = r[1]
    return out


def bridge(frames, Hs, max_gap_s=2.0):
    """Fill frames without a mapping by chaining band flow from the last good one."""
    out, last, last_t = [], None, None
    for f, H in zip(frames, Hs):
        if H is not None:
            last, last_t = H, f["t"]
        elif last is not None and f["G"] is not None and f["t"] - last_t <= max_gap_s * 1e9:
            last = last @ np.linalg.inv(f["G"])
            H = last
        else:
            last = None if f["G"] is None else last
        out.append(H)
    return out


def test_subsets(frames, layout, K, scr, ref):
    rows = {}
    full = [n for n, f in enumerate(frames) if ref[n] is not None and all(i in f["dets"] for i in (0, 1, 2, 3))]
    sub = [frames[n] for n in full]
    for name, ids in SUBSETS.items():
        for method in ("H", "PnP"):
            Hs = per_frame(sub, layout, ids, K, scr, method)
            errs = np.array([transfer_err_mm(ref[n], H, scr) for n, H in zip(full, Hs) if H is not None])
            fails = sum(H is None for H in Hs)
            jit = jitter_mm(sub, Hs, scr)
            rows[f"{name} | {method}"] = {
                "frames": len(full), "failed": fails,
                "mean_mm_median": float(np.median(errs.mean(1))) if len(errs) else None,
                "mean_mm_p90": float(np.percentile(errs.mean(1), 90)) if len(errs) else None,
                "worst_point_mm_median": float(np.median(errs.max(1))) if len(errs) else None,
                "worst_point_mm_p90": float(np.percentile(errs.max(1), 90)) if len(errs) else None,
                "jitter_mm": jit,
            }
    return rows


def jitter_mm(frames, Hs, scr):
    """Frame-to-frame wobble: for consecutive frame triples (t-1, t, t+1) with mappings, how far
    the middle frame's grid (in the scene) is from the average of its neighbours', in screen mm."""
    d = []
    for k in range(1, len(frames) - 1):
        a, b, c = Hs[k - 1], Hs[k], Hs[k + 1]
        if a is None or b is None or c is None:
            continue
        if frames[k + 1]["i"] - frames[k - 1]["i"] != 2:
            continue
        pa, pb, pc = (h_apply(np.linalg.inv(H), scr.grid) for H in (a, b, c))
        resid = pb - (pa + pc) / 2
        scale = np.linalg.norm(scr.mm(h_apply(b, pb + resid) - scr.grid), axis=1)
        d.append(np.median(scale))
    return float(np.median(d)) if d else None


def test_coverage(frames, layout, K, scr):
    rows = {}
    for name, ids in (("all 4", (0, 1, 2, 3)), ("top 2", TOP), ("bottom 2", BOTTOM)):
        H = per_frame(frames, layout, ids, K, scr, "H")
        H2 = [h if h is not None and sum(i in f["dets"] for i in ids) >= 2 else None for f, h in zip(frames, H)]
        P = per_frame(frames, layout, ids, K, scr, "PnP")
        PB = bridge(frames, P)
        for step in ON_SCREEN_STEPS:
            sel = [n for n, f in enumerate(frames) if f["step"] == step]
            if not sel:
                continue
            frac = lambda xs: round(sum(xs[n] is not None for n in sel) / len(sel), 3)  # noqa: E731
            rows[f"{name} | {step}"] = {"frames": len(sel), "H (>=2 tags, current rule)": frac(H2),
                                        "PnP (>=1 tag)": frac(P), "PnP + flow": frac(PB)}
    return rows


def spanning_ref(frames, layout, K, scr):
    """PnP from every tag found, on frames with at least one top and one bottom tag. Agrees with
    the 4-tag homography to ~0.5 mm (test 1) and exists on far more frames."""
    P = per_frame(frames, layout, (0, 1, 2, 3), K, scr, "PnP")
    return [H if any(i in f["dets"] for i in TOP) and any(i in f["dets"] for i in BOTTOM) else None
            for f, H in zip(frames, P)]


def test_gaps(frames, ref, scr):
    """Start at a frame with a reference, then use only flow for N frames; compare with the reference."""
    res = {g: [] for g in GAP_FRAMES}
    for s in range(0, len(frames), 5):
        if ref[s] is None:
            continue
        H = ref[s]
        for k in range(1, max(GAP_FRAMES) + 1):
            n = s + k
            if n >= len(frames) or frames[n]["step"] != frames[s]["step"] or frames[n]["G"] is None:
                break
            H = H @ np.linalg.inv(frames[n]["G"])
            if k in res and ref[n] is not None:
                res[k].append(float(transfer_err_mm(ref[n], H, scr).mean()))
    return {f"{g} frames": {"n": len(v), "median_mm": float(np.median(v)) if v else None,
                            "p90_mm": float(np.percentile(v, 90)) if v else None} for g, v in res.items()}


def test_gaze(frames, layout, K, dist, scr, rec, session, configs):
    """Gaze accuracy at the validation dots for each mapping (mapping from configs[name] per frame)."""
    _, _, gaze, gaze_t, _ = load_neon(rec)
    meta, events, offsets = load_app(session)
    off = offsets[0]
    gaze_u = undistort(gaze, K, dist)
    Kinv = np.linalg.inv(K)
    ray = lambda p: (v := Kinv @ np.array([p[0], p[1], 1.0])) / np.linalg.norm(v)  # noqa: E731
    targets = {}
    for e in events:
        if e["type"] == "validation_target":
            targets[(e["step_id"], e["index"])] = {"xy": np.array([e["x_px"], e["y_px"]]), "shown": e["t_ns"] + off}
        elif e["type"] == "validation_tap" and e.get("on_target"):
            targets[(e["step_id"], e["index"])]["tap"] = e["t_ns"] + off
    ft = np.array([f["t"] for f in frames])
    out = {}
    for name, Hs in configs.items():
        good = np.array([H is not None for H in Hs])
        dots = []
        for key, t in sorted(targets.items()):
            if "tap" not in t:
                continue
            t0, t1 = max(t["tap"] - WINDOW_NS, t["shown"]), t["tap"]
            fsel = np.where((ft >= t0) & (ft <= t1) & good)[0]
            gsel = (gaze_t >= t0) & (gaze_t <= t1)
            if len(fsel) < 3 or not gsel.any():
                dots.append(None)
                continue
            mapped = [h_apply(Hs[fsel[np.argmin(np.abs(ft[fsel] - gt))]], g)[0] for g, gt in zip(gaze_u[gsel], gaze_t[gsel])]
            med = np.median(mapped, axis=0)
            Hm = Hs[fsel[len(fsel) // 2]]
            a, b = h_apply(np.linalg.inv(Hm), np.vstack([med, t["xy"]]))
            dots.append({"key": f"{key[0]}#{key[1]}", "d_px": med - t["xy"], "Hm": Hm, "xy": t["xy"],
                         "deg": float(np.degrees(np.arccos(np.clip(ray(a) @ ray(b), -1, 1))))})
        ok = [d for d in dots if d is not None]
        if not ok:
            out[name] = {"dots_usable": 0, "dots": len(dots)}
            continue
        mm = np.array([np.linalg.norm(scr.mm(d["d_px"])) for d in ok])
        deg = np.array([d["deg"] for d in ok])
        # per-session shift, leave-one-out: correct each dot by the mean shift of the others
        loo_mm, loo_deg = [], []
        for j, d in enumerate(ok):
            others = [o["d_px"] for k, o in enumerate(ok) if k != j]
            if not others:
                continue
            resid = d["d_px"] - np.mean(others, axis=0)
            loo_mm.append(np.linalg.norm(scr.mm(resid)))
            a, b = h_apply(np.linalg.inv(d["Hm"]), np.vstack([d["xy"] + resid, d["xy"]]))
            loo_deg.append(np.degrees(np.arccos(np.clip(ray(a) @ ray(b), -1, 1))))
        out[name] = {"dots_usable": len(ok), "dots": len(dots),
                     "raw_mm_median": float(np.median(mm)), "raw_deg_median": float(np.median(deg)),
                     "raw_deg_mean": float(deg.mean()),
                     "shift_corrected_mm_median": float(np.median(loo_mm)),
                     "shift_corrected_deg_median": float(np.median(loo_deg)),
                     "shift_corrected_deg_mean": float(np.mean(loo_deg))}
    return out


# ---------------------------------------------------------------- report

def table(title, rows, cols):
    print(f"\n{title}")
    w = max(len(k) for k in rows)
    print(f"{'':{w}}  " + "  ".join(f"{c[0]:>{c[2]}}" for c in cols))
    for k, r in rows.items():
        cells = []
        for _, key, width, fmt in cols:
            v = r.get(key)
            cells.append(f"{'-':>{width}}" if v is None else f"{v:>{width}{fmt}}")
        print(f"{k:{w}}  " + "  ".join(cells))


def main(rec: Path, session: Path, out: Path):
    out.mkdir(parents=True, exist_ok=True)
    K, dist, *_ = load_neon(rec)
    meta, events, _ = load_app(session)
    scr = Screen(meta["device"])
    layout = next({int(k): black_square(v) for k, v in e["tags"].items()}
                  for e in events if e["type"] == "marker_layout" and e.get("on_screen"))
    print(f"{rec.parent.name}: scanning the scene video (cached after the first run)...")
    frames = scan(rec, session, out)
    n_tags = np.bincount([sum(i in f["dets"] for i in layout) for f in frames], minlength=5)
    print(f"{len(frames)} frames in {', '.join(ON_SCREEN_STEPS)}; frames with 0..4 tags: {n_tags.tolist()}")

    ref = per_frame(frames, layout, (0, 1, 2, 3), K, scr, "H")
    ref = [H if all(i in f["dets"] for i in (0, 1, 2, 3)) else None for f, H in zip(frames, ref)]
    print(f"reference (all 4 tags, homography): {sum(H is not None for H in ref)} frames")

    res = {"run": rec.parent.name}
    res["subsets"] = test_subsets(frames, layout, K, scr, ref)
    table("1. Hide tags: mapping error vs the 4-tag reference (mm on screen; frames where all 4 were found)",
          res["subsets"], [("frames", "frames", 6, "d"), ("failed", "failed", 6, "d"),
                           ("avg mm (median)", "mean_mm_median", 15, ".2f"), ("avg mm (p90)", "mean_mm_p90", 12, ".2f"),
                           ("worst pt (median)", "worst_point_mm_median", 17, ".2f"),
                           ("worst pt (p90)", "worst_point_mm_p90", 14, ".2f"), ("jitter mm", "jitter_mm", 9, ".2f")])

    res["coverage"] = test_coverage(frames, layout, K, scr)
    table("2. Coverage: share of frames with a usable mapping, from the tags actually found",
          res["coverage"], [("frames", "frames", 6, "d"), ("H >=2 tags", "H (>=2 tags, current rule)", 10, ".0%"),
                            ("PnP", "PnP (>=1 tag)", 6, ".0%"), ("PnP+flow", "PnP + flow", 8, ".0%")])

    sref = spanning_ref(frames, layout, K, scr)
    print(f"\nreference for test 3 (PnP, >= 1 top and >= 1 bottom tag): {sum(H is not None for H in sref)} frames")
    res["gaps"] = test_gaps(frames, sref, scr)
    table("3. Bridging a gap with flow only (30 frames = 1 s): average mapping error vs the reference",
          res["gaps"], [("n", "n", 5, "d"), ("median mm", "median_mm", 9, ".2f"), ("p90 mm", "p90_mm", 7, ".2f")])

    P_all = per_frame(frames, layout, (0, 1, 2, 3), K, scr, "PnP")
    P_top = per_frame(frames, layout, TOP, K, scr, "PnP")
    configs = {
        "H, all 4 (current)": per_frame(frames, layout, (0, 1, 2, 3), K, scr, "H"),
        "PnP, all 4": P_all,
        "PnP + flow, all 4": bridge(frames, P_all),
        "H, top 2": per_frame(frames, layout, TOP, K, scr, "H"),
        "PnP, top 2": P_top,
        "PnP + flow, top 2": bridge(frames, P_top),
        "PnP, bottom 2": per_frame(frames, layout, BOTTOM, K, scr, "PnP"),
        "PnP, top-left only": per_frame(frames, layout, (0,), K, scr, "PnP"),
    }
    res["gaze"] = test_gaze(frames, layout, K, dist, scr, rec, session, configs)
    table("4. Gaze at the validation dots (no reference needed). 'Shift-corrected' = per-session shift, leave-one-out",
          res["gaze"], [("dots", "dots_usable", 4, "d"), ("raw mm", "raw_mm_median", 6, ".1f"),
                        ("raw deg", "raw_deg_median", 7, ".2f"),
                        ("corr mm", "shift_corrected_mm_median", 7, ".1f"),
                        ("corr deg", "shift_corrected_deg_median", 8, ".2f"),
                        ("corr deg mean", "shift_corrected_deg_mean", 13, ".2f")])
    (out / "results.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(f"\nresults: {out / 'results.json'}")


if __name__ == "__main__":
    rec, session = Path(sys.argv[1]), Path(sys.argv[2])
    main(rec, session, Path(sys.argv[3]) if len(sys.argv) > 3 else Path("analysis_out/tracking_pnp") / rec.parent.name)
