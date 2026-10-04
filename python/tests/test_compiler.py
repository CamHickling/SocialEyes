import json
from collections import Counter

import pytest

from conftest import EXAMPLE, edit_file
from socialeyes.study.compiler import StudyError, build_plans, check_study, compile_study, load_study


def errors_of(path):
    b, rep = check_study(path)
    assert b is None
    return "\n".join(rep.errors)


def test_example_study_is_valid():
    b, rep = check_study(EXAMPLE)
    assert rep.errors == []
    assert rep.warnings == []
    assert len(b.critical) == 8 and len(b.fillers) == 12


def test_plans_are_reproducible():
    b = load_study(EXAMPLE)
    assert build_plans(b) == build_plans(load_study(EXAMPLE))


def test_every_post_in_every_cell_equally_often_per_block():
    b = load_study(EXAMPLE)
    plans = build_plans(b)[:8]  # one balanced block: 2 groups x 4 lists
    assert Counter((p["group"], p["list"]) for p in plans) == Counter({(g, l): 1 for g in (0, 1) for l in range(4)})
    per_post = Counter()
    for p in plans:
        crit = [e for e in p["feed"] if e["role"] == "critical"]
        assert len(crit) == 8
        assert Counter(e["cell"] for e in crit) == Counter({c: 2 for c in set(e["cell"] for e in crit)})
        per_post.update((e["post_id"], e["cell"]) for e in crit)
    assert set(per_post.values()) == {2}  # 8 posts x 4 cells, each twice per block


def test_conditions_are_applied():
    b = load_study(EXAMPLE)
    for p in build_plans(b):
        for e in p["feed"]:
            if e["role"] != "critical":
                assert e["label"] is None
                assert e["comment_variant"] == ""  # comments factor applies to critical posts only
                assert e["conditions"] == {}
                continue
            c = e["conditions"]
            assert e["image_id"] == f"{e['post_id']}_{c['edit']}"
            assert e["label"] == (None if c["label"] == "none" else "edited")
            assert e["comment_variant"] == p["between"]["comments"]
            assert len(e["comments"]) == 2


def test_feed_constraints_hold():
    b = load_study(EXAMPLE)
    for p in build_plans(b):
        roles = [e["role"] for e in p["feed"]]
        assert roles[:2] == ["filler", "filler"]
        assert "critical,critical" not in ",".join(roles)
        crit_cells = [e["cell"] for e in p["feed"] if e["role"] == "critical"]
        assert all(not (a == b_ == c) for a, b_, c in zip(crit_cells, crit_cells[1:], crit_cells[2:]))


def test_recognition_trials():
    b = load_study(EXAMPLE)
    plan = build_plans(b)[0]
    trials = plan["steps"]["recog"]["trials"]
    kinds = Counter(t["kind"] for t in trials)
    assert kinds == {"old": 8, "alternate": 8, "foil": 2}
    seen = {e["image_id"] for e in plan["feed"]}
    for t in trials:
        assert (t["image_id"] in seen) == (t["kind"] == "old")
    assert len(plan["steps"]["ratings"]["trials"]) == 8


def test_compile_writes_package(example, tmp_path):
    out, _ = compile_study(example, tmp_path / "build")
    manifest = json.loads((out / "study.json").read_text(encoding="utf-8"))
    assert manifest["study"]["id"] == "example"
    assert len(list((out / "plans").glob("P*.json"))) == 16
    for img in manifest["images"].values():
        assert (out / img["file"]).is_file()
        if img["aoi"]:
            assert (out / img["aoi"]).is_file()
    for acc in manifest["accounts"].values():
        assert (out / acc["avatar"]).is_file()
    assert sorted(p.name for p in (out / "tags").iterdir()) == [f"tag36h11_{i}.png" for i in range(4)]
    aoi = json.loads((out / "aois" / "crit01_original.json").read_text())
    assert [a["name"] for a in aoi["aois"]] == ["face", "waist", "legs"]


def test_compile_refuses_to_overwrite(example, tmp_path):
    out = tmp_path / "build"
    compile_study(example, out)
    with pytest.raises(FileExistsError):
        compile_study(example, out)
    compile_study(example, out, clean=True)
    other = tmp_path / "not_a_build"
    other.mkdir()
    (other / "notes.txt").write_text("keep me")
    with pytest.raises(FileExistsError):
        compile_study(example, other, clean=True)
    assert (other / "notes.txt").is_file()


def test_errors_are_collected_not_first_only(example):
    edit_file(example / "posts.csv", "crit01,critical,acc1", "crit01,critical,nobody")
    edit_file(example / "images.csv", "crit02_retouched,images/crit02_retouched.png,crit02,retouched",
              "crit02_retouched,images/missing.png,crit02,retouched")
    errs = errors_of(example)
    assert "account_id 'nobody'" in errs
    assert "'images/missing.png' not found" in errs


def test_missing_image_version(example):
    edit_file(example / "images.csv", "crit03,retouched", "crit03,edited")
    assert "post crit03 has no image with version 'retouched'" in errors_of(example)


def test_missing_comment_variant(example):
    edit_file(example / "comments.csv", "crit04,appearance,1", "crit04,apearance,1")
    edit_file(example / "comments.csv", "crit04,appearance,2", "crit04,apearance,2")
    assert "post crit04 has no comments with variant 'appearance'" in errors_of(example)


def test_undefined_label(example):
    edit_file(example / "study.yaml", "edited: edited}", "edited: altered}")
    assert "label 'altered' is not defined" in errors_of(example)


def test_missing_aoi_for_critical_image(example):
    (example / "aois" / "crit05_original.json").unlink()
    assert "need an AOI file" in errors_of(example)


def test_aoi_size_mismatch(example):
    path = example / "aois" / "crit06_original.json"
    data = json.loads(path.read_text())
    data["width"] = 1080
    path.write_text(json.dumps(data))
    assert "is for a 1080x675 image" in errors_of(example)


def test_foil_must_not_belong_to_a_post(example):
    edit_file(example / "study.yaml", "foils: [foil01, foil02]", "foils: [foil01, fill01]")
    assert "foil 'fill01' belongs to post fill01" in errors_of(example)


def test_unknown_csv_column(example):
    edit_file(example / "posts.csv", "posted_ago", "posted")
    assert "unknown column(s) ['posted']" in errors_of(example)


def test_schema_errors_are_reported(example):
    edit_file(example / "study.yaml", "lead_in_fillers: 2", "lead_in_filers: 2")
    assert "feed.lead_in_filers" in errors_of(example)


def test_infeasible_feed_constraints(example):
    edit_file(example / "study.yaml", "min_fillers_between_critical: 1", "min_fillers_between_critical: 3")
    assert "min_fillers_between_critical=3" in errors_of(example)


def test_between_only_design_ignores_run_rule(example):
    # no within-subject factor: every critical post shares one cell
    for name in ("edit", "label"):
        edit_file(example / "study.yaml", f"  - name: {name}\n    design: within", f"  - name: {name}\n    design: between")
    b, rep = check_study(example)
    assert rep.errors == []


def test_warnings_for_unbalanced_numbers(example):
    edit_file(example / "study.yaml", "n_plans: 16", "n_plans: 10")
    b, rep = check_study(example)
    assert b is not None
    assert any("not a multiple of the assignment block size 8" in w for w in rep.warnings)


def test_caption_variants(example):
    edit_file(example / "study.yaml", "factors:\n", "factors:\n  - name: tone\n    design: between\n"
              "    levels: [plain, body]\n    sets:\n      caption_variant: \"{level}\"\n")
    with pytest.raises(StudyError, match="no caption with variant 'plain'"):
        load_study(example)
    rows = ["post_id,variant,text"] + [f"crit{n:02d},{v},{v} caption {n}" for n in range(1, 9) for v in ("plain", "body")]
    (example / "captions.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    b = load_study(example)
    for p in build_plans(b):
        for e in p["feed"]:
            if e["role"] == "critical":
                assert e["caption"].startswith(p["between"]["tone"] + " caption")


def test_profile_photo_step(example):
    _, rep = check_study(example)
    assert rep.errors == [] and not any("profile_photo" in w for w in rep.warnings)
    y = example / "study.yaml"
    edit_file(y, "  - {id: photo, type: profile_photo}", "")
    edit_file(y, "  - {id: feed, type: feed}", "  - {id: feed, type: feed}\n  - {id: photo, type: profile_photo}")
    _, rep = check_study(example)
    assert any("profile_photo step comes after the feed" in w for w in rep.warnings)


def test_stories(example, tmp_path):
    out, rep = compile_study(example, tmp_path / "build")
    stories = json.loads((out / "study.json").read_text(encoding="utf-8"))["stories"]
    assert [s["story_id"] for s in stories[:3]] == ["acc3_1", "acc3_2", "acc6_1"]  # grouped by account, csv order
    assert stories[0]["width"] == 540 and stories[0]["height"] == 960
    assert stories[0]["duration_s"] == 5.0  # feed.story_duration_s default
    assert (out / stories[0]["file"]).is_file()


def test_story_errors(example):
    edit_file(example / "stories.csv", "acc5,stories/acc5_1.png,8h", "nobody,stories/missing.png,8h")
    _, rep = check_study(example)
    assert any("account_id 'nobody'" in e for e in rep.errors)


def test_reels(example, tmp_path):
    out, rep = compile_study(example, tmp_path / "build")
    reels = json.loads((out / "study.json").read_text(encoding="utf-8"))["reels"]
    assert [r["reel_id"] for r in reels] == ["acc3_reel1", "acc1_reel1", "acc6_reel1"]
    assert (reels[0]["width"], reels[0]["height"]) == (540, 960)
    assert reels[0]["duration_s"] == pytest.approx(6.0, abs=0.1)
    assert (out / reels[0]["file"]).is_file()


def test_reel_must_be_a_video(example):
    edit_file(example / "reels.csv", "reels/acc1_reel1.mp4", "images/fill01.png")
    _, rep = check_study(example)
    assert any("is not a readable video" in e for e in rep.errors)


def test_ids_default_to_file_names_and_positions(example, tmp_path):
    # image_id may be left out: the file name without extension
    text = (example / "images.csv").read_text(encoding="utf-8")
    (example / "images.csv").write_text("\n".join(l.split(",", 1)[1] for l in text.splitlines()) + "\n", encoding="utf-8")
    out, rep = compile_study(example, tmp_path / "build")
    study = json.loads((out / "study.json").read_text(encoding="utf-8"))
    assert "crit01_original" in study["images"] and "foil01" in study["images"]
    plan = json.loads((out / "plans" / "P001.json").read_text(encoding="utf-8"))
    ids = [c["comment_id"] for p in plan["feed"] for c in p["comments"]]
    assert "crit01_neutral_1" in ids or "crit01_appearance_1" in ids
    assert len(ids) == len(set(ids))


def test_explicit_comment_ids_and_id_rules(example):
    edit_file(example / "comments.csv", "post_id,variant,", "comment_id,post_id,variant,")
    text = (example / "comments.csv").read_text(encoding="utf-8").splitlines()
    rows = [text[0]] + [f",{l}" for l in text[1:]]
    rows[1] = "warm hello" + rows[1]   # space: not allowed
    rows[2] = "p3" + rows[2]           # reserved for the participant's own comments
    (example / "comments.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    edit_file(example / "accounts.csv", "acc1,", "acc 1,")
    errors = errors_of(example)
    assert "comment_id 'warm hello' may only contain letters, digits, _ and -" in errors
    assert "comment_id 'p3' is reserved" in errors
    assert "account_id 'acc 1' may only contain" in errors


def test_story_ids_from_file_names_must_be_unique(example):
    edit_file(example / "stories.csv", "acc3,stories/acc3_2.png", "acc3,stories/acc3_1.png")
    assert "story_id 'acc3_1'" in errors_of(example)
