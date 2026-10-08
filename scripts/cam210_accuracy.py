"""CAM-210: how accurate is Neon gaze on the phone screen?

One-off analysis of an accuracy_check session plus the Neon recording made at
the same time (native format, copied straight off the phone):

    python scripts/cam210_accuracy.py data/cam210/neon data/cam210/app/<session> [case_sheet.json]

1. Clocks: Neon Companion and the app run on the same phone, so Neon's Unix-ns
   timestamps and the app's elapsed-realtime timestamps are tied together by the
   session's (elapsed_ns, wall_ms) anchors.
2. marker_calibration: screen tags (0-3, known screen pixels) and the printed
   case tags (10-15) are both visible; their homography puts the case tags'
   corners into screen pixels.
3. validation: the case tags alone give a scene->screen homography per frame;
   gaze in the last 500 ms before each dot's tap is mapped onto the screen and
   compared with the dot (px, mm, and degrees of visual angle).

This is a stand-in for the real pipeline (CAM-165), kept for reproducibility.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np

CASE_IDS = range(10, 16)
WINDOW_NS = 500_000_000      # gaze window before each tap
SKIP_BEFORE_TAP_NS = 0       # gaze leads the finger, so keep up to the tap itself

CALIB_DTYPE = np.dtype([
    ("version", "u1"), ("serial", "6S"),
    ("scene_camera_matrix", "(3,3)<f8"), ("scene_distortion_coefficients", "8<f8"),
    ("scene_extrinsics_affine_matrix", "(4,4)<f8"),
    ("right_camera_matrix", "(3,3)<f8"), ("right_distortion_coefficients", "8<f8"),
    ("right_extrinsics_affine_matrix", "(4,4)<f8"),
    ("left_camera_matrix", "(3,3)<f8"), ("left_distortion_coefficients", "8<f8"),
    ("left_extrinsics_affine_matrix", "(4,4)<f8"),
    ("crc", "<u4"),
])


def load_neon(rec: Path):
    calib = np.fromfile(rec / "calibration.bin", CALIB_DTYPE)[0]
    K, dist = calib["scene_camera_matrix"], calib["scene_distortion_coefficients"]
    gaze = np.fromfile(rec / "gaze ps1.raw", "<f4").reshape(-1, 2)
    gaze_t = np.fromfile(rec / "gaze ps1.time", "<u8").astype(np.int64)
    n = min(len(gaze), len(gaze_t))
    scene_t = np.fromfile(rec / "Neon Scene Camera v1 ps1.time", "<u8").astype(np.int64)
    return K, dist, gaze[:n], gaze_t[:n], scene_t


def load_app(session: Path):
    meta = json.loads((session / "session.json").read_text(encoding="utf-8"))
    events = [json.loads(line) for line in (session / "events.jsonl").read_text(encoding="utf-8").splitlines() if line]
    anchors = [meta["clock"]] + ([meta["end"]["clock"]] if meta.get("end", {}).get("clock") else [])
    offsets = [a["wall_ms"] * 1_000_000 - a["elapsed_ns"] for a in anchors]
    return meta, events, offsets


def undistort(pts: np.ndarray, K, dist) -> np.ndarray:
    return cv2.undistortPoints(pts.reshape(-1, 1, 2).astype(np.float64), K, dist, P=K).reshape(-1, 2)


def black_square(rect) -> np.ndarray:
    """Screen corners of a tag's black border (the drawn image has a 1/6 white margin)."""
    x0, y0, x1, y1 = rect
    return square((x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 3)


def frames_between(cap, scene_t, t0, t1, step=1):
    idx = np.where((scene_t >= t0) & (scene_t <= t1))[0][::step]
    for i in idx:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(i))
        ok, frame = cap.read()
        if ok:
            yield int(i), cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)


def detect(detector, gray, K, dist) -> dict[int, np.ndarray]:
    """Undistorted corners of each tag found, in pupil_apriltags' order (TR, TL, BL, BR for an upright tag)."""
    return {d.tag_id: undistort(np.asarray(d.corners), K, dist) for d in detector.detect(gray)}


def square(cx, cy, half) -> np.ndarray:
    """Corners of an upright square in the detector's order: TR, TL, BL, BR (y down; checked on a frame)."""
    return np.array([[cx + half, cy - half], [cx - half, cy - half], [cx - half, cy + half], [cx + half, cy + half]])


def nominal_case_positions(sheet: Path, meta: dict) -> dict[int, np.ndarray]:
    """Case-tag centres in screen pixels from the printed sheet, assuming the screen is centred in
    the cut-out. Used when the screen tags couldn't be read (e.g. an overexposed screen)."""
    sh = json.loads(sheet.read_text(encoding="utf-8"))
    dev = meta["device"]
    sw, shh = dev["screen_width_px"] / dev["xdpi"] * 25.4, dev["screen_height_px"] / dev["ydpi"] * 25.4
    ox, oy = (sh["phone_width_mm"] - sw) / 2, (sh["phone_height_mm"] - shh) / 2
    sx, sy = dev["xdpi"] / 25.4, dev["ydpi"] / 25.4
    half = sh["tag_size_mm"] / 2
    return {t["id"]: square(t["center_mm"][0] - ox, t["center_mm"][1] - oy, half) * [sx, sy] for t in sh["tags"]}


def main(rec: Path, session: Path, sheet: Path | None = None) -> None:
    K, dist, gaze, gaze_t, scene_t = load_neon(rec)
    meta, events, offsets = load_app(session)
    off = offsets[0]
    print(f"clock anchors disagree by {abs(offsets[-1] - offsets[0]) / 1e6:.1f} ms over the session")
    to_unix = lambda t: t + off  # noqa: E731
    dpi = (meta["device"]["xdpi"] + meta["device"]["ydpi"]) / 2
    px_per_mm = dpi / 25.4

    from pupil_apriltags import Detector
    detector = Detector(families="tag36h11", quad_decimate=1.0, decode_sharpening=0.25, nthreads=4)
    cap = cv2.VideoCapture(str(rec / "Neon Scene Camera v1 ps1.mp4"))
    print(f"scene video {int(cap.get(cv2.CAP_PROP_FRAME_COUNT))} frames, {len(scene_t)} timestamps; "
          f"gaze {len(gaze)} samples ({len(gaze) / ((gaze_t[-1] - gaze_t[0]) / 1e9):.0f} Hz)")

    # ---- 1. where the case tags sit in screen pixels, from each marker_calibration step
    by_step = {}
    for e in events:
        if e["type"] == "step_start":
            by_step.setdefault(e["step_id"], {})["start"] = e["t_ns"]
        elif e["type"] == "step_end":
            by_step.setdefault(e["step_id"], {})["end"] = e["t_ns"]
    layouts = [e for e in events if e["type"] == "marker_layout" and not e.get("on_screen")]
    # markers.on_screen: tags kept on screen during a step map gaze straight onto the screen
    on_screen = {e["step_id"]: {int(k): black_square(v) for k, v in e["tags"].items()}
                 for e in events if e["type"] == "marker_layout" and e.get("on_screen")}
    case_screen: dict[int, list[np.ndarray]] = {}
    for lay in layouts:
        st = by_step[lay["step_id"]]
        screen = {int(k): black_square(v) for k, v in lay["tags"].items()}
        n_used = 0
        for _, gray in frames_between(cap, scene_t, to_unix(st["start"]) + 300_000_000, to_unix(st["end"])):
            tags = detect(detector, gray, K, dist)
            src = [tags[i] for i in screen if i in tags]
            dst = [screen[i] for i in screen if i in tags]
            if len(src) < 2:
                continue
            H, _ = cv2.findHomography(np.vstack(src), np.vstack(dst), cv2.RANSAC, 3.0)
            for i in CASE_IDS:
                if i in tags:
                    case_screen.setdefault(i, []).append(cv2.perspectiveTransform(tags[i].reshape(-1, 1, 2), H).reshape(4, 2))
            n_used += 1
        print(f"{lay['step_id']}: {n_used} frames with >= 2 screen tags")
    if case_screen:
        case_pos = {i: np.median(np.stack(v), axis=0) for i, v in case_screen.items()}
        spread = {i: float(np.median(np.linalg.norm(np.stack(v) - case_pos[i], axis=2))) for i, v in case_screen.items()}
        print("case tags placed on screen:", {i: f"{len(case_screen[i])} frames, ±{spread[i]:.1f}px" for i in sorted(case_pos)})
    elif sheet:
        case_pos = nominal_case_positions(sheet, meta)
        print(f"screen tags unreadable: case tags placed from {sheet.name} (screen assumed centred in the cut-out)")
    elif on_screen:
        case_pos = {}
        print(f"no case tags: using on-screen tags during {', '.join(on_screen)}")
    else:
        sys.exit("no frame showed the screen tags; pass the case sheet's .json to use its nominal layout")

    # ---- 2. each validation dot: gaze before the tap, mapped to the screen by the case tags
    targets = {}
    for e in events:
        if e["type"] == "validation_target":
            targets[(e["step_id"], e["index"])] = {"x": e["x_px"], "y": e["y_px"], "shown": e["t_ns"]}
        elif e["type"] == "validation_tap" and e.get("on_target"):
            targets[(e["step_id"], e["index"])]["tap"] = e["t_ns"]

    gaze_u = undistort(gaze, K, dist)
    Kinv = np.linalg.inv(K)

    def ray(p):
        v = Kinv @ np.array([p[0], p[1], 1.0])
        return v / np.linalg.norm(v)

    rows = []
    for (step, idx), t in sorted(targets.items()):
        if "tap" not in t:
            continue
        t1 = to_unix(t["tap"]) - SKIP_BEFORE_TAP_NS
        t0 = max(t1 - WINDOW_NS, to_unix(t["shown"]))
        sel = (gaze_t >= t0) & (gaze_t <= t1)
        homos = []
        known = on_screen.get(step, case_pos)
        for fi, gray in frames_between(cap, scene_t, t0, t1):
            tags = detect(detector, gray, K, dist)
            src = [tags[i] for i in known if i in tags]
            if len(src) >= 2:
                H, _ = cv2.findHomography(np.vstack(src), np.vstack([known[i] for i in known if i in tags]), cv2.RANSAC, 3.0)
                if H is not None:
                    homos.append((scene_t[fi], H))
        if not homos or not sel.any():
            rows.append({"step": step, "index": idx, "x": t["x"], "y": t["y"], "ok": False})
            continue
        ft = np.array([h[0] for h in homos])
        mapped, angles = [], []
        target = np.array([[t["x"], t["y"]]])
        for g, gt in zip(gaze_u[sel], gaze_t[sel]):
            H = homos[int(np.argmin(np.abs(ft - gt)))][1]
            s = cv2.perspectiveTransform(g.reshape(1, 1, 2), H).reshape(2)
            tgt_scene = cv2.perspectiveTransform(target.reshape(1, 1, 2), np.linalg.inv(H)).reshape(2)
            mapped.append(s)
            angles.append(np.degrees(np.arccos(np.clip(ray(g) @ ray(tgt_scene), -1, 1))))
        mapped = np.array(mapped)
        med = np.median(mapped, axis=0)
        err_px = float(np.linalg.norm(med - target[0]))
        prec_px = float(np.sqrt(np.mean(np.sum((mapped - med) ** 2, axis=1))))
        # visual angle of the median gaze point vs. the dot, through the middle frame's homography
        Hm = homos[len(homos) // 2][1]
        med_scene = cv2.perspectiveTransform(med.reshape(1, 1, 2), np.linalg.inv(Hm)).reshape(2)
        tgt_scene = cv2.perspectiveTransform(target.reshape(1, 1, 2), np.linalg.inv(Hm)).reshape(2)
        err_deg = float(np.degrees(np.arccos(np.clip(ray(med_scene) @ ray(tgt_scene), -1, 1))))
        # viewing distance: screen px per degree around the dot
        px_per_deg = err_px / err_deg if err_deg > 0.05 else np.nan
        rows.append({"step": step, "index": idx, "x": t["x"], "y": t["y"], "ok": True,
                     "gx": float(med[0]), "gy": float(med[1]), "dx": float(med[0] - t["x"]), "dy": float(med[1] - t["y"]),
                     "err_px": err_px, "err_mm": err_px / px_per_mm, "err_deg": err_deg,
                     "prec_px": prec_px, "n_gaze": int(sel.sum()), "n_frames": len(homos), "px_per_deg": px_per_deg})

    print()
    print(f"{'dot':>8} {'x':>5} {'y':>5} | {'dx':>6} {'dy':>6} | {'err px':>6} {'mm':>5} {'deg':>5} | {'prec px':>7} {'frames':>6}")
    for r in rows:
        if not r["ok"]:
            print(f"{r['step']}#{r['index']:<3} {r['x']:5.0f} {r['y']:5.0f} | no usable frames or gaze")
            continue
        print(f"{r['step']}#{r['index']:<3} {r['x']:5.0f} {r['y']:5.0f} | {r['dx']:6.0f} {r['dy']:6.0f} | "
              f"{r['err_px']:6.0f} {r['err_mm']:5.1f} {r['err_deg']:5.2f} | {r['prec_px']:7.0f} {r['n_frames']:6d}")
    ok = [r for r in rows if r["ok"]]
    if ok:
        e = np.array([[r["err_px"], r["err_mm"], r["err_deg"], r["dx"], r["dy"], r["prec_px"]] for r in ok])
        centre = [r for r in ok if 0.2 < r["x"] / meta["device"]["screen_width_px"] < 0.8
                  and 0.2 < r["y"] / meta["device"]["screen_height_px"] < 0.8]
        print()
        print(f"accuracy (n={len(ok)}): mean {e[:, 0].mean():.0f} px = {e[:, 1].mean():.1f} mm = {e[:, 2].mean():.2f} deg "
              f"(median {np.median(e[:, 2]):.2f} deg, SD {e[:, 2].std(ddof=1):.2f}, max {e[:, 2].max():.2f})")
        print(f"systematic offset: dx {e[:, 3].mean():+.0f} px, dy {e[:, 4].mean():+.0f} px "
              f"({e[:, 3].mean() / px_per_mm:+.1f}, {e[:, 4].mean() / px_per_mm:+.1f} mm)")
        print(f"precision (RMS around each median): {np.median(e[:, 5]):.0f} px")
        if centre:
            c = np.array([r["err_deg"] for r in centre])
            edge = np.array([r["err_deg"] for r in ok if r not in centre])
            print(f"centre dots {len(c)}: {c.mean():.2f} deg; edge dots {len(edge)}: {edge.mean():.2f} deg")
        ppd = np.nanmedian([r["px_per_deg"] for r in ok])
        if np.isfinite(ppd):
            print(f"~{ppd:.0f} screen px per degree => viewing distance ~{ppd / px_per_mm / np.tan(np.radians(1)) / 10:.0f} cm")
        out = session / "cam210_accuracy.json"
        out.write_text(json.dumps(rows, indent=1), encoding="utf-8")
        print(f"\nper-dot results: {out}")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]) if len(sys.argv) > 3 else None)
