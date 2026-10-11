"""Reading a Neon recording in Companion's native format (the folder copied off the phone)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

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
