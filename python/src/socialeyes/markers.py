"""AprilTag (tag36h11) generation and detection.

tag36h11 is the family used by Pupil Labs' Marker Mapper, so the same printed
case works with Pupil Cloud and with this package's own pipeline. Generation and
detection use OpenCV's aruco module (``DICT_APRILTAG_36h11``).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

CELLS = 8  # 6x6 data cells + 1-cell black border on each side
QUIET = 2  # white quiet-zone cells added around the tag (detector needs >= 1)


def _dictionary():
    return cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_APRILTAG_36h11)


def tag_image(tag_id: int, px_per_cell: int = 10, quiet_cells: int = QUIET) -> np.ndarray:
    """Tag bitmap (uint8, 0/255) including a white quiet zone."""
    side = CELLS * px_per_cell
    img = cv2.aruco.generateImageMarker(_dictionary(), int(tag_id), side, borderBits=1)
    pad = quiet_cells * px_per_cell
    return cv2.copyMakeBorder(img, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=255)


def write_tag_png(tag_id: int, path: Path, px_per_cell: int = 10) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ok = cv2.imwrite(str(path), tag_image(tag_id, px_per_cell))
    if not ok:
        raise OSError(f"could not write {path}")


@dataclass
class Detection:
    tag_id: int
    corners: np.ndarray  # (4, 2) TL, TR, BR, BL in the tag's own orientation (image px)


def make_detector() -> cv2.aruco.ArucoDetector:
    params = cv2.aruco.DetectorParameters()
    params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
    params.cornerRefinementWinSize = 3
    # Tags on a phone are small in the scene video; allow small candidates.
    params.minMarkerPerimeterRate = 0.01
    params.adaptiveThreshWinSizeMin = 3
    params.adaptiveThreshWinSizeMax = 33
    params.adaptiveThreshWinSizeStep = 6
    return cv2.aruco.ArucoDetector(_dictionary(), params)


def detect(gray: np.ndarray, detector: cv2.aruco.ArucoDetector | None = None) -> list[Detection]:
    detector = detector or make_detector()
    corners, ids, _ = detector.detectMarkers(gray)
    if ids is None:
        return []
    return [Detection(int(i), c.reshape(4, 2).astype(float)) for c, i in zip(corners, ids.ravel())]


# ---------------------------------------------------------------- printable case


def case_sheet_svg(
    phone_width_mm: float,
    phone_height_mm: float,
    tag_ids: list[int],
    tag_size_mm: float,
    gap_mm: float = 2.0,
) -> tuple[str, dict]:
    """A printable frame (1:1 scale SVG) that surrounds the phone with tags.

    Tags are placed on the top and bottom strips (and the sides if more than
    four ids are given). Print at 100% scale on sticker paper and stick on a
    flat frame/case flush with the screen; measure a tag after printing to
    confirm the scale. ``tag_size_mm`` is the black-border edge length.

    Returns (svg_text, layout) where layout records tag positions in mm relative
    to the phone's top-left corner (informational; the analysis self-calibrates
    tag positions from the marker_calibration step).
    """
    if len(tag_ids) < 4:
        raise ValueError("use at least 4 case tags")
    cell = tag_size_mm / CELLS
    quiet = QUIET * cell
    strip = tag_size_mm + 2 * quiet  # strip width needed around the phone
    W = phone_width_mm + 2 * strip
    H = phone_height_mm + 2 * strip

    # Centres of tags (mm, sheet coordinates): four corners, then the sides.
    c = strip / 2
    positions = [(c, c), (W - c, c), (W - c, H - c), (c, H - c)]
    pitch = strip + gap_mm
    for k in range(len(tag_ids) - 4):
        row = k // 2  # 0, 0, 1, 1, ... alternating left/right, spreading out from the middle
        offset = ((row + 1) // 2) * pitch * (1 if row % 2 == 0 else -1)
        positions.append((c if k % 2 == 0 else W - c, H / 2 + offset))

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.2f}mm" height="{H:.2f}mm" '
        f'viewBox="0 0 {W:.3f} {H:.3f}">',
        f'<rect x="0" y="0" width="{W:.3f}" height="{H:.3f}" fill="white" stroke="#999" stroke-width="0.2"/>',
        f'<rect x="{strip:.3f}" y="{strip:.3f}" width="{phone_width_mm:.3f}" height="{phone_height_mm:.3f}" '
        f'fill="none" stroke="#f00" stroke-width="0.3" stroke-dasharray="2,1"/>',
        f'<text x="{W / 2:.1f}" y="{H / 2:.1f}" font-size="4" text-anchor="middle" fill="#f00">'
        f"phone cut-out {phone_width_mm:.1f} x {phone_height_mm:.1f} mm</text>",
    ]
    layout = {"tag_size_mm": tag_size_mm, "phone_width_mm": phone_width_mm,
              "phone_height_mm": phone_height_mm, "tags": []}
    for tid, (cx, cy) in zip(tag_ids, positions):
        bits = cv2.aruco.generateImageMarker(_dictionary(), int(tid), CELLS, borderBits=1)
        x0, y0 = cx - tag_size_mm / 2, cy - tag_size_mm / 2
        for r in range(CELLS):
            for c in range(CELLS):
                if bits[r, c] < 128:
                    parts.append(
                        f'<rect x="{x0 + c * cell:.4f}" y="{y0 + r * cell:.4f}" '
                        f'width="{cell + 0.01:.4f}" height="{cell + 0.01:.4f}" fill="black"/>'
                    )
        layout["tags"].append({"id": tid, "center_mm": [round(cx - strip, 3), round(cy - strip, 3)]})
    parts.append("</svg>")
    return "\n".join(parts), layout
