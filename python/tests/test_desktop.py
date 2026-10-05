"""The desktop app's study-folder handling and its bridge (no window needed)."""
import pytest

from socialeyes.desktop.app import Api, builder_page
from socialeyes.desktop.studyfolder import (FolderError, check_folder, new_study_folder, read_study,
                                            save_study)


def test_read_study(example, tmp_path):
    r = read_study(example)
    assert r["yaml"].startswith("#") and "id: example" in r["yaml"]
    assert "posts.csv" in r["files"] and "study.yaml" in r["files"]
    with pytest.raises(FolderError, match="no study.yaml"):
        read_study(tmp_path)


def test_save_never_overwrites_existing_files(example):
    posts = (example / "posts.csv").read_text(encoding="utf-8")
    old_yaml = (example / "study.yaml").read_text(encoding="utf-8")
    r = save_study(example, {"study.yaml": "id: example\n", "posts.csv": "post_id,role\n",
                             "captions.csv": "post_id,variant,text\n", "NEXT_STEPS.txt": "next\n"})
    assert r["written"] == ["study.yaml", "captions.csv", "NEXT_STEPS.txt"]
    assert r["kept"] == ["posts.csv"] and r["backup"] is True
    assert (example / "posts.csv").read_text(encoding="utf-8") == posts  # the researcher's file is untouched
    assert (example / "study.yaml").read_text(encoding="utf-8") == "id: example\n"
    assert (example / "study.yaml.bak").read_text(encoding="utf-8") == old_yaml
    assert not (example / "study.yaml.tmp").exists()
    # saving the same study.yaml again doesn't replace the backup
    assert save_study(example, {"study.yaml": "id: example\n"})["backup"] is False
    assert (example / "study.yaml.bak").read_text(encoding="utf-8") == old_yaml


def test_save_creates_the_folder_and_stays_inside_it(tmp_path):
    folder = tmp_path / "new" / "study"
    assert save_study(folder, {"study.yaml": "id: s\n"})["written"] == ["study.yaml"]
    assert (folder / "study.yaml").is_file()
    for bad in ("../evil.csv", "/abs.csv", "C:/abs.csv", "..\\evil.csv"):
        with pytest.raises(FolderError, match="refusing"):
            save_study(folder, {"study.yaml": "id: s\n", bad: "x"})
    assert not (tmp_path / "new" / "evil.csv").exists()
    with pytest.raises(FolderError, match="no study.yaml"):
        save_study(folder, {"posts.csv": "x"})


def test_new_study_folder(example):
    parent = example.parent
    assert new_study_folder(parent, "pilot") == parent / "pilot"
    with pytest.raises(FolderError, match="already contains a study"):
        new_study_folder(parent, "example")
    for bad in ("", "a/b", "..", 'x"y'):
        with pytest.raises(FolderError, match="id"):
            new_study_folder(parent, bad)


def test_check_folder_reports_what_the_compiler_finds(example):
    assert check_folder(example)["errors"] == []
    (example / "images" / "fill01.png").unlink()
    errors = check_folder(example)["errors"]
    assert any("fill01.png" in e for e in errors)


def test_bridge_returns_results_or_messages(example, tmp_path):
    api = Api()
    r = api.open_folder(str(example))["ok"]
    assert r["study"]["folder"] == str(example) and r["check"]["errors"] == []
    assert "no study.yaml" in api.open_folder(str(tmp_path))["error"]

    yaml = (example / "study.yaml").read_text(encoding="utf-8").replace("version: 1", "version: 2")
    r = api.save(str(example), {"study.yaml": yaml, "posts.csv": "ignored"})["ok"]
    assert r["saved"]["kept"] == ["posts.csv"] and r["check"]["errors"] == []

    r = api.save_new(str(tmp_path), "copy", {"study.yaml": "id: copy\n"})["ok"]
    assert r["saved"]["folder"] == str(tmp_path / "copy")
    assert r["check"]["errors"]  # a study.yaml alone is far from a complete study
    assert "already contains" in api.save_new(str(tmp_path), "copy", {"study.yaml": "id: copy\n"})["error"]
    assert api.check(str(example))["ok"]["errors"] == []
    assert api.app_info()["ok"]["version"]


def test_builder_page_is_built():
    page = builder_page().read_text(encoding="utf-8")
    assert "pywebviewready" in page and "Save to study folder" in page
