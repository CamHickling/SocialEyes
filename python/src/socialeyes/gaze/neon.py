"""Reading a Neon recording in Companion's native format (the folder copied off the phone)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import cv2
import numpy as np

SCENE_VIDEO = "Neon Scene Camera v1 ps1.mp4"

_CALIB_DTYPE = np.dtype([
    ("version", "u1"), ("serial", "6S"),
    ("scene_camera_matrix", "(3,3)<f8"), ("scene_distortion_coefficients", "8<f8"),
    ("scene_extrinsics_affine_matrix", "(4,4)<f8"),
    ("right_camera_matrix", "(3,3)<f8"), ("right_distortion_coefficients", "8<f8"),
    ("right_extrinsics_affine_matrix", "(4,4)<f8"),
    ("left_camera_matrix", "(3,3)<f8"), ("left_distortion_coefficients", "8<f8"),
    ("left_extrinsics_affine_matrix", "(4,4)<f8"),
    ("crc", "<u4"),
])


class NeonFormatError(ValueError):
    pass


@dataclass
class NeonRecording:
    path: Path
    K: np.ndarray            # scene camera matrix
    dist: np.ndarray         # scene camera distortion coefficients
    gaze: np.ndarray         # (n, 2) gaze in scene pixels (distorted, as recorded)
    gaze_t: np.ndarray       # (n,) Unix ns
    scene_t: np.ndarray      # (frames,) Unix ns of each scene video frame

    @property
    def scene_video(self) -> Path:
        return self.path / SCENE_VIDEO

    def undistort(self, pts: np.ndarray) -> np.ndarray:
        """Scene pixels as recorded -> undistorted scene pixels (same camera matrix)."""
        return undistort(pts, self.K, self.dist)

    def distort(self, pts: np.ndarray) -> np.ndarray:
        """Undistorted scene pixels -> pixels in the recorded video frame."""
        xn = np.hstack([pts, np.ones((len(pts), 1))]) @ np.linalg.inv(self.K).T
        return cv2.projectPoints(xn, np.zeros(3), np.zeros(3), self.K, self.dist)[0].reshape(-1, 2)


class SceneVideo:
    """Scene video frames by index, decoded in order. Seeking (CAP_PROP_POS_FRAMES) can't be
    trusted on Companion's videos: their frame rate varies, and a seek lands up to many frames
    away from the one asked for (12 Oct recordings: tag_ladder B, tag_bars run 2). Going back
    reopens the file; going forward decodes and drops the frames in between."""

    def __init__(self, path: str | Path):
        self.path = str(path)
        self._cap, self._next = None, 0

    def _open(self) -> None:
        self.close()
        self._cap, self._next = cv2.VideoCapture(self.path), 0
        if not self._cap.isOpened():
            raise NeonFormatError(f"can't open {self.path}")

    def gray(self, indices) -> "Iterator[tuple[int, np.ndarray]]":
        """(index, grey image) for each frame index asked for (in increasing order), until the video ends."""
        for i in indices:
            i = int(i)
            if self._cap is None or i < self._next:
                self._open()
            while self._next < i:
                if not self._cap.grab():
                    return
                self._next += 1
            ok, img = self._cap.read()
            if not ok:
                return
            self._next += 1
            yield i, cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def __enter__(self) -> "SceneVideo":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def undistort(pts: np.ndarray, K: np.ndarray, dist: np.ndarray) -> np.ndarray:
    pts = np.asarray(pts, np.float64).reshape(-1, 1, 2)
    return cv2.undistortPoints(pts, K, dist, P=K).reshape(-1, 2)


def read_recording(path: str | Path) -> NeonRecording:
    path = Path(path)
    for name in ("calibration.bin", "gaze ps1.raw", "gaze ps1.time", SCENE_VIDEO, "Neon Scene Camera v1 ps1.time"):
        if not (path / name).exists():
            raise NeonFormatError(f"{path}: no '{name}' (is this a Neon recording folder copied off the phone?)")
    calib = np.fromfile(path / "calibration.bin", _CALIB_DTYPE)
    if not len(calib):
        raise NeonFormatError(f"{path}: calibration.bin is empty")
    gaze = np.fromfile(path / "gaze ps1.raw", "<f4").reshape(-1, 2).astype(np.float64)
    gaze_t = np.fromfile(path / "gaze ps1.time", "<u8").astype(np.int64)
    n = min(len(gaze), len(gaze_t))
    scene_t = np.fromfile(path / "Neon Scene Camera v1 ps1.time", "<u8").astype(np.int64)
    return NeonRecording(path, calib[0]["scene_camera_matrix"].copy(), calib[0]["scene_distortion_coefficients"].copy(),
                         gaze[:n], gaze_t[:n], scene_t)


@dataclass
class NeonImu:
    t: np.ndarray            # (n,) Unix ns
    gyro: np.ndarray         # (n, 3) deg/s, in the IMU's axes
    accel: np.ndarray        # (n, 3) g
    quat: np.ndarray         # (n, 4) w, x, y, z: the module's orientation (Neon's own fusion)


_IMU_DTYPE = np.dtype([("t", "<i8"), ("gyro", "<f4", 3), ("accel", "<f4", 3), ("quat", "<f4", 4)])

# Scene camera axes (x right, y down, z forward) from the IMU's (x right, y forward, z up): a
# 78 degree turn about x, the camera looking 12 degrees above the IMU's forward axis. Pupil Labs'
# Neon documentation gives the 12 degrees; the direction is from the data: fitted to the tags'
# motion while only the head turned (tag_ladder B, 12 Oct), 7 degrees from this and 23.5 from the
# opposite tilt, which explained less of the motion (86% vs 91%).
_a = np.deg2rad(90 - 12)
CAMERA_FROM_IMU = np.array([[1, 0, 0], [0, np.cos(_a), -np.sin(_a)], [0, np.sin(_a), np.cos(_a)]])


def read_imu(path: str | Path) -> NeonImu:
    """The glasses' IMU (~110 Hz) from a native recording's 'imu ps1.raw' (see its imu.dtype)."""
    f = Path(path) / "imu ps1.raw"
    if not f.exists():
        raise NeonFormatError(f"{path}: no 'imu ps1.raw' (recorded with an older Companion app?)")
    a = np.fromfile(f, _IMU_DTYPE)
    return NeonImu(a["t"].astype(np.int64), a["gyro"].astype(np.float64), a["accel"].astype(np.float64),
                   a["quat"].astype(np.float64))
