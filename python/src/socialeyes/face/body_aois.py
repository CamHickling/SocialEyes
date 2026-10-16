"""Face and body AOIs drawn automatically on post images (`socialeyes aois`), for the researcher
to review and correct in LabelMe.

Three MediaPipe models run on each image (on this computer, nothing is uploaded):

- the pose landmarker: the person's silhouette (``body``) and shoulders and hips, which give
  the torso's axis
- the face landmarker: the face's outline (``face``); a face too small to find in the whole
  image is looked for again in an enlarged crop around the head the pose found
- the multiclass selfie segmenter: hair (``hair``), and face skin when no face outline is found

The silhouette is cut across the torso's axis (0 at the shoulders, 1 at the hips, so the cuts
follow a bending or leaning body): ``upper_body`` above WAIST_FROM (neck, chest, shoulders and
whatever of the arms is there), ``waist`` from WAIST_FROM to LEGS_FROM (stomach, waist, hips)
and ``legs`` below. Face and hair are left out of the bands. AOIs are written in that order,
small before large: a point gets the first AOI that contains it, so ``body`` only collects what
no other AOI took. An AOI whose part of the silhouette falls apart (two legs) becomes one
polygon whose pieces are joined by zero-width seams.

The result is a LabelMe file per image (aois/<image file name>.json, read by the compiler as
is). It is a starting point: arms crossing the torso, loose clothing, several people and
unusual poses need checking, and the review page shows every image with its AOIs drawn on.
"""
from __future__ import annotations

import html
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from .model_files import ensure, quiet_native_stderr

NAMES = ("face", "hair", "upper_body", "waist", "legs", "body")
WAIST_FROM = 0.55
LEGS_FROM = 1.15
COLOURS = {"face": (255, 99, 71), "hair": (255, 193, 7), "upper_body": (33, 150, 243), "waist": (156, 39, 176),
           "legs": (76, 175, 80), "body": (158, 158, 158)}  # RGB

# MediaPipe face mesh: the face's outline, in order
FACE_OVAL = [10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397, 365, 379, 378, 400, 377, 152, 148, 176,
             149, 150, 136, 172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109]
# selfie_multiclass_256x256 categories
BACKGROUND, HAIR, BODY_SKIN, FACE_SKIN, CLOTHES, OTHER = range(6)


@dataclass
class ImageAOIs:
    image: str                         # file, relative to the study
    width: int
    height: int
    aois: dict = field(default_factory=dict)   # name -> (N, 2) polygon, in NAMES order
    notes: list = field(default_factory=list)  # what to check

    def labelme(self, image_path: str) -> dict:
        return {
            "version": "5.4.1", "flags": {},
            "shapes": [{"label": n, "points": np.round(p, 1).tolist(), "group_id": None,
                        "description": "drawn by socialeyes aois; check and correct", "shape_type": "polygon",
                        "flags": {}} for n, p in self.aois.items()],
            "imagePath": image_path, "imageData": None, "imageHeight": self.height, "imageWidth": self.width,
        }


class Detector:
    """The three models, loaded once for a batch of images."""

    def __init__(self):
        import os
        import warnings

        os.environ.setdefault("GLOG_minloglevel", "2")
        os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
        warnings.filterwarnings("ignore", message="SymbolDatabase.GetPrototype")
        warnings.filterwarnings("ignore", message="MessageFactory class is deprecated")
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions, vision

        self.mp = mp
        for name in ("face_landmarker.task", "pose_landmarker_full.task", "selfie_multiclass_256x256.tflite"):
            ensure(name)  # downloads (with their own messages) before stderr is hidden
        with quiet_native_stderr():
            self._create(vision, BaseOptions)

    def _create(self, vision, BaseOptions) -> None:
        self.face = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(ensure("face_landmarker.task"))), num_faces=3))
        self.pose = vision.PoseLandmarker.create_from_options(vision.PoseLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(ensure("pose_landmarker_full.task"))), num_poses=3,
            output_segmentation_masks=True))
        self.seg = vision.ImageSegmenter.create_from_options(vision.ImageSegmenterOptions(
            base_options=BaseOptions(model_asset_path=str(ensure("selfie_multiclass_256x256.tflite"))),
            output_category_mask=True, output_confidence_masks=False))

    def close(self) -> None:
        for m in (self.face, self.pose, self.seg):
            m.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _image(self, rgb: np.ndarray):
        return self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))

    def faces(self, rgb: np.ndarray) -> list[np.ndarray]:
        h, w = rgb.shape[:2]
        return [np.array([[p.x * w, p.y * h] for p in f]) for f in self.face.detect(self._image(rgb)).face_landmarks]

    def run(self, rgb: np.ndarray) -> tuple[np.ndarray, list, list, list]:
        """(category mask, faces' landmarks, poses' landmarks (x, y, visibility), poses' silhouettes),
        in the image's pixels."""
        import cv2

        h, w = rgb.shape[:2]
        img = self._image(rgb)
        cat = self.seg.segment(img).category_mask.numpy_view().copy()
        if cat.ndim == 3:
            cat = cat[..., 0]
        if cat.shape != (h, w):
            cat = cv2.resize(cat, (w, h), interpolation=cv2.INTER_NEAREST)
        res = self.pose.detect(img)
        poses = [np.array([[p.x * w, p.y * h, p.visibility] for p in f]) for f in res.pose_landmarks]
        sils = []
        for m in res.segmentation_masks or []:
            a = m.numpy_view()
            a = a[..., 0] if a.ndim == 3 else a
            sils.append(cv2.resize(a, (w, h), interpolation=cv2.INTER_LINEAR) > 0.5 if a.shape != (h, w) else a > 0.5)
        return cat, self.faces(rgb), poses, sils

    def face_in_head(self, rgb: np.ndarray, pose: np.ndarray) -> Optional[np.ndarray]:
        """The face's landmarks from an enlarged crop around the pose's head (faces far from the
        camera are too small for the face landmarker in the whole image)."""
        import cv2

        h, w = rgb.shape[:2]
        head = pose[:11]  # nose, eyes, ears, mouth
        if head[:, 2].max() < 0.3:
            return None
        cx, cy = head[0, :2]
        size = max(np.ptp(head[:, 0]), np.ptp(head[:, 1]), 0.25 * abs(pose[11, 0] - pose[12, 0])) * 3.0
        x0, y0 = int(max(0, cx - size / 2)), int(max(0, cy - size / 2))
        x1, y1 = int(min(w, cx + size / 2)), int(min(h, cy + size / 2))
        if x1 - x0 < 8 or y1 - y0 < 8:
            return None
        k = 384 / max(x1 - x0, y1 - y0)
        crop = cv2.resize(rgb[y0:y1, x0:x1], None, fx=k, fy=k, interpolation=cv2.INTER_CUBIC)
        found = self.faces(crop)
        if not found:
            return None
        f = max(found, key=lambda q: np.ptp(q[:, 0]) * np.ptp(q[:, 1]))
        return f / k + np.array([x0, y0])


def _solid(mask: np.ndarray) -> np.ndarray:
    """The mask with small gaps closed and holes filled."""
    import cv2

    m = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    contours, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    return cv2.drawContours(np.zeros_like(m), contours, -1, 1, cv2.FILLED).astype(bool)


def _largest_components(mask: np.ndarray, keep: float = 0.1) -> np.ndarray:
    """The mask's biggest connected part, and any other at least ``keep`` times its size."""
    import cv2

    n, lab, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    if n <= 1:
        return np.zeros_like(mask, bool)
    areas = stats[1:, cv2.CC_STAT_AREA]
    big = np.flatnonzero(areas >= keep * areas.max()) + 1
    return np.isin(lab, big)


def _near(mask: np.ndarray, px: int = 15) -> np.ndarray:
    import cv2

    return cv2.dilate(mask.astype(np.uint8), np.ones((2 * px + 1, 2 * px + 1), np.uint8)).astype(bool)


def mask_polygon(mask: np.ndarray, min_part: float = 0.05) -> Optional[np.ndarray]:
    """One polygon covering the mask: its outline, or its parts' outlines joined by zero-width
    seams (parts smaller than ``min_part`` of the largest are dropped)."""
    import cv2

    m = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    areas = [cv2.contourArea(c) for c in contours]
    rings = []
    for c, a in sorted(zip(contours, areas), key=lambda ca: -ca[1]):
        if a < max(20.0, min_part * max(areas)):
            continue
        c = cv2.approxPolyDP(c, max(1.0, 0.004 * cv2.arcLength(c, True)), True)
        if len(c) >= 3:
            rings.append(c.reshape(-1, 2).astype(float))
    if not rings:
        return None
    pts = list(rings[0]) + [rings[0][0]]
    hub = rings[0][0]
    for r in rings[1:]:  # hub -> ring -> back to the ring's start -> hub: the seam is crossed twice
        pts += list(r) + [r[0], hub]
    return np.array(pts)


def image_aois(rgb: np.ndarray, det: Detector, name: str = "") -> ImageAOIs:
    import cv2

    h, w = rgb.shape[:2]
    out = ImageAOIs(name, w, h)
    cat, faces, poses, sils = det.run(rgb)
    # the person: the largest pose's silhouette (the pose model is made for whole bodies), else the
    # selfie segmenter's (made for head and shoulders)
    p = int(np.argmax([np.ptp(q[:, 1]) for q in poses])) if poses else None
    if p is not None and p < len(sils) and sils[p].any():
        person = _solid(_largest_components(sils[p]))
        person |= _largest_components((cat == HAIR) & _near(person), keep=0.2)  # loose hair
    else:
        person = _solid(_largest_components(cat != BACKGROUND))
    if not person.any():
        out.notes.append("no person found")
        return out
    if len(poses) > 1 or len(faces) > 1:
        out.notes.append(f"{max(len(poses), len(faces))} people: the AOIs are for the largest; check")
    if not faces and p is not None:
        f = det.face_in_head(rgb, poses[p])
        faces = [f] if f is not None else []

    # face: the landmarks' outline (the largest face), else the face-skin segment
    face_mask = np.zeros((h, w), bool)
    if faces:
        f = max(faces, key=lambda p: np.ptp(p[:, 0]) * np.ptp(p[:, 1]))
        poly = f[FACE_OVAL]
        face_mask = cv2.fillPoly(np.zeros((h, w), np.uint8), [poly.round().astype(np.int32)], 1).astype(bool)
        out.aois["face"] = poly
    else:
        skin = _largest_components((cat == FACE_SKIN) & person, keep=1.0)
        if skin.sum() > 0.001 * h * w:
            out.aois["face"] = mask_polygon(skin)
            face_mask = skin
            out.notes.append("face outline from skin colour only (no face landmarks): check")
        else:
            out.notes.append("no face found (turned away, covered or out of frame)")
    hair = _largest_components((cat == HAIR) & person & ~face_mask, keep=0.2)
    if hair.sum() > 0.001 * h * w:
        out.aois["hair"] = mask_polygon(hair)

    # bands across the torso's axis
    if p is not None:
        p = poses[p]
        sh, hp = (p[11, :2] + p[12, :2]) / 2, (p[23, :2] + p[24, :2]) / 2
        if min(p[[11, 12, 23, 24], 2]) < 0.5:
            out.notes.append("shoulders or hips hard to see: the bands may be off")
        axis = hp - sh
        if np.hypot(*axis) > 0.02 * h:
            yy, xx = np.mgrid[0:h, 0:w]
            t = ((xx - sh[0]) * axis[0] + (yy - sh[1]) * axis[1]) / float(axis @ axis)
            rest = person & ~face_mask & (cat != HAIR)
            for nm, sel in (("upper_body", t < WAIST_FROM), ("waist", (t >= WAIST_FROM) & (t < LEGS_FROM)),
                            ("legs", t >= LEGS_FROM)):
                band = rest & sel
                if band.sum() > 0.002 * h * w:
                    poly = mask_polygon(band)
                    if poly is not None:
                        out.aois[nm] = poly
            if p[[25, 26, 27, 28], 2].max() < 0.5 and "legs" in out.aois:
                out.notes.append("knees and ankles not visible: legs may be cut off by the frame")
        else:
            out.notes.append("torso too small to split into bands")
    else:
        out.notes.append("no body pose found: only face, hair and body")
    body = mask_polygon(person)
    if body is not None:
        out.aois["body"] = body
    out.aois = {n: out.aois[n] for n in NAMES if out.aois.get(n) is not None}
    return out


# ---------------------------------------------------------------- a study


@dataclass
class StudyAOIResult:
    written: list = field(default_factory=list)    # (image file, aoi file)
    kept: list = field(default_factory=list)       # image files whose AOI file existed (not overwritten)
    empty: list = field(default_factory=list)      # (image file, why)
    review: Optional[str] = None
    images: list = field(default_factory=list)     # ImageAOIs, for the review page


def study_aois(study_dir: Path | str, all_images: bool = False, overwrite: bool = False,
               review_dir: Optional[Path | str] = None,
               progress: Callable[[str], None] = lambda s: None) -> StudyAOIResult:
    """Draws AOIs for the images of the study's critical posts (``all_images``: every image in
    images.csv) and writes aois/<image file name>.json for each image that has none yet."""
    import csv

    import cv2

    from ..study.compiler import check_study

    root = Path(study_dir)
    if root.name == "study.yaml":
        root = root.parent
    b, rep = check_study(root)
    if b is None:  # missing AOIs are what this fixes: read the CSVs directly
        crit = None
    else:
        crit = {p.post_id for p in b.critical}
    with (root / "images.csv").open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    if crit is None:
        with (root / "posts.csv").open(encoding="utf-8-sig", newline="") as fh:
            crit = {r["post_id"] for r in csv.DictReader(fh) if (r.get("role") or "").strip() == "critical"}
    r = StudyAOIResult()
    todo = [x for x in rows if all_images or x.get("post_id") in crit]
    with Detector() as det:
        for n, row in enumerate(todo, 1):
            rel = row["file"]
            aoi_rel = row.get("aoi_file") or f"aois/{Path(rel).stem}.json"
            progress(f"Image {n} of {len(todo)}: {rel}…")
            img = cv2.imread(str(root / rel), cv2.IMREAD_COLOR)
            if img is None:
                r.empty.append((rel, "can't read the image"))
                continue
            res = image_aois(img[:, :, ::-1].copy(), det, rel)
            r.images.append(res)
            if not res.aois:
                r.empty.append((rel, "; ".join(res.notes)))
                continue
            dest = root / aoi_rel
            if dest.is_file() and not overwrite:
                r.kept.append(rel)
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            image_path = Path(*([".."] * (len(Path(aoi_rel).parts) - 1)), rel).as_posix()
            dest.write_text(json.dumps(res.labelme(image_path), indent=1) + "\n", encoding="utf-8")
            r.written.append((rel, aoi_rel))
    if review_dir is not None:
        r.review = str(write_review(root, r.images, Path(review_dir)))
    return r


def write_review(root: Path, images: list[ImageAOIs], out: Path) -> Path:
    """A page with every image and its AOIs drawn on, for checking them."""
    import cv2

    out.mkdir(parents=True, exist_ok=True)
    cards = []
    for k, res in enumerate(images):
        img = cv2.imread(str(root / res.image), cv2.IMREAD_COLOR)
        if img is None:
            continue
        over = img.copy()
        for nm, poly in reversed(list(res.aois.items())):  # large first, so small ones stay on top
            r, g, b = COLOURS[nm]
            cv2.fillPoly(over, [poly.round().astype(np.int32)], (b, g, r))
        shown = cv2.addWeighted(over, 0.45, img, 0.55, 0)
        for nm, poly in res.aois.items():
            r, g, b = COLOURS[nm]
            cv2.polylines(shown, [poly.round().astype(np.int32)], True, (b, g, r), max(1, img.shape[1] // 400))
        scale = 480 / max(shown.shape[:2])
        if scale < 1:
            shown = cv2.resize(shown, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        name = f"aoi_{k:03d}.jpg"
        cv2.imwrite(str(out / name), shown, [cv2.IMWRITE_JPEG_QUALITY, 85])
        found = ", ".join(res.aois) or "none"
        notes = "".join(f"<li>{html.escape(n)}</li>" for n in res.notes)
        cards.append(f'<figure><img src="{name}" alt="{html.escape(res.image)}"><figcaption><b>{html.escape(res.image)}</b>'
                     f"<br>AOIs: {html.escape(found)}{f'<ul>{notes}</ul>' if notes else ''}</figcaption></figure>")
    legend = "".join(f'<span class="key"><i style="background:rgb{COLOURS[n]}"></i>{n}</span>' for n in NAMES)
    page = f"""<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>AOI review</title>
<style>
:root{{--bg:#fff;--fg:#1a1a1a;--muted:#666;--line:#ddd}}
@media (prefers-color-scheme:dark){{:root{{--bg:#151515;--fg:#eee;--muted:#aaa;--line:#333}}}}
body{{background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif;margin:0 auto;max-width:1200px;padding:16px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:16px}}
figure{{margin:0}} img{{width:100%;border:1px solid var(--line);border-radius:8px}}
figcaption{{font-size:13px;color:var(--muted)}} ul{{margin:4px 0;padding-left:18px}}
.key{{margin-right:14px;white-space:nowrap}} .key i{{display:inline-block;width:12px;height:12px;border-radius:3px;margin-right:4px;vertical-align:-1px}}
</style>
<h1>Automatic AOIs: check each image</h1>
<p>{legend}</p>
<p>Drawn by <code>socialeyes aois</code>. Correct any that are off in LabelMe (open the image's
<code>aois/&lt;image&gt;.json</code>); a point gets the first AOI that contains it, in the order above.</p>
<div class=grid>{''.join(cards)}</div>
"""
    path = out / "index.html"
    path.write_text(page, encoding="utf-8")
    return path
