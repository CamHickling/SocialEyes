"""The desktop app's Studies tab (list, status, copy of the example) and Content tab (file checklist)."""
import pytest

from socialeyes import settings
from socialeyes.desktop.studies import content_checklist, copy_example, list_studies
from socialeyes.desktop.studyfolder import FolderError
from socialeyes.session import register


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("SOCIALEYES_SETTINGS", str(tmp_path / "settings.json"))
    monkeypatch.setattr(settings, "workspace", lambda: tmp_path / "ws")
    return tmp_path / "ws"


def status_of(study_id):
    return next(s for s in list_studies()["studies"] if s["id"] == study_id)


def test_copy_example_and_status(ws):
    folder = copy_example("pilot")
    assert folder.endswith("pilot")
    s = status_of("pilot")
    assert s["status"] == "ready" and s["n_errors"] == 0 and s["n_sessions"] == 0
    assert "id: pilot" in (ws / "studies" / "pilot" / "study.yaml").read_text(encoding="utf-8")
    assert not (ws / "studies" / "pilot" / "make_placeholders.py").exists()

    (ws / "studies" / "pilot" / "images" / "fill01.png").unlink()
    s = status_of("pilot")
    assert s["status"] == "designing" and s["n_errors"] >= 1

    register.update(settings.data_dir("pilot") / register.REGISTER,
                    [{"participant_id": "P001", "session_uid": "u1", "started": "2026-10-05T10:00:00"}])
    s = status_of("pilot")
    assert s["status"] == "collecting data" and s["n_sessions"] == 1 and s["last_session"].startswith("2026-10-05")


def test_copy_example_refuses_bad_or_taken_ids(ws):
    copy_example("pilot")
    with pytest.raises(FolderError, match="already exists"):
        copy_example("pilot")
    for bad in ("", "my study", "../x"):
        with pytest.raises(FolderError, match="letters, digits"):
            copy_example(bad)


def test_list_without_studies_folder(ws):
    assert list_studies()["studies"] == []


def test_content_checklist(example):
    c = content_checklist(example)
    assert c["n_found"] == c["n_needed"] == 61
    kinds = {i["kind"] for i in c["items"]}
    assert kinds == {"image", "aoi", "avatar", "story", "video"}
    aoi = [i for i in c["items"] if i["kind"] == "aoi"]
    assert len(aoi) == 16 and all(i["what"].startswith("AOIs for post crit") for i in aoi)

    (example / "aois" / "crit03_retouched.json").unlink()
    (example / "avatars").rename(example / "avatars_gone")
    c = content_checklist(example)
    missing = {i["file"] for i in c["items"] if not i["found"]}
    assert "aois/crit03_retouched.json" in missing
    assert sum(1 for i in c["items"] if i["kind"] == "avatar" and not i["found"]) == 6
    assert c["n_found"] == 61 - 7


def test_content_checklist_on_an_unfinished_study(tmp_path):
    (tmp_path / "study.yaml").write_text("id: draft\n", encoding="utf-8")  # far from valid
    (tmp_path / "images.csv").write_text("file,post_id\nimages/a.jpg,p1\n", encoding="utf-8")
    c = content_checklist(tmp_path)
    assert [t["file"] for t in c["tables"] if not t["found"]] == ["accounts.csv", "posts.csv"]
    assert [(i["file"], i["found"]) for i in c["items"]] == [("images/a.jpg", False)]
