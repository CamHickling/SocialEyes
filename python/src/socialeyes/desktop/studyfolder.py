"""Reading, saving and checking a study folder for the desktop app's Design tab.

No GUI code here, so it can be tested without a window. Saving follows one rule:
study.yaml is always written (the previous one is kept as study.yaml.bak), every
other file only when it doesn't exist yet. A researcher's CSVs are never overwritten.
"""
from __future__ import annotations

import os
from pathlib import Path, PurePosixPath

from ..study.compiler import check_study

STUDY_FILE = "study.yaml"
BACKUP_FILE = "study.yaml.bak"


class FolderError(ValueError):
    """Something about the folder the user should be told in plain words."""


def read_study(folder: Path | str) -> dict:
    """The folder's study.yaml text and which other files are already there."""
    folder = Path(folder)
    path = folder / STUDY_FILE
    if not path.is_file():
        raise FolderError(f"{folder} has no study.yaml. Choose the folder that contains it.")
    return {
        "folder": str(folder),
        "yaml": path.read_text(encoding="utf-8"),
        "files": sorted(p.name for p in folder.iterdir() if p.is_file()),
    }


def _target(folder: Path, name: str) -> Path:
    """Where a file the builder sends goes; refuses anything that would leave the folder."""
    rel = PurePosixPath(name.replace("\\", "/"))
    if rel.is_absolute() or not rel.parts or ".." in rel.parts or ":" in name:
        raise FolderError(f"refusing to write {name!r}: not a file inside the study folder")
    return folder.joinpath(*rel.parts)


def save_study(folder: Path | str, files: dict[str, str]) -> dict:
    """Write the builder's files into ``folder`` (created if needed).

    ``files`` maps names to text and must contain study.yaml. Returns which files
    were written, which already existed and were left alone, and whether a
    backup of the previous study.yaml was made.
    """
    folder = Path(folder)
    if STUDY_FILE not in files:
        raise FolderError("nothing to save: the builder sent no study.yaml")
    targets = {name: _target(folder, name) for name in files}
    folder.mkdir(parents=True, exist_ok=True)

    written, kept = [], []
    study_path = targets[STUDY_FILE]
    new_yaml = files[STUDY_FILE]
    backup = False
    if study_path.is_file():
        old = study_path.read_text(encoding="utf-8")
        if old != new_yaml:
            (folder / BACKUP_FILE).write_text(old, encoding="utf-8")
            backup = True
    tmp = study_path.with_name(STUDY_FILE + ".tmp")
    tmp.write_text(new_yaml, encoding="utf-8")
    os.replace(tmp, study_path)  # a crash mid-save never leaves half a study.yaml
    written.append(STUDY_FILE)

    for name, text in files.items():
        if name == STUDY_FILE:
            continue
        path = targets[name]
        if path.exists():
            kept.append(name)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        written.append(name)
    return {"folder": str(folder), "written": written, "kept": sorted(kept), "backup": backup}


def new_study_folder(parent: Path | str, study_id: str) -> Path:
    """The folder a new study is saved to: <parent>/<study id>, which must not hold another study."""
    if not study_id or any(c in study_id for c in '\\/:*?"<>|') or study_id in (".", ".."):
        raise FolderError("give the study an id first (Basics); it names the folder")
    folder = Path(parent) / study_id
    if (folder / STUDY_FILE).exists():
        raise FolderError(f"{folder} already contains a study. Open it instead, or change the study id.")
    return folder


def check_folder(folder: Path | str) -> dict:
    """The compiler's checks (images, AOIs, CSV contents) for the study in ``folder``."""
    folder = Path(folder)
    if not (folder / STUDY_FILE).is_file():
        raise FolderError(f"{folder} has no study.yaml to check")
    _, report = check_study(folder)
    return {"folder": str(folder), "errors": report.errors, "warnings": report.warnings}
