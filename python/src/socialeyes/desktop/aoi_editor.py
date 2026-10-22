"""The AOI editor (Design > Content > Edit AOIs, CAM-171): drawing and naming AOIs on a study's
images in the app, instead of in LabelMe.

- ``aoi_images``: the images AOIs can be drawn on: the critical posts' images (they need AOIs),
  then the other feed images and the story images (optional).
- ``load``: an image (as a data URL for the page) and its AOIs, from a LabelMe or native AOI file.
- ``save``: writes the AOI file in LabelMe's format (as ``socialeyes aois`` does), so it still
  opens in LabelMe. The file it replaces is kept first in ``aoi_history/`` with the time.
- ``outline``: click-to-outline (face/outline.py), SAM when it can be had, else MediaPipe.
"""
from __future__ import annotations

import base64
import csv
import json
import shutil
from datetime import datetime
from pathlib import Path

HISTORY = "aoi_history"
MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}


def _rows(root: Path, name: str) -> list[dict]:
    path = root / name
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return [{k: (v or "").strip() for k, v in r.items() if k} for r in csv.DictReader(fh)]


def aoi_images(folder: Path | str) -> list[dict]:
    """[{image, aoi_file, what, needed, exists, names}] for every image AOIs can be drawn on."""
    from ..study.aoi import load_aoi_file

    root = Path(folder)
    crit = {r.get("post_id") for r in _rows(root, "posts.csv") if r.get("role") == "critical"}
    out = []
    for r in _rows(root, "images.csv"):
        if not r.get("file"):
            continue
        needed = r.get("post_id") in crit
        what = f"post {r['post_id']} ({r.get('version') or 'image'})" if r.get("post_id") else f"image {r.get('image_id', '')}"
        out.append({"image": r["file"], "aoi_file": r.get("aoi_file") or f"aois/{Path(r['file']).stem}.json",
                    "what": what, "needed": needed, "kind": "post", "post_id": r.get("post_id") or None})
    for r in _rows(root, "stories.csv"):
        if r.get("file") and Path(r["file"]).suffix.lower() in MIME:
            out.append({"image": r["file"], "aoi_file": r.get("aoi_file") or f"aois/{Path(r['file']).stem}.json",
                        "what": f"story {r['story_id']}" if r.get('story_id') else f"story of {r['account_id']}", "needed": False, "kind": "story"})
    seen, items = set(), []
    for x in sorted(out, key=lambda x: (not x["needed"], x["kind"] != "post")):   # needed first, stable otherwise
        if x["image"] in seen:
            continue
        seen.add(x["image"])
        p = root / x["aoi_file"]
        x["found"] = (root / x["image"]).is_file()
        x["exists"] = p.is_file()
        try:
            x["names"] = load_aoi_file(p).names() if x["exists"] else []
        except (OSError, ValueError, KeyError) as e:
            x["names"], x["error"] = [], str(e)
        items.append(x)
    return items


def _entry(folder: Path, image: str) -> dict:
    for x in aoi_images(folder):
        if x["image"] == image:
            return x
    raise ValueError(f"{image} isn't one of the study's images")


def load(folder: Path | str, image: str) -> dict:
    """{image, aoi_file, width, height, src (data URL), aois: [{name, points}], note}."""
    from PIL import Image

    from ..study.aoi import load_aoi_file

    root = Path(folder)
    x = _entry(root, image)
    path = root / image
    with Image.open(path) as im:
        w, h = im.size
    src = f"data:{MIME.get(path.suffix.lower(), 'image/png')};base64," + base64.b64encode(path.read_bytes()).decode()
    aois, note = [], None
    if x["exists"]:
        try:
            s = load_aoi_file(root / x["aoi_file"])
        except (OSError, ValueError, KeyError) as e:
            note = f"{x['aoi_file']} couldn't be read ({e}); saving replaces it (the old file is kept in {HISTORY}/)"
        else:
            if (s.width, s.height) != (w, h):   # drawn on another size of this image: scale to this one
                sx, sy = w / s.width, h / s.height
                note = f"{x['aoi_file']} was drawn on a {s.width} x {s.height} copy of this image; scaled to {w} x {h}"
            else:
                sx = sy = 1.0
            aois = [{"name": a.name, "points": [[round(px * sx, 1), round(py * sy, 1)] for px, py in a.polygon.tolist()]}
                    for a in s.aois]
    return {"image": image, "aoi_file": x["aoi_file"], "what": x["what"], "width": w, "height": h, "src": src,
            "aois": aois, "note": note}


def _clean(aois: list, w: int, h: int) -> list[dict]:
    out, names = [], set()
    for a in aois:
        name = str(a.get("name", "")).strip()
        if not name:
            raise ValueError("every AOI needs a name")
        if name in names:
            raise ValueError(f"two AOIs are called {name!r}; each name can be used once per image")
        names.add(name)
        pts = [[min(max(float(px), 0.0), w), min(max(float(py), 0.0), h)] for px, py in a.get("points", [])]
        if len(pts) < 3:
            raise ValueError(f"AOI {name!r} needs at least 3 points")
        out.append({"name": name, "points": [[round(px, 1), round(py, 1)] for px, py in pts]})
    return out


def save(folder: Path | str, image: str, aois: list) -> dict:
    """Writes the image's AOI file (LabelMe format); the file it replaces goes to aoi_history/ first."""
    from PIL import Image

    root = Path(folder)
    x = _entry(root, image)
    with Image.open(root / image) as im:
        w, h = im.size
    shapes = _clean(aois, w, h)
    dest = root / x["aoi_file"]
    kept = None
    if dest.is_file():
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        kept = root / HISTORY / f"{Path(x['aoi_file']).stem}.{stamp}.json"
        kept.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(dest, kept)
    dest.parent.mkdir(parents=True, exist_ok=True)
    image_path = Path(*([".."] * (len(Path(x["aoi_file"]).parts) - 1)), image).as_posix()
    data = {"version": "5.4.1", "flags": {},
            "shapes": [{"label": a["name"], "points": a["points"], "group_id": None,
                        "description": "drawn in the SocialEyes AOI editor", "shape_type": "polygon", "flags": {}}
                       for a in shapes],
            "imagePath": image_path, "imageData": None, "imageHeight": h, "imageWidth": w}
    tmp = dest.with_suffix(".json.part")
    tmp.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
    tmp.replace(dest)
    return {"aoi_file": x["aoi_file"], "n": len(shapes), "kept": str(kept) if kept else None}
