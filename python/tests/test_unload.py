"""Unloading sessions, against a fake phone (a local folder) holding simulated sessions."""
import hashlib
import json
import re
import shutil
from pathlib import Path

import pytest

from socialeyes import settings
from socialeyes.phone import unload as U
from socialeyes.phone.adb import APP_FILES, Device
from socialeyes.session import register
from socialeyes.session.simulate import simulate_session
from socialeyes.study.compiler import compile_study


class FakePhone:
    """Answers the adb commands the unloader sends, from a folder standing in for the phone."""

    def __init__(self, root: Path, running: bool = False, corrupt: bool = False):
        self.root, self.running, self.corrupt = root, running, corrupt
        self.serial = "FAKE1"

    def local(self, remote: str) -> Path:
        assert remote.startswith(APP_FILES), remote
        return self.root / remote[len(APP_FILES):].lstrip("/")

    def choose(self):
        return Device("FAKE1", "device", "Fake Phone")

    def shell(self, cmd: str, timeout=60, check=False) -> str:
        if cmd.startswith("pidof"):
            return "1234\n" if self.running else ""
        if m := re.fullmatch(r"cd (\S+) 2>/dev/null && find \. -mindepth 2 -maxdepth 2 -type d", cmd):
            d = self.local(m.group(1))
            return "".join(f"./{p.relative_to(d).as_posix()}\n" for p in sorted(d.glob("*/*")) if p.is_dir()) if d.is_dir() else ""
        if m := re.fullmatch(r"cd (\S+) && find \. -type f -exec sha256sum \{\} \+", cmd):
            d = self.local(m.group(1))
            return "".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  ./{p.relative_to(d).as_posix()}\n"
                           for p in sorted(d.rglob("*")) if p.is_file())
        if m := re.fullmatch(r"cat (\S+)", cmd):
            return self.local(m.group(1)).read_text(encoding="utf-8")
        if m := re.fullmatch(r"rm -r (\S+)", cmd):
            shutil.rmtree(self.local(m.group(1)))
            return ""
        if cmd.startswith("cd ") and "rmdir" in cmd:  # tidying empty folders
            return ""
        raise AssertionError(f"unexpected command: {cmd}")

    def run(self, *args, timeout=60, check=True) -> str:
        assert args[0] == "pull", args
        src = self.local(args[1])
        dest = Path(args[2]) / src.name
        shutil.copytree(src, dest)
        if self.corrupt:  # a bad cable: one file arrives damaged
            f = next(p for p in sorted(dest.rglob("*.csv")))
            f.write_bytes(f.read_bytes()[:-10])
        return ""


@pytest.fixture
def setup(tmp_path, monkeypatch, example):
    monkeypatch.setenv("SOCIALEYES_SETTINGS", str(tmp_path / "settings.json"))
    monkeypatch.setattr(settings, "workspace", lambda: tmp_path / "ws")
    build, _ = compile_study(example, tmp_path / "build")
    phone_root = tmp_path / "phone"
    for pid in ("P001", "P002"):
        simulate_session(build, pid, phone_root / "data" / "example" / pid / f"{pid}-20261004T100000")
    return example, phone_root, tmp_path


def run(monkeypatch, example, phone):
    monkeypatch.setattr(U, "Adb", lambda serial=None: phone)
    return U.unload(example)


def test_unload_copies_checks_registers_then_deletes(setup, monkeypatch):
    example, phone_root, tmp = setup
    r = run(monkeypatch, example, FakePhone(phone_root))
    assert r.error is None and len(r.sessions) == 2
    for s in r.sessions:
        assert s.copied and s.deleted and s.error is None and s.completed
    data = tmp / "ws" / "data" / "example"
    assert (data / "P001" / "P001-20261004T100000" / "session.json").is_file()
    assert not list((phone_root / "data" / "example").glob("*/*"))  # gone from the phone
    _, rows = register.read(data / "sessions.csv")
    assert [r["participant_id"] for r in rows] == ["P001", "P002"]
    assert rows[0]["completed"] == "yes" and rows[0]["package_sha256"] and rows[0]["duplicate_id"] == ""
    assert (tmp / "ws" / "analysis_out" / "example" / "P001" / "P001-20261004T100000" / "quality.json").is_file()


def test_damaged_copy_is_not_deleted(setup, monkeypatch):
    example, phone_root, tmp = setup
    r = run(monkeypatch, example, FakePhone(phone_root, corrupt=True))
    for s in r.sessions:
        assert not s.copied and not s.deleted and "don't match" in s.error
    assert len(list((phone_root / "data" / "example").glob("*/*"))) == 2  # still on the phone
    assert not (tmp / "ws" / "data" / "example" / "sessions.csv").exists()


def test_second_copy(setup, monkeypatch):
    example, phone_root, tmp = setup
    settings.set_study("example", second_copy_dir=str(tmp / "backup"))
    r = run(monkeypatch, example, FakePhone(phone_root))
    assert all(s.second_copy and s.deleted for s in r.sessions)
    assert U.local_hashes(tmp / "backup" / "P002" / "P002-20261004T100000") == \
        U.local_hashes(tmp / "ws" / "data" / "example" / "P002" / "P002-20261004T100000")
    assert (tmp / "backup" / "sessions.csv").is_file()


def test_unfinished_session_stays_while_the_app_is_open(setup, monkeypatch):
    example, phone_root, tmp = setup
    meta_path = phone_root / "data" / "example" / "P001" / "P001-20261004T100000" / "session.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    del meta["end"]
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    r = run(monkeypatch, example, FakePhone(phone_root, running=True))
    p1 = next(s for s in r.sessions if s.participant_id == "P001")
    assert p1.copied and not p1.deleted and "may still be recording" in p1.kept_reason
    assert meta_path.is_file()
    _, rows = register.read(tmp / "ws" / "data" / "example" / "sessions.csv")
    assert next(x for x in rows if x["participant_id"] == "P001")["on_phone"] == "yes"
    # once the app is closed, unloading again finishes the job
    r = run(monkeypatch, example, FakePhone(phone_root, running=False))
    assert [s.deleted for s in r.sessions] == [True]


def test_register_keeps_notes_and_flags_reused_ids(tmp_path):
    path = tmp_path / "sessions.csv"
    register.update(path, [{"participant_id": "P001", "session_uid": "a", "completed": "yes"}])
    columns, rows = register.read(path)
    rows[0]["notes"] = "glasses slipped"
    with path.open("w", encoding="utf-8-sig", newline="") as fh:  # the researcher edits it, adds a column
        import csv
        w = csv.DictWriter(fh, fieldnames=columns + ["room"])
        w.writeheader()
        w.writerows([{**rows[0], "room": "lab 2"}])
    register.update(path, [{"participant_id": "P001", "session_uid": "a", "completed": "no"},
                           {"participant_id": "P001", "session_uid": "b", "completed": "yes"}])
    columns, rows = register.read(path)
    assert "room" in columns
    assert rows[0]["notes"] == "glasses slipped" and rows[0]["room"] == "lab 2" and rows[0]["completed"] == "no"
    assert [r["duplicate_id"] for r in rows] == ["yes", "yes"]


def test_settings_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("SOCIALEYES_SETTINGS", str(tmp_path / "s.json"))
    assert settings.second_copy_dir("x") is None
    settings.set_study("x", data_dir=str(tmp_path / "d"), second_copy_dir=str(tmp_path / "b"))
    assert settings.data_dir("x") == tmp_path / "d" and settings.second_copy_dir("x") == tmp_path / "b"
    settings.set_study("x", second_copy_dir=None)
    assert settings.second_copy_dir("x") is None


def test_study_id_of(example, tmp_path):
    assert U.study_id_of(example) == "example"
    with pytest.raises(ValueError):
        U.study_id_of(tmp_path)
