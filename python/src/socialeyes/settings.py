"""Settings that belong to this computer, not to the study (CAM-158): where each study's
data goes and its optional second copy. Kept in one JSON file per user, so study.yaml
never carries anyone's drive letters or network paths.

    %APPDATA%\\SocialEyes\\settings.json      (Windows)
    ~/.config/socialeyes/settings.json       (elsewhere)

SOCIALEYES_SETTINGS overrides the location (used by the tests).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parents[3]  # python/src/socialeyes/settings.py -> repo root


def settings_path() -> Path:
    if os.environ.get("SOCIALEYES_SETTINGS"):
        return Path(os.environ["SOCIALEYES_SETTINGS"])
    if os.name == "nt" and os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / "SocialEyes" / "settings.json"
    return Path.home() / ".config" / "socialeyes" / "settings.json"


def workspace() -> Path:
    """The folder holding studies/, data/ and analysis_out/: the repo when developing,
    Documents\\SocialEyes for the packaged app."""
    if not hasattr(sys, "_MEIPASS") and (REPO / "studies").is_dir():
        return REPO
    return Path.home() / "Documents" / "SocialEyes"


def studies_dir() -> Path:
    """Where studies live (created on first use)."""
    path = workspace() / "studies"
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return path


def example_study() -> Path:
    """The bundled example study (the packaged app carries a copy)."""
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "example"
    return REPO / "studies" / "example"


def load() -> dict:
    path = settings_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save(data: dict) -> None:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def study(study_id: str) -> dict:
    return dict(load().get("studies", {}).get(study_id, {}))


def set_study(study_id: str, **values: Optional[str]) -> dict:
    """Changes a study's settings; a value of None removes that setting."""
    data = load()
    entry = data.setdefault("studies", {}).setdefault(study_id, {})
    for key, value in values.items():
        if value is None:
            entry.pop(key, None)
        else:
            entry[key] = value
    save(data)
    return dict(entry)


def data_dir(study_id: str) -> Path:
    """Where the study's sessions are kept: the setting, else <workspace>/data/<study id>."""
    chosen = study(study_id).get("data_dir")
    return Path(chosen) if chosen else workspace() / "data" / study_id


def second_copy_dir(study_id: str) -> Optional[Path]:
    chosen = study(study_id).get("second_copy_dir")
    return Path(chosen) if chosen else None


def analysis_dir(study_id: str) -> Path:
    return workspace() / "analysis_out" / study_id


def build_snapshot(study_id: str, package_sha256: str) -> Path:
    """Where the exact build a phone was loaded with is kept: <data folder>/builds/<hash, first 16>."""
    return data_dir(study_id) / "builds" / package_sha256[:16]
