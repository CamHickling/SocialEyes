"""Getting a study's images and videos in (CAM-173): matching a folder of files to the study's slots,
an image check, and a record of where each file came from.

- ``match``: every file in a folder against the files the study's CSVs name (images, avatars, story
  images, reel videos), by name, ignoring case, spaces, dashes, underscores and the extension.
- ``copy_in``: copies the chosen files into the study folder under the names the CSVs give, converting
  an image to the slot's format (a .png for a .jpg slot) so the CSVs stay as they are. A file already
  there is only replaced when asked.
- ``image_report``: per image: size and shape against what the feed shows well, very small or very
  large files, the same picture in two slots, and the two versions of a critical post differing in size.
- ``resize_large``: shrinks the very large images (longest side above MAX_SIDE), keeping each original
  in ``originals/``.
- ``sources``: ``sources.csv`` with a row per file (source, licence, credit, consent, notes), kept in
  step with the study (rows are added, never removed), and how many still lack a source and licence.
"""
from __future__ import annotations

import csv
import hashlib
import re
import shutil
from pathlib import Path

from .studies import content_checklist

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_EXT = {".mp4", ".mov", ".m4v"}
MAX_SIDE = 2160            # px: larger only costs phone memory (the feed is ~1080 px wide)
MIN_WIDTH = 600            # px: smaller looks blurry across a phone's width
TALLEST, WIDEST = 4 / 5, 1.91   # width/height range Instagram accepts for feed posts
SOURCES = "sources.csv"
SOURCE_COLUMNS = ["file", "source", "licence", "credit", "consent", "notes"]


def _key(name: str) -> str:
    """A file name as matching sees it: stem, lower case, letters and digits only."""
    return re.sub(r"[^a-z0-9]", "", Path(name).stem.lower())


def _slots(folder: Path) -> list[dict]:
    return [i for i in content_checklist(folder)["items"] if i["kind"] in ("image", "avatar", "story", "video")]


def match(folder: Path | str, source_dir: Path | str) -> dict:
    """{matched: [{source, slot, what, exists}], unmatched: [source], missing: [{slot, what}]}."""
    folder, source_dir = Path(folder), Path(source_dir)
    slots = _slots(folder)
    files = sorted(p for p in source_dir.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXT | VIDEO_EXT)
    by_key = {}
    for p in files:
        by_key.setdefault(_key(p.name), p)
    matched, used = [], set()
    for s in slots:
        p = by_key.get(_key(s["file"]))
        video = Path(s["file"]).suffix.lower() in VIDEO_EXT
        if p is not None and (p.suffix.lower() in VIDEO_EXT) == video:
            matched.append({"source": str(p), "slot": s["file"], "what": s["what"], "exists": s["found"]})
            used.add(p)
    return {"matched": matched,
            "unmatched": [str(p) for p in files if p not in used],
            "missing": [{"slot": s["file"], "what": s["what"]} for s in slots
                        if not s["found"] and s["file"] not in {m["slot"] for m in matched}]}


def copy_in(folder: Path | str, pairs: list[dict], replace: bool = False) -> dict:
    """Copies each {source, slot} into the study folder. Returns {copied, converted, kept, errors}."""
    from PIL import Image

    folder = Path(folder)
    out = {"copied": [], "converted": [], "kept": [], "errors": []}
    for pair in pairs:
        src, dest = Path(pair["source"]), folder / pair["slot"]
        if not src.is_file():
            out["errors"].append(f"{src.name}: not found")
            continue
        if dest.exists() and not replace:
            out["kept"].append(pair["slot"])
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        same = src.suffix.lower() == dest.suffix.lower() or {src.suffix.lower(), dest.suffix.lower()} <= {".jpg", ".jpeg"}
        try:
            if same or dest.suffix.lower() in VIDEO_EXT:
                if dest.suffix.lower() in VIDEO_EXT and src.suffix.lower() not in VIDEO_EXT:
                    raise ValueError("a video slot needs a video file")
                shutil.copy2(src, dest)
                out["copied"].append(pair["slot"])
            else:   # a .png for a .jpg slot (or the other way round): convert, so the CSVs stay as they are
                with Image.open(src) as im:
                    im = im.convert("RGB") if dest.suffix.lower() in (".jpg", ".jpeg") else im
                    im.save(dest, quality=92) if dest.suffix.lower() in (".jpg", ".jpeg") else im.save(dest)
                out["converted"].append(pair["slot"])
        except (OSError, ValueError) as e:
            out["errors"].append(f"{src.name}: {e}")
    return out


def _hash(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def image_report(folder: Path | str) -> dict:
    """{images: [{file, what, width, height, flags}], large: [file], notes: [str]} for the images found."""
    from PIL import Image

    folder = Path(folder)
    items = [s for s in _slots(folder) if s["found"] and s["kind"] in ("image", "story", "avatar")]
    rows, large, seen, notes = [], [], {}, []
    for s in items:
        p = folder / s["file"]
        try:
            with Image.open(p) as im:
                w, h = im.size
        except OSError:
            rows.append({"file": s["file"], "what": s["what"], "width": None, "height": None,
                         "flags": ["can't be opened as an image"]})
            continue
        flags = []
        if s["kind"] == "image":
            ratio = w / h
            if ratio < TALLEST - 0.01:
                flags.append(f"taller than a feed post can be (4:5): shown whole, it fills more than a screen")
            elif ratio > WIDEST + 0.01:
                flags.append("wider than a feed post can be (1.91:1)")
            if w < MIN_WIDTH:
                flags.append(f"only {w} px wide: looks blurry across the phone")
        if max(w, h) > MAX_SIDE:
            flags.append(f"{w} x {h} px: larger than needed")
            large.append(s["file"])
        digest = _hash(p)
        if digest in seen and seen[digest] != s["file"]:
            flags.append(f"the same picture as {seen[digest]}")
        seen.setdefault(digest, s["file"])
        rows.append({"file": s["file"], "what": s["what"], "width": w, "height": h, "flags": flags})
    # the versions of a critical post should be the same size (AOIs and gaze are compared across them)
    by_post: dict = {}
    for r in rows:
        m = re.match(r"post (\S+) \(", r["what"])
        if m and r["width"]:
            by_post.setdefault(m.group(1), set()).add((r["width"], r["height"]))
    for post, sizes in sorted(by_post.items()):
        if len(sizes) > 1:
            notes.append(f"post {post}: its versions differ in size ({', '.join(f'{w} x {h}' for w, h in sorted(sizes))}); "
                         "make them the same size so AOIs and gaze line up")
    return {"images": rows, "large": large, "notes": notes,
            "flagged": sum(1 for r in rows if r["flags"]) + len(notes)}


def resize_large(folder: Path | str, files: list[str] | None = None) -> dict:
    """Shrinks images whose longest side is over MAX_SIDE to MAX_SIDE, keeping each original in originals/."""
    from PIL import Image

    folder = Path(folder)
    files = image_report(folder)["large"] if files is None else files
    done = []
    for rel in files:
        p = folder / rel
        keep = folder / "originals" / rel
        if not keep.exists():
            keep.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, keep)
        with Image.open(keep) as im:
            im.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
            (im.convert("RGB") if p.suffix.lower() in (".jpg", ".jpeg") else im).save(p, quality=92) \
                if p.suffix.lower() in (".jpg", ".jpeg") else im.save(p)
        done.append(rel)
    return {"resized": done, "originals": str(folder / "originals")}


def sources(folder: Path | str, create: bool = True) -> dict:
    """Brings sources.csv in step with the study's files (adds rows, never removes them) and says how
    many files still lack a source and a licence. Without ``create``, a study that has no sources.csv
    yet gets none ({exists: False}): looking at a study doesn't write to it."""
    folder = Path(folder)
    path = folder / SOURCES
    if not create and not path.is_file():
        return {"path": str(path), "exists": False, "files": len(_slots(folder)), "complete": 0, "added": 0}
    rows, columns = [], list(SOURCE_COLUMNS)
    if path.is_file():
        with path.open(encoding="utf-8-sig", newline="") as fh:
            r = csv.DictReader(fh)
            columns = list(r.fieldnames or SOURCE_COLUMNS) + [c for c in SOURCE_COLUMNS if c not in (r.fieldnames or [])]
            rows = [dict(x) for x in r]
    have = {r.get("file", "") for r in rows}
    files = [s["file"] for s in _slots(folder)]
    added = [f for f in files if f not in have]
    rows += [{c: (f if c == "file" else "") for c in columns} for f in added]
    if added or not path.is_file():
        with path.open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
    current = [r for r in rows if r.get("file") in set(files)]
    complete = sum(1 for r in current if (r.get("source") or "").strip() and (r.get("licence") or "").strip())
    return {"path": str(path), "exists": True, "files": len(current), "complete": complete, "added": len(added)}
