"""The desktop app's Studies tab (the study list) and Content tab (which files the design needs).

Both only read the study folders, except copy_example, which makes a new study.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

import yaml

from .. import settings
from ..session import register
from ..study.compiler import Report, _id_from_file, _read_csv, check_study
from .studyfolder import STUDY_FILE, FolderError

CSV_DEFAULTS = {"accounts": "accounts.csv", "images": "images.csv", "posts": "posts.csv",
                "stories": "stories.csv", "reels": "reels.csv"}
ID = re.compile(r"[A-Za-z0-9_-]+")


def studies_root() -> Path:
    return settings.studies_dir()


def _raw_study(folder: Path) -> dict:
    try:
        data = yaml.safe_load((folder / STUDY_FILE).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def study_summary(folder: Path) -> dict:
    """One row of the Studies tab: id, title, status and sessions so far.

    Status: *collecting data* once sessions are registered, else *ready* when the study
    passes every check, else *designing* (with the number of problems).
    """
    raw = _raw_study(folder)
    sid = str(raw.get("id") or folder.name)
    _, report = check_study(folder)
    rows = []
    if ID.fullmatch(sid):
        _, rows = register.read(settings.data_dir(sid) / register.REGISTER)
    started = sorted(r.get("started", "") for r in rows if r.get("started"))
    status = "collecting data" if rows else "ready" if not report.errors else "designing"
    return {
        "folder": str(folder), "id": sid, "title": str(raw.get("title") or ""), "version": raw.get("version", 1),
        "status": status, "n_errors": len(report.errors), "n_warnings": len(report.warnings),
        "n_sessions": len(rows), "last_session": started[-1] if started else None,
    }


def list_studies(root: Path | None = None) -> dict:
    root = Path(root) if root else studies_root()
    found = sorted(p for p in root.iterdir() if (p / STUDY_FILE).is_file()) if root.is_dir() else []
    return {"root": str(root), "studies": [study_summary(p) for p in found]}


def copy_example(new_id: str, root: Path | None = None) -> str:
    """A new study folder <root>/<new id> made from the example, images and all."""
    root = Path(root) if root else studies_root()
    if not ID.fullmatch(new_id or ""):
        raise FolderError("The study id may only contain letters, digits, _ and -.")
    dest = root / new_id
    if dest.exists():
        raise FolderError(f"{dest} already exists; choose another id.")
    example = settings.example_study()
    if not (example / STUDY_FILE).is_file():
        raise FolderError("The example study isn't available on this computer.")
    shutil.copytree(example, dest, ignore=shutil.ignore_patterns("__pycache__", "make_placeholders.py"))
    text = (dest / STUDY_FILE).read_text(encoding="utf-8")
    text, n = re.subn(r"(?m)^id:\s*example\s*$", f"id: {new_id}", text, count=1)
    if not n:
        shutil.rmtree(dest)
        raise FolderError("Couldn't set the id in the copied study.yaml.")
    (dest / STUDY_FILE).write_text(text, encoding="utf-8")
    return str(dest)


def content_checklist(folder: Path | str) -> dict:
    """Every file the study's CSVs point to, found or missing, grouped by kind.

    Works on unfinished studies too: CSV names come straight from study.yaml (or the
    defaults), and rows with problems are skipped here (the checks report them).
    """
    folder = Path(folder)
    if not (folder / STUDY_FILE).is_file():
        raise FolderError(f"{folder} has no study.yaml")
    raw = _raw_study(folder)
    names = {k: str(raw.get(k) or v) for k, v in CSV_DEFAULTS.items()}
    rep = Report()
    items: list[dict] = []
    tables = []

    def add(kind: str, rel: str, what: str) -> None:
        rel = rel.replace("\\", "/")
        items.append({"kind": kind, "file": rel, "what": what, "found": (folder / rel).is_file()})

    for kind in ("accounts", "images", "posts"):
        tables.append({"file": names[kind], "found": (folder / names[kind]).is_file()})
    for kind in ("stories", "reels"):
        if (folder / names[kind]).is_file():
            tables.append({"file": names[kind], "found": True})

    roles = {r["post_id"]: r["role"] for _, r in _read_csv(folder / names["posts"], "posts", rep)}
    for _, r in _read_csv(folder / names["accounts"], "accounts", rep):
        add("avatar", r["avatar"], f"avatar of @{r['handle'].lstrip('@')}")
    for _, r in _read_csv(folder / names["images"], "images", rep):
        image_id = r["image_id"] or _id_from_file(r["file"])
        post = r["post_id"]
        label = f"post {post}" + (f" ({r['version']})" if r["version"] else "") if post else f"image {image_id} (not in the feed)"
        add("image", r["file"], label)
        if r["aoi_file"] or roles.get(post) == "critical":
            add("aoi", r["aoi_file"] or f"aois/{Path(r['file']).stem}.json", f"AOIs for {label}")
    for _, r in _read_csv(folder / names["stories"], "stories", rep, required=False):
        add("story", r["file"], f"story of {r['account_id']}")
    for _, r in _read_csv(folder / names["reels"], "reels", rep, required=False):
        add("video", r["file"], f"reel of {r['account_id']}")

    return {"folder": str(folder), "tables": tables, "items": items,
            "n_found": sum(i["found"] for i in items), "n_needed": len(items)}
