"""CAM-165 option 5: can motion sensors keep track of the phone when the tags drop out?

Offline, on a recording with on-screen tags (a CAM-210 run, or a tag_ladder session):

    python scripts/imu_tracking_test.py NEON_FOLDER SESSION_FOLDER OUT_DIR

(OUT_DIR caches the tag scan; for CAM-210 runs use analysis_out/tracking_pnp/<run>, where
tracking_pnp_test.py left one.)

The phone moves in the scene camera's view because the head turns (the Neon IMU measures this),
because the hand turns the phone (the phone's gyroscope measures this, when the session logged
logging.sensors) and because either shifts sideways (neither measures this well). Two tests:

  1. Motion explained: how far the tags move in the image over 100 ms and 267 ms, and how much of
     that each sensor predicts (share of the squared motion explained; 1 = all, 0 = none, below
     0 = worse than predicting no motion). Per step (per hold on the tag ladder). Also fits the
     IMU->camera axes and time lag to the data and compares them with Pupil Labs' figures.
  2. Gap bridging: from a reference frame, predict the pose N frames later without tags and
     compare with that frame's reference (mm on the screen):
       hold         keep the last pose
       head         rotate the last pose by the head's rotation (Neon IMU)
       head+phone   and by the phone's own rotation (phone gyroscope; needs logging.sensors)
       flow         optical flow around the tags, chained (as in socialeyes gaze)
       flow+sensors flow, with frames where flow fails bridged by the gyroscopes

Results are printed and saved to OUT_DIR/imu_results.json.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from scipy.optimize import minimize

sys.path.insert(0, str(Path(__file__).parent))
from tracking_reference import Frame, Run, load_run, stats, table  # noqa: E402
from socialeyes.gaze.neon import CAMERA_FROM_IMU, NeonImu, read_imu  # noqa: E402

GAPS = (1, 3, 8, 15, 30, 60)
MOTION_FRAMES = (3, 8)
LAGS_MS = np.arange(-60, 61, 10)
# Android sensor axes (x right, y up, z out of the screen) -> the screen axes the poses use
# (x right, y down, z into the screen)
SCREEN_FROM_PHONE = np.diag([1.0, -1.0, -1.0])


def rotvec(R: np.ndarray) -> np.ndarray:
    return cv2.Rodrigues(R)[0].ravel()


def rot(v) -> np.ndarray:
    return cv2.Rodrigues(np.asarray(v, np.float64).reshape(3, 1))[0]


class Gyro:
    """A gyroscope's rotation between any two times (rates integrated once, held between samples)."""

    def __init__(self, t: np.ndarray, w_rad_s: np.ndarray):
        order = np.argsort(t)
        self.t, self.w = t[order], w_rad_s[order]
        self.R = np.empty((len(self.t), 3, 3))  # orientation at each sample, relative to the first
        self.R[0] = np.eye(3)
        for k in range(1, len(self.t)):
            self.R[k] = self.R[k - 1] @ rot(self.w[k - 1] * (self.t[k] - self.t[k - 1]) / 1e9)

    def _at(self, t: float) -> np.ndarray:
        k = max(int(np.searchsorted(self.t, t, side="right")) - 1, 0)
        return self.R[k] @ rot(self.w[k] * (t - self.t[k]) / 1e9)

    def delta(self, t0: int, t1: int, lag_ns: int = 0) -> Optional[np.ndarray]:
        """The sensor's rotation over [t0, t1] in its own axes (a vector fixed in the world goes
        from v to D^T v in sensor axes), or None if the samples don't cover it."""
        t0, t1 = t0 + lag_ns, t1 + lag_ns
        if t0 < self.t[0] or t1 > self.t[-1]:
            return None
        return self._at(t0).T @ self._at(t1)


class Sensors:
    def __init__(self, run: Run, imu: NeonImu, Q: np.ndarray = CAMERA_FROM_IMU, lag_ns: int = 0):
        self.head = Gyro(imu.t, np.deg2rad(imu.gyro))
        self.Q, self.lag_ns = Q, lag_ns
        s = run.session.sensors
        g = s[s["sensor"] == "gyro"] if s is not None else None
        self.phone = Gyro(g["t_ns"].to_numpy(np.int64) + run.offset_ns, g[["x", "y", "z"]].to_numpy(float)) \
            if g is not None and len(g) else None

    def d_head(self, t0: int, t1: int) -> Optional[np.ndarray]:
        """Head rotation in camera axes."""
        D = self.head.delta(t0, t1, self.lag_ns)
        return None if D is None else self.Q @ D @ self.Q.T

    def d_phone(self, t0: int, t1: int) -> Optional[np.ndarray]:
        """Phone rotation in screen axes."""
        D = self.phone.delta(t0, t1) if self.phone else None
        return None if D is None else SCREEN_FROM_PHONE @ D @ SCREEN_FROM_PHONE.T


def predict(R: np.ndarray, t: np.ndarray, D_head: Optional[np.ndarray], D_phone: Optional[np.ndarray],
            pivot: Optional[np.ndarray] = None):
    """Phone pose (phone -> camera) after the head turned by D_head (camera axes, about the camera)
    and the phone by D_phone (screen axes, about `pivot` in phone mm: where the hand holds it)."""
    if D_phone is not None:
        p = np.zeros(3) if pivot is None else pivot
        t = t + R @ (p - D_phone @ p)
        R = R @ D_phone
    if D_head is not None:
        R, t = D_head.T @ R, D_head.T @ t
    return R, t


def homography(run: Run, R: np.ndarray, t: np.ndarray) -> np.ndarray:
    H = np.linalg.inv(run.rec.K @ np.column_stack([R[:, 0], R[:, 1], t]) @ run.screen.S)
    return H / H[2, 2]


def pivot_mm(run: Run) -> np.ndarray:
    """Roughly where the phone turns about: the lower middle of the screen (the holding hand)."""
    return np.array([*run.screen.mm(np.array([run.screen.w / 2, run.screen.h * 0.75])), 0.0])


# ---------------------------------------------------------------- 1. motion explained

def motion_cases(run: Run, n: int):
    """(f0, f1, tag id) where a tag was found in both frames n apart and f0 has a pose."""
    by_i = {f.i: f for f in run.frames}
    for f0 in run.frames:
        f1 = by_i.get(f0.i + n)
        if f0.pose is None or f1 is None or f1.segment != f0.segment:
            continue
        for k in set(f0.dets) & set(f1.dets):
            yield f0, f1, k


def project(run: Run, R, t, P_mm):
    q = run.rec.K @ (R @ P_mm + t)
    return q[:2] / q[2]


def fit_head_axes(run: Run, sensors: Sensors) -> dict:
    """IMU->camera rotation and lag that best explain the tags' image motion over 100 ms, using
    the head's rotation alone (only meaningful when the head turned while the phone stayed put)."""
    K, Ki = run.rec.K, np.linalg.inv(run.rec.K)
    cases = list(motion_cases(run, 3))
    p0 = np.array([f0.dets[k].mean(0) for f0, _, k in cases])
    obs = np.array([f1.dets[k].mean(0) for _, f1, k in cases]) - p0
    rays = np.c_[p0, np.ones(len(p0))] @ Ki.T
    base = float(np.sum(obs ** 2))
    best = None
    for lag in LAGS_MS:
        D = [sensors.head.delta(f0.t, f1.t, int(lag * 1e6)) for f0, f1, _ in cases]
        ok = np.array([d is not None for d in D])
        if ok.sum() < 20:
            continue
        Ds = np.array([d for d in D if d is not None])

        def cost(v):
            Q = rot(v)
            Dc = np.einsum("ij,njk,lk->nil", Q, Ds, Q)
            q = np.einsum("nji,nj->ni", Dc, rays[ok])
            return float(np.sum((obs[ok] - (q[:, :2] / q[:, 2:] * K[0, 0] + K[:2, 2] - p0[ok])) ** 2))

        starts = [rotvec(CAMERA_FROM_IMU)] + [rotvec(CAMERA_FROM_IMU @ rot(v)) for v in np.eye(3) * np.pi / 2]
        o = min((minimize(cost, s, method="Powell") for s in starts), key=lambda r: r.fun)
        explained = 1 - o.fun / float(np.sum(obs[ok] ** 2))
        doc = 1 - cost(rotvec(CAMERA_FROM_IMU)) / float(np.sum(obs[ok] ** 2))
        if best is None or explained > best["explained_fitted"]:
            best = {"lag_ms": float(lag), "explained_fitted": round(explained, 3), "explained_documented": round(doc, 3),
                    "fitted_vs_documented_deg": round(float(np.rad2deg(np.linalg.norm(rotvec(rot(o.x) @ CAMERA_FROM_IMU.T)))), 1),
                    "camera_from_imu": rot(o.x).round(4).tolist()}
    return best or {"note": "too few frames"}


def test_motion(run: Run, sensors: Sensors) -> dict:
    """Per segment and window: tag image motion (px) and the share explained by each sensor."""
    piv = pivot_mm(run)
    out = {}
    for n in MOTION_FRAMES:
        by_seg: dict[str, dict[str, list]] = {}
        for f0, f1, k in motion_cases(run, n):
            P = np.array([*run.screen.mm(f0.tags[k].mean(0)), 0.0])
            p0 = project(run, f0.pose.R, f0.pose.t, P)   # where the pose puts the tag now
            obs = f1.dets[k].mean(0) - f0.dets[k].mean(0)
            Dh, Dp = sensors.d_head(f0.t, f1.t), sensors.d_phone(f0.t, f1.t)
            preds = {"head": (Dh, None)}
            if sensors.phone:
                preds["phone"] = (None, Dp)
                preds["head+phone"] = (Dh, Dp)
            row = by_seg.setdefault(f0.segment, {"obs": [], **{m: [] for m in preds}})
            row["obs"].append(obs)
            for m, (a, b) in preds.items():
                if (a is None and m != "phone") or (b is None and m != "head"):
                    row[m].append(np.full(2, np.nan))
                    continue
                R, t = predict(f0.pose.R, f0.pose.t, a, b, piv)
                row[m].append(obs - (project(run, R, t, P) - p0))
        res = {}
        for seg, row in by_seg.items():
            obs = np.array(row["obs"])
            mag = np.linalg.norm(obs, axis=1)
            r = {"cases": len(obs), "motion_px": {"median": round(float(np.median(mag)), 2),
                                                 "p90": round(float(np.percentile(mag, 90)), 2)}}
            for m in row:
                if m == "obs":
                    continue
                resid = np.array(row[m])
                ok = np.all(np.isfinite(resid), axis=1)
                r[f"explained_{m}"] = round(float(1 - np.sum(resid[ok] ** 2) / np.sum(obs[ok] ** 2)), 3) if ok.any() else None
            res[seg] = r
        out[f"{n} frames ({n * 1000 / 30:.0f} ms)"] = res
    return out


# ---------------------------------------------------------------- 2. gap bridging

def recover_pose(run: Run, H: np.ndarray):
    """Pose (R, t) from a scene->screen homography (inverse of homography())."""
    A = np.linalg.inv(run.rec.K) @ np.linalg.inv(H) @ np.linalg.inv(run.screen.S)
    s = 1 / np.linalg.norm(A[:, 0])
    r1, r2, t = A[:, 0] * s, A[:, 1] * s, A[:, 2] * s
    if t[2] < 0:
        r1, r2, t = -r1, -r2, -t
    U, _, Vt = np.linalg.svd(np.column_stack([r1, r2, np.cross(r1, r2)]))
    return U @ Vt, t


def test_gaps(run: Run, sensors: Sensors) -> dict:
    by_i = {f.i: f for f in run.frames}
    piv = pivot_mm(run)
    methods = ["hold", "head", "flow", "flow+sensors"] + (["head+phone"] if sensors.phone else [])
    errs = {n: {m: [] for m in methods} for n in GAPS}
    flow_missing = {n: [] for n in GAPS}

    for f0 in run.frames:
        if not f0.ref:
            continue
        for n in GAPS:
            f1 = by_i.get(f0.i + n)
            chain = [by_i.get(f0.i + k) for k in range(1, n + 1)]
            if f1 is None or not f1.ref or any(c is None or c.segment != f0.segment for c in chain):
                continue
            R0, t0, H_ref = f0.pose.R, f0.pose.t, f1.pose.H
            err = lambda H: float(np.mean(run.transfer_err_mm(H_ref, H)))  # noqa: E731
            errs[n]["hold"].append(err(f0.pose.H))
            Dh, Dp = sensors.d_head(f0.t, f1.t), sensors.d_phone(f0.t, f1.t)
            if Dh is not None:
                errs[n]["head"].append(err(homography(run, *predict(R0, t0, Dh, None))))
                if sensors.phone and Dp is not None:
                    errs[n]["head+phone"].append(err(homography(run, *predict(R0, t0, Dh, Dp, piv))))
            # flow chained frame by frame; a step where flow failed is bridged by the gyros
            H_flow, H_mix, prev, missing = f0.pose.H, f0.pose.H, f0, 0
            for c in chain:
                if c.G is not None:
                    G_inv = np.linalg.inv(c.G)
                    H_flow = None if H_flow is None else H_flow @ G_inv
                    H_mix = None if H_mix is None else H_mix @ G_inv
                else:
                    missing += 1
                    H_flow = None
                    dh, dp = sensors.d_head(prev.t, c.t), sensors.d_phone(prev.t, c.t)
                    H_mix = None if H_mix is None or dh is None else homography(run, *predict(*recover_pose(run, H_mix), dh, dp, piv))
                prev = c
            flow_missing[n].append(missing / n)
            if H_flow is not None:
                errs[n]["flow"].append(err(H_flow))
            if H_mix is not None:
                errs[n]["flow+sensors"].append(err(H_mix))
    return {f"{n} frames ({n * 1000 / 30:.0f} ms)": {**{m: stats(v) for m, v in errs[n].items()},
                                                     "flow_missing_share": round(float(np.mean(flow_missing[n])), 3)
                                                     if flow_missing[n] else None}
            for n in GAPS}


# ---------------------------------------------------------------- main

def check_units(imu: NeonImu) -> float:
    """Gyro integrated over 1 s vs Neon's own orientation quaternion: ratio of the rotation
    angles (1.0 when the gyro really is in deg/s)."""
    g = Gyro(imu.t, np.deg2rad(imu.gyro))
    ratios = []
    for k in range(0, len(imu.t) - 110, 110):
        ang_q = 2 * np.arccos(min(abs(float(np.dot(imu.quat[k], imu.quat[k + 104]))), 1.0))
        if ang_q > np.deg2rad(5):
            ratios.append(np.linalg.norm(rotvec(g.delta(int(imu.t[k]), int(imu.t[k + 104])))) / ang_q)
    return round(float(np.median(ratios)), 3) if ratios else float("nan")


def main(rec: Path, session: Path, out_dir: Path):
    run = load_run(rec, session, out_dir)
    imu = read_imu(rec)
    sensors = Sensors(run, imu)
    res = {"run": run.name, "gyro_units_check": check_units(imu), "phone_sensors": sensors.phone is not None}
    print(f"{run.name}: Neon gyro integrated / Neon orientation = {res['gyro_units_check']} (1.0 = deg/s as expected)")
    print("phone gyroscope:", "yes" if sensors.phone else "not logged (logging.sensors was off)")

    axes = fit_head_axes(run, sensors)
    res["head_axes"] = axes
    print(f"\nIMU axes/lag fitted to the tags' motion: lag {axes.get('lag_ms')} ms, explains "
          f"{axes.get('explained_fitted')} (documented axes: {axes.get('explained_documented')}); "
          f"fitted axes are {axes.get('fitted_vs_documented_deg')} deg from Pupil Labs' figures")

    motion = test_motion(run, sensors)
    res["motion"] = motion
    for win, segs in motion.items():
        ms = [m for m in next(iter(segs.values())) if m.startswith("explained_")]
        rows = [[seg, r["cases"], f"{r['motion_px']['median']} / {r['motion_px']['p90']}"] + [r[m] for m in ms]
                for seg, r in segs.items()]
        print("\n" + table(f"1. Tag motion over {win}, px (median / p90), and share explained", rows,
                           ["segment", "cases", "motion px"] + [m.replace("explained_", "") for m in ms]))

    gaps = test_gaps(run, sensors)
    res["gaps"] = gaps
    methods = [m for m in next(iter(gaps.values())) if m != "flow_missing_share"]
    rows = [[name] + [f"{g[m]['median']} / {g[m]['p90']}" if g[m]["n"] else "-" for m in methods]
            + [g["flow_missing_share"]] for name, g in gaps.items()]
    print("\n" + table("2. Gap bridging: error vs reference, mm on screen (median / p90)", rows,
                       ["gap"] + methods + ["flow missing"]))
    out = out_dir / "imu_results.json"
    out.write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(f"\nsaved {out}")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
