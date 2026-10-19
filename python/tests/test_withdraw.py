"""Withdrawal (two steps, with undo) and retention reminders, on simulated sessions."""
import csv
import datetime as dt
import json
import shutil

import pytest

from conftest import edit_file
from socialeyes import settings
from socialeyes.cli import main
from socialeyes.session import register, retention
from socialeyes.session import withdraw as W
from socialeyes.session.export import export_study
from socialeyes.session.simulate import simulate_session
from socialeyes.study.compiler import compile_study


@pytest.fixture
def study(tmp_path, monkeypatch, example):
    """Two participants' sessions in the data folder, a second copy, analysis output and an export."""
    monkeypatch.setenv("SOCIALEYES_SETTINGS", str(tmp_path / "settings.json"))
    monkeypatch.setattr(settings, "workspace", lambda: tmp_path / "ws")
    settings.set_study("example", second_copy_dir=str(tmp_path / "backup"))
    build, _ = compile_study(example, tmp_path / "build")
    data = settings.data_dir("example")
    for pid in ("P001", "P002"):
        uid = f"{pid}-20261004T100000"
        out = simulate_session(build, pid, data / pid / uid)
        meta = json.loads((out / "session.json").read_text(encoding="utf-8"))
        meta["session_uid"] = uid
        meta["neon"] = {"recording_id": f"rec-{pid}"}
        (out / "session.json").write_text(json.dumps(meta), encoding="utf-8")
        shutil.copytree(out, tmp_path / "backup" / pid / uid)
        (settings.analysis_dir("example") / pid / uid).mkdir(parents=True)
        (settings.analysis_dir("example") / pid / uid / "quality.json").write_text("{}", encoding="utf-8")
        register.update(data / register.REGISTER, [{"participant_id": pid, "session_uid": uid,
                                                    "unloaded_at": "2026-10-05T10:00:00"}])
    export_study(example, data, settings.export_dir("example"), build_for=lambda _f: build)
    return example, build, data, tmp_path


def log(data):
    return list(csv.DictReader((data / W.LOG).open(encoding="utf-8-sig", newline="")))


def test_withdraw_holds_then_restores(study):
    example, build, data, tmp = study
    r = W.withdraw(example, "P002", reason="emailed on 18 Oct")
    assert r.sessions == ["P002-20261004T100000"] and r.neon_recordings == ["rec-P002"]
    for base in (data, tmp / "backup", settings.analysis_dir("example")):
        assert not (base / "P002").exists() and (base / W.HOLD / "P002" / "P002-20261004T100000").is_dir()
    assert not settings.export_dir("example").exists()  # the tables included them
    rows = {x["participant_id"]: x for x in register.read(data / register.REGISTER)[1]}
    assert rows["P002"]["status"] == "withdrawn" and rows["P001"]["status"] == "active"
    assert (tmp / "backup" / register.REGISTER).is_file()
    assert log(data)[0]["action"] == "withdrawn" and log(data)[0]["reason"] == "emailed on 18 Oct"
    # they are left out of the export
    e = export_study(example, data, tmp / "out", build_for=lambda _f: build)
    assert e.sessions == 1
    with pytest.raises(ValueError, match="withdrawn already"):
        W.withdraw(example, "P002")
    # a mistake: undo
    r = W.restore(example, "P002")
    assert (data / "P002" / "P002-20261004T100000" / "session.json").is_file() and not (data / W.HOLD).exists()
    assert register.withdrawn_ids(data / register.REGISTER) == set()
    assert [x["action"] for x in log(data)] == ["withdrawn", "restored"]


def test_delete_permanently(study, monkeypatch):
    example, build, data, tmp = study
    with pytest.raises(ValueError, match="withdraw them first"):
        W.delete_permanently(example, "P001", phone=False)
    W.withdraw(example, "P001")
    r = W.delete_permanently(example, "P001", phone=False)
    assert len(r.deleted) == 3 and "rec-P001" in " ".join(r.notes)
    for base in (data, tmp / "backup", settings.analysis_dir("example")):
        assert not (base / W.HOLD / "P001").exists() and not (base / "P001").exists()
    rows = {x["participant_id"]: x for x in register.read(data / register.REGISTER)[1]}
    assert rows["P001"]["status"] == "withdrawn" and rows["P001"]["session_uid"]  # the record stays
    with pytest.raises(ValueError, match="deleted permanently"):
        W.restore(example, "P001")
    assert [x["action"] for x in log(data)] == ["withdrawn", "deleted"]


def test_withdraw_someone_never_unloaded(study):
    example, build, data, tmp = study
    r = W.withdraw(example, "P077")
    assert r.sessions == [] and any("no files" in n for n in r.notes)
    assert "P077" in register.withdrawn_ids(data / register.REGISTER)


def test_withdraw_rejects_odd_ids(study):
    example, *_ = study
    for bad in ("", "../P001", "export", "withdrawn"):
        with pytest.raises(ValueError):
            W.withdraw(example, bad)


def test_cli_withdraw_asks_first(study, monkeypatch, capsys):
    example, build, data, tmp = study
    monkeypatch.setattr("builtins.input", lambda _p: "P00")  # mistyped
    assert main(["withdraw", str(example), "P001"]) == 1
    assert (data / "P001").is_dir()
    monkeypatch.setattr("builtins.input", lambda _p: "P001")
    assert main(["withdraw", str(example), "P001", "--reason", "asked"]) == 0
    assert "withdrawn; 1 session(s)" in capsys.readouterr().out
    assert main(["withdraw", str(example), "P001", "--restore"]) == 0


def test_retention_reminds_and_deletes_only_when_asked(study):
    example, build, data, tmp = study
    edit_file(example / "study.yaml", "procedure:", "data:\n  keep_until: 2030-12-31\n  face_video_days: 30\n\nprocedure:")
    d = retention.due(example, today=dt.date(2026, 10, 18))
    assert d["keep_until"] == "2030-12-31" and not d["past_keep_until"] and d["sessions"] == []
    assert d["face_videos"] == []  # the simulated sessions have no front camera video
    cam = data / "P001" / "P001-20261004T100000" / "camera"
    cam.mkdir()
    (cam / "front_000.mp4").write_bytes(b"x")
    d = retention.due(example, today=dt.date(2026, 10, 18))
    assert d["face_videos"] == []  # 13 days after unloading: not due yet
    d = retention.due(example, today=dt.date(2026, 11, 10))  # 36 days
    assert [v["participant_id"] for v in d["face_videos"]] == ["P001"]
    r = retention.delete_due(example, "face_videos", today=dt.date(2026, 11, 10))
    assert r["files"] == 1 and not (cam / "front_000.mp4").exists() and (cam.parent / "session.json").is_file()
    later = dt.date(2031, 1, 1)
    assert len(retention.due(example, today=later)["sessions"]) == 2
    r = retention.delete_due(example, "sessions", today=later)
    assert len(r["deleted"]) == 2 and not (data / "P001").exists() and not (tmp / "backup" / "P002").exists()
    rows = register.read(data / register.REGISTER)[1]
    assert {x["status"] for x in rows} == {"deleted"}
    assert [x["action"] for x in log(data)] == ["retention: face videos", "retention: sessions"]


def test_storage_flags_cloud_folders(tmp_path, monkeypatch):
    monkeypatch.setenv("OneDrive", str(tmp_path / "OneDrive"))
    assert retention.cloud_folder(tmp_path / "OneDrive" / "data") == "OneDrive"
    assert retention.cloud_folder(tmp_path / "Dropbox" / "lab") == "Dropbox"
    assert retention.cloud_folder(tmp_path / "data") is None


def test_app_calls(study):
    from socialeyes.desktop.app import Api

    example, build, data, tmp = study
    api = Api()
    st = api.data_status(str(example))["ok"]
    assert [s["folder"] for s in st["storage"]] == ["data", "second copy"] and st["clear_after_unload"] is False
    assert st["retention"]["keep_until"] is None
    r = api.data_withdraw(str(example), "P001", "test")["ok"]
    assert r["action"] == "withdrawn" and r["sessions"] == ["P001-20261004T100000"]
    rows = {x["participant_id"]: x["status"] for x in api.data_status(str(example))["ok"]["register"]}
    assert rows == {"P001": "withdrawn", "P002": "active"}
    assert api.data_restore(str(example), "P001")["ok"]["action"] == "restored"
    assert "error" in api.data_delete_withdrawn(str(example), "P002", None)  # not withdrawn
