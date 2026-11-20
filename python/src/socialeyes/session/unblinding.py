"""The unblinding log: who unblinded a study's results, when, and what they made.

Results stay blinded (conditions as codes, heatmaps pooled over every condition) until a researcher
unblinds. Unblinding can't be taken back, since nobody can un-see results, so every unblinded output
needs the researcher's name and the confirmation phrase typed out in full ("unblind <study id>", as
GitHub asks before deleting a repository), and each one is recorded in ``unblinding.csv`` in the
study's data folder. The log is only ever added to: SocialEyes never edits or deletes its rows.
"""
from __future__ import annotations

import csv
import getpass
import platform
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

LOG = "unblinding.csv"
COLUMNS = ["unblinded_at", "researcher", "computer_user", "computer", "study_id", "study_version", "what", "sessions"]


def phrase(study_id: str) -> str:
    """What the researcher types to confirm."""
    return f"unblind {study_id}"


@dataclass
class Unblinding:
    """A researcher's go-ahead to unblind: their name and the phrase as they typed it."""
    researcher: str
    typed: str

    def check(self, study_id: str) -> None:
        """ValueError unless the name is filled in and the phrase was typed exactly."""
        if len((self.researcher or "").strip()) < 2:
            raise ValueError("Unblinding needs the name of the researcher doing it.")
        if (self.typed or "").strip() != phrase(study_id):
            raise ValueError(f'To unblind, type "{phrase(study_id)}" exactly.')


def computer_user() -> str:
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001  (no user name in the environment: still log the rest)
        return ""


def record(data_dir: Path, study_id: str, study_version, who: Unblinding, what: str, sessions: int) -> dict:
    """Checks the go-ahead and adds a row to the log (made if missing). Called before the unblinded
    files are written, so an unblinding that then fails part-way is still on record."""
    who.check(study_id)
    row = {"unblinded_at": datetime.now().astimezone().isoformat(timespec="seconds"),
           "researcher": who.researcher.strip(), "computer_user": computer_user(), "computer": platform.node(),
           "study_id": study_id, "study_version": "" if study_version is None else str(study_version),
           "what": what, "sessions": sessions}
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / LOG
    new = not path.is_file()
    with path.open("a", encoding="utf-8-sig" if new else "utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        if new:
            w.writeheader()
        w.writerow(row)
    return row


def study_version(study_dir: Path | str):
    """The version in study.yaml (None if it can't be read: the log row is still written)."""
    import yaml

    path = Path(study_dir)
    path = path if path.suffix.lower() in (".yaml", ".yml") else path / "study.yaml"
    try:
        return (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("version")
    except (OSError, yaml.YAMLError):
        return None


def count_sessions(data_dir: Path) -> int:
    return sum(1 for p in Path(data_dir).glob("*/*/session.json") if not p.parent.parent.name.startswith("."))


def unblind(study_dir: Path | str, data_dir: Path, study_id: str, who: "Unblinding | None", what: str) -> dict:
    """record() for an output about to be made unblinded; ValueError without a go-ahead."""
    if who is None:
        raise ValueError(f'Unblinding needs the researcher\'s name and "{phrase(study_id)}" typed out.')
    return record(data_dir, study_id, study_version(study_dir), who, what, count_sessions(data_dir))


def history(data_dir: Path) -> list[dict]:
    """The log's rows, oldest first ([] if the study was never unblinded)."""
    path = Path(data_dir) / LOG
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))
