"""Protecting studies that have sessions: which edits break them (CAM-160)."""
import pytest
from PIL import Image

from conftest import edit_file
from socialeyes import settings
from socialeyes.desktop.app import Api
from socialeyes.desktop.studyfolder import protection_check
from socialeyes.phone import unload as U
from socialeyes.phone.loader import build_study, discard, keep_snapshot
from socialeyes.session import register
from socialeyes.study.compiler import compile_study, package_hash
from socialeyes.study.protect import breaking_changes


@pytest.fixture
def base(example, tmp_path):
    out, _ = compile_study(example, tmp_path / "base")
    return out


def rebuild(example, tmp_path, name="new"):
    out, _ = compile_study(example, tmp_path / name)
    return out


def test_identical_and_text_only_edits_are_safe(example, tmp_path, base):
    assert breaking_changes(base, rebuild(example, tmp_path, "same")) == []
    edit_file(example / "posts.csv", "Sunday reset", "Sunday reset!")                   # caption typo
    edit_file(example / "comments.csv", "Love this!", "Love this!!")                    # comment wording
    edit_file(example / "study.yaml", "How satisfied are you with your body right now?",
              "How satisfied are you with your body at the moment?")                     # question wording
    edit_file(example / "study.yaml", "title: ", "title: New ")
    assert breaking_changes(base, rebuild(example, tmp_path)) == []


def test_more_plans_is_safe_fewer_is_not(example, tmp_path, base):
    edit_file(example / "study.yaml", "n_plans: 16", "n_plans: 24")
    assert breaking_changes(base, rebuild(example, tmp_path, "more")) == []
    edit_file(example / "study.yaml", "n_plans: 24", "n_plans: 8")
    reasons = breaking_changes(base, rebuild(example, tmp_path, "fewer"))
    assert len(reasons) == 1 and "P009" in reasons[0] and "no longer have a plan" in reasons[0]


@pytest.mark.parametrize("edit, expected", [
    (("study.yaml", "seed: 20251001", "seed: 7"), "post order or conditions"),
    (("comments.csv", "crit01,neutral,1,", "crit01,neutral,3,"), "comments shown"),
    (("study.yaml", "id: body_sat_pre,", "id: body_satisfaction_pre,"), "data's columns"),
    (("study.yaml", "id: example", "id: example2"), "study id would change"),
])
def test_breaking_edits(example, tmp_path, base, edit, expected):
    edit_file(example / edit[0], edit[1], edit[2])
    reasons = breaking_changes(base, rebuild(example, tmp_path))
    assert any(expected in r for r in reasons), reasons


def test_replacing_an_image_under_the_same_name_is_breaking(example, tmp_path, base):
    path = example / "images" / "crit03_retouched.png"
    Image.open(path).convert("RGB").rotate(180).save(path)
    reasons = breaking_changes(base, rebuild(example, tmp_path))
    assert any("image crit03_retouched" in r for r in reasons), reasons


@pytest.fixture
def with_sessions(example, tmp_path, monkeypatch):
    """The example study with one registered session and the build it ran kept as a snapshot."""
    monkeypatch.setenv("SOCIALEYES_SETTINGS", str(tmp_path / "settings.json"))
    monkeypatch.setattr(settings, "workspace", lambda: tmp_path / "ws")
    s = build_study(example)
    try:
        snap = keep_snapshot(s)
        sha = s.package_sha256
    finally:
        discard(s)
    register.update(settings.data_dir("example") / register.REGISTER,
                    [{"participant_id": "P001", "session_uid": "u1", "package_sha256": sha}])
    return example, snap


def test_snapshot_is_the_exact_build(with_sessions):
    example, snap = with_sessions
    _, rows = register.read(settings.data_dir("example") / register.REGISTER)
    assert snap is not None and package_hash(snap) == rows[0]["package_sha256"]
    assert snap == settings.data_dir("example") / "builds" / rows[0]["package_sha256"][:16]


def test_protection_check(with_sessions):
    example, snap = with_sessions
    yaml_text = (example / "study.yaml").read_text(encoding="utf-8")
    assert protection_check(example, yaml_text) is None                                   # unchanged
    assert protection_check(example, yaml_text.replace("title: ", "title: Renamed ")) is None
    p = protection_check(example, yaml_text.replace("seed: 20251001", "seed: 7"))
    assert p["sessions"] == 1 and p["version"] == 1 and any("post order" in r for r in p["reasons"])
    bumped = yaml_text.replace("seed: 20251001", "seed: 7").replace("version: 1", "version: 2")
    assert protection_check(example, bumped) is None                                      # a new version is fine
    assert not (example / ".socialeyes-proposed.yaml").exists()
    # the snapshot is the baseline: a breaking edit made outside the app (here: on disk) is still caught
    edit_file(example / "study.yaml", "seed: 20251001", "seed: 7")
    p = protection_check(example, (example / "study.yaml").read_text(encoding="utf-8"))
    assert p and any("post order" in r for r in p["reasons"])


def test_save_refuses_breaking_edit_until_new_version(with_sessions):
    example, _ = with_sessions
    api = Api()
    yaml_text = (example / "study.yaml").read_text(encoding="utf-8")
    r = api.save(str(example), {"study.yaml": yaml_text.replace("seed: 20251001", "seed: 7")})["ok"]
    assert "needs_version" in r and "seed: 20251001" in (example / "study.yaml").read_text(encoding="utf-8")
    bumped = yaml_text.replace("seed: 20251001", "seed: 7").replace("version: 1", "version: 2")
    r = api.save(str(example), {"study.yaml": bumped})["ok"]
    assert r["saved"]["written"] == ["study.yaml"] and r["sessions"] == 1
    assert api.open_folder(str(example))["ok"]["sessions"] == 1


def test_loader_blocks_breaking_edits_made_outside_the_app(with_sessions, monkeypatch):
    from socialeyes.phone import loader

    example, _ = with_sessions
    edit_file(example / "study.yaml", "seed: 20251001", "seed: 7")   # e.g. edited in a text editor
    monkeypatch.setattr(loader, "read_phone", lambda adb: loader.PhoneState(
        serial="X", app_installed=True, app_version_code=1, app_version_name="0.1.0", battery=90, free_bytes=2**40))
    r, study, _ = loader._assess(None, example)
    discard(study)
    assert r.checks[0].level == "block" and "Save it as version 2" in r.checks[0].text
    edit_file(example / "study.yaml", "version: 1", "version: 2")
    r, study, _ = loader._assess(None, example)
    discard(study)
    assert not any(c.level == "block" for c in r.checks)


def test_unload_analyses_with_the_snapshot(with_sessions, tmp_path):
    example, snap = with_sessions
    session = tmp_path / "s"
    session.mkdir()
    (session / "session.json").write_text(f'{{"package_sha256": "{package_hash(snap)}"}}', encoding="utf-8")
    assert U._build_for(session, "example", None) == snap
    (session / "session.json").write_text('{"package_sha256": "' + "0" * 64 + '"}', encoding="utf-8")
    assert U._build_for(session, "example", None) is None
