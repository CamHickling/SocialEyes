"""Areas of interest (AOIs) defined in image pixel coordinates.

Two input formats are accepted:

* SocialEyes native JSON::

    {"width": 1080, "height": 1350,
     "aois": [{"name": "waist", "polygon": [[x, y], ...]},
              {"name": "face",  "rect": [x0, y0, x1, y1]}]}

* LabelMe JSON (https://github.com/wkentaro/labelme), a free polygon annotation
  tool: shapes with shape_type "polygon" or "rectangle" are used, ``label`` is
  the AOI name.

Both are normalised to the native format when a study is compiled.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class AOI:
    name: str
    polygon: np.ndarray  # (N, 2) image pixel coordinates

    def contains(self, x: np.ndarray, y: np.ndarray) -> np.ndarray:
        return points_in_polygon(np.asarray(x, float), np.asarray(y, float), self.polygon)

    @property
    def area_px(self) -> float:
        p = self.polygon
        return 0.5 * abs(np.dot(p[:, 0], np.roll(p[:, 1], 1)) - np.dot(p[:, 1], np.roll(p[:, 0], 1)))


@dataclass(frozen=True)
class AOISet:
    width: int
    height: int
    aois: tuple[AOI, ...]

    def names(self) -> list[str]:
        return [a.name for a in self.aois]

    def to_json(self) -> dict:
        return {
            "width": self.width,
            "height": self.height,
            "aois": [{"name": a.name, "polygon": a.polygon.round(2).tolist()} for a in self.aois],
        }

    def label_points(self, x: np.ndarray, y: np.ndarray) -> np.ndarray:
        """Name of the first AOI containing each point ('' if none).

        AOIs are tested in file order, so list small AOIs (e.g. face) before
        larger ones that enclose them (e.g. body) to give them priority.
        """
        x = np.asarray(x, float)
        y = np.asarray(y, float)
        out = np.full(x.shape, "", dtype=object)
        free = np.ones(x.shape, bool)
        for a in self.aois:
            hit = free & a.contains(x, y)
            out[hit] = a.name
            free &= ~hit
        return out


def points_in_polygon(x: np.ndarray, y: np.ndarray, poly: np.ndarray) -> np.ndarray:
    """Vectorised even-odd ray casting test."""
    inside = np.zeros(np.broadcast(x, y).shape, bool)
    px, py = poly[:, 0], poly[:, 1]
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi, xj, yj = px[i], py[i], px[j], py[j]
        cond = (yi > y) != (yj > y)
        with np.errstate(divide="ignore", invalid="ignore"):
            xcross = (xj - xi) * (y - yi) / (yj - yi) + xi
        inside ^= cond & (x < xcross)
        j = i
    return inside


def _rect_to_poly(x0: float, y0: float, x1: float, y1: float) -> np.ndarray:
    x0, x1 = sorted((x0, x1))
    y0, y1 = sorted((y0, y1))
    return np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], float)


def load_aoi_file(path: Path) -> AOISet:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    aois: list[AOI] = []
    if "shapes" in data:  # LabelMe
        w, h = int(data["imageWidth"]), int(data["imageHeight"])
        for s in data["shapes"]:
            pts = np.asarray(s["points"], float)
            kind = s.get("shape_type", "polygon")
            if kind == "rectangle":
                poly = _rect_to_poly(*pts[0], *pts[1])
            elif kind == "polygon":
                poly = pts
            else:
                raise ValueError(f"{path}: unsupported LabelMe shape_type {kind!r} (use polygon or rectangle)")
            aois.append(AOI(str(s["label"]), poly))
    else:
        w, h = int(data["width"]), int(data["height"])
        for a in data["aois"]:
            if "polygon" in a:
                poly = np.asarray(a["polygon"], float)
            elif "rect" in a:
                poly = _rect_to_poly(*a["rect"])
            else:
                raise ValueError(f"{path}: AOI {a.get('name')!r} needs 'polygon' or 'rect'")
            aois.append(AOI(str(a["name"]), poly))
    for a in aois:
        if a.polygon.ndim != 2 or a.polygon.shape[1] != 2 or len(a.polygon) < 3:
            raise ValueError(f"{path}: AOI {a.name!r} must have at least 3 [x, y] points")
    names = [a.name for a in aois]
    if len(set(names)) != len(names):
        raise ValueError(f"{path}: duplicate AOI names {names}")
    return AOISet(w, h, tuple(aois))


def aoiset_from_json(data: dict) -> AOISet:
    return AOISet(
        int(data["width"]),
        int(data["height"]),
        tuple(AOI(a["name"], np.asarray(a["polygon"], float)) for a in data["aois"]),
    )
