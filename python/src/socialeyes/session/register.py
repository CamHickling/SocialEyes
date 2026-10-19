"""The session register: sessions.csv in a study's data folder, one row per session.

The app owns the columns in APP_COLUMNS and rewrites them when a session is unloaded
again. ``status`` is ``active`` or ``withdrawn`` (with ``status_at``): a withdrawn participant's rows
stay, so the register keeps a record of every id used, but their data does not (withdraw.py). ``notes`` and any column the researcher adds are theirs: they are kept as they
are. Written as UTF-8 with a byte-order mark, so Excel shows accents correctly.
"""
from __future__ import annotations

import csv
import os
from pathlib import Path

REGISTER = "sessions.csv"
APP_COLUMNS = ["participant_id", "session_uid", "status", "status_at", "started", "phone", "app_version", "completed", "end_reason",
               "duration_s", "group_key", "package_sha256", "n_warnings", "warnings", "duplicate_id",
               "on_phone", "unloaded_at"]
COLUMNS = APP_COLUMNS + ["notes"]


class RegisterLocked(OSError):
    pass


def read(path: Path | str) -> tuple[list[str], list[dict]]:
    """(columns, rows) of a register; no file means an empty one."""
    path = Path(path)
    if not path.is_file():
        return list(COLUMNS), []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        columns = list(reader.fieldnames or [])
        rows = [dict(r) for r in reader]
    for c in COLUMNS:  # older or hand-made registers get the missing columns
        if c not in columns:
            columns.append(c)
    return columns, rows


def update(path: Path | str, new_rows: list[dict]) -> list[dict]:
    """Adds or refreshes rows (matched by session_uid), re-flags duplicate participant ids, writes the file."""
    path = Path(path)
    columns, rows = read(path)
    by_uid = {r.get("session_uid"): r for r in rows}
    for new in new_rows:
        row = by_uid.get(new["session_uid"])
        if row is None:
            row = {c: "" for c in columns}
            rows.append(row)
            by_uid[new["session_uid"]] = row
        for c in APP_COLUMNS:
            if c in new:
                row[c] = "" if new[c] is None else str(new[c])
    for r in rows:
        if not r.get("status"):
            r["status"] = "active"
    counts: dict = {}
    for r in rows:
        counts[r.get("participant_id", "")] = counts.get(r.get("participant_id", ""), 0) + 1
    for r in rows:
        r["duplicate_id"] = "yes" if r.get("participant_id") and counts[r["participant_id"]] > 1 else ""

    _write(path, columns, rows)
    return rows


def withdrawn_ids(path: Path | str) -> set[str]:
    """Participant ids marked withdrawn (their sessions are never unloaded or exported again)."""
    return {r["participant_id"] for r in read(path)[1] if r.get("status") == "withdrawn"}


def set_status(path: Path | str, participant_id: str, status: str, at: str) -> list[dict]:
    """Marks every row of the participant (one row if they have none yet), keeping the rows: the
    register stays a record of every id used."""
    path = Path(path)
    columns, rows = read(path)
    mine = [r for r in rows if r.get("participant_id") == participant_id]
    if not mine:
        mine = [{c: "" for c in columns}]
        mine[0]["participant_id"] = participant_id
        rows.append(mine[0])
    for r in mine:
        r["status"], r["status_at"] = status, at
    _write(path, columns, rows)
    return rows


def _write(path: Path, columns: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    try:
        os.replace(tmp, path)
    except PermissionError as e:  # Windows: the file is open in Excel
        tmp.unlink(missing_ok=True)
        raise RegisterLocked(f"{path} is open in another program (Excel?); close it and try again.") from e
