import json
import shutil

import pandas as pd
import pytest

from conftest import EXAMPLE
from socialeyes.cli import main
from socialeyes.session import register
from socialeyes.session.export import TABLES, export_study, factor_col
from socialeyes.session.io import load_session
from socialeyes.session.simulate import simulate_session
from socialeyes.study.compiler import compile_study


@pytest.fixture(scope="module")
def exported(tmp_path_factory):
    """Three sessions of the example study (P002 twice), one broken folder, and their export."""
    root = tmp_path_factory.mktemp("export")
    build, _ = compile_study(EXAMPLE, root / "build")
    data = root / "data"
    for pid, uid, seed in (("P001", "P001-a", 1), ("P002", "P002-a", 2), ("P002", "P002-b", 3)):
        out = simulate_session(build, pid, data / pid / uid, seed=seed)
        meta = json.loads((out / "session.json").read_text(encoding="utf-8"))
        meta["session_uid"] = uid  # the simulator names every session <participant>-sim; the app's are unique
        (out / "session.json").write_text(json.dumps(meta), encoding="utf-8")
    (data / "P009" / "P009-x").mkdir(parents=True)
    (data / "P009" / "P009-x" / "session.json").write_text("{not json", encoding="utf-8")
    register.update(data / register.REGISTER, [{"participant_id": "P001", "session_uid": "P001-a", "notes": ""},
                                               {"participant_id": "P002", "session_uid": "P002-a"},
                                               {"participant_id": "P002", "session_uid": "P002-b"}])
    cols, rows = register.read(data / register.REGISTER)
    for r in rows:
        if r["session_uid"] == "P001-a":
            r["notes"] = "fire alarm at 5 min"
    with (data / register.REGISTER).open("w", encoding="utf-8-sig", newline="") as fh:
        import csv
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    r = export_study(EXAMPLE, data, root / "out", build_for=lambda _f: build)
    tables = {t: pd.read_csv(root / "out" / f"{t}.csv", encoding="utf-8-sig", keep_default_na=False, na_values=[""])
              for t in TABLES}
    return build, data, r, tables, root


def test_export_writes_every_table_and_skips_broken_sessions(exported):
    _, _, r, t, root = exported
    assert r.sessions == 3
    assert len(r.skipped) == 1 and "P009-x" in r.skipped[0][0]
    assert sorted(p.name for p in (root / "out").iterdir()) == ["by_condition.csv", "by_item.csv", "by_session.csv",
                                                                "codebook.csv", "exploration", "exploration.html"]
    assert (root / "out" / "by_item.csv").read_bytes().startswith(b"\xef\xbb\xbf")  # Excel reads UTF-8 with a BOM
    assert len(t["by_session"]) == 3
    assert len(t["by_item"]) == 3 * 20
    assert len(t["by_condition"]) == 3 * (4 + 1)  # the 4 within cells and the fillers


def test_by_session(exported):
    build, data, _, t, _ = exported
    s = t["by_session"].set_index("session_uid")
    plan = json.loads((build / "plans" / "P002.json").read_text(encoding="utf-8"))
    assert s.loc["P002-b", "group"] == plan["group"] and s.loc["P002-b", "comments"] == plan["between"]["comments"]
    assert s.loc["P002-a", "duplicate_id"] == 1 and s.loc["P001-a", "duplicate_id"] == 0
    assert s.loc["P001-a", "notes"] == "fire alarm at 5 min"
    sess = load_session(data / "P002" / "P002-b")
    ev = sess.events
    pre = ev[(ev["type"] == "response") & (ev["item_id"] == "body_sat_pre")]["value"].iloc[-1]
    assert s.loc["P002-b", "body_sat_pre"] == pytest.approx(pre)
    likes = ev[ev["type"] == "like"].groupby("post_id")["liked"].last()
    assert s.loc["P002-b", "likes"] == int(likes.sum())
    assert s.loc["P002-b", "completed"] == 1
    assert 0 <= s.loc["P002-b", "recog_hit_rate"] <= 1


def test_by_item_attaches_answers_to_the_right_post(exported):
    build, data, _, t, _ = exported
    items = t["by_item"]
    mine = items[items["session_uid"] == "P001-a"].set_index("post_id")
    plan = json.loads((build / "plans" / "P001.json").read_text(encoding="utf-8"))
    assert list(mine.index) == [p["post_id"] for p in plan["feed"]]
    crit = next(p for p in plan["feed"] if p["role"] == "critical")
    assert mine.loc[crit["post_id"], "edit"] == crit["conditions"]["edit"]
    assert mine.loc[crit["post_id"], "image_id"] == crit["image_id"]
    ev = load_session(data / "P001" / "P001-a").events
    r = ev[(ev["type"] == "response") & (ev["step_id"] == "ratings") & (ev["item_id"] == "attractive")]
    trials = plan["steps"]["ratings"]["trials"]
    for row in r.itertuples():
        assert mine.loc[trials[int(row.trial)]["post_id"], "attractive"] == row.value
    rec = plan["steps"]["recog"]["trials"]
    said = ev[(ev["type"] == "response") & (ev["step_id"] == "recog") & (ev["item_id"] == "old_new")]
    for row in said.itertuples():
        trial = rec[int(row.trial)]
        if trial["kind"] == "old":
            assert mine.loc[trial["post_id"], "recog_old_response"] == row.value
            assert mine.loc[trial["post_id"], "recog_old_correct"] == int(row.value == "old")
    fillers = mine[mine["role"] == "filler"]
    assert fillers["attractive"].isna().all() and fillers["cell"].isna().all()
    liked = ev[ev["type"] == "like"].groupby("post_id")["liked"].last()
    for pid, v in liked.items():
        assert mine.loc[pid, "liked"] == int(v)


def test_by_condition_averages_the_cells_posts(exported):
    _, _, _, t, _ = exported
    items, cond = t["by_item"], t["by_condition"]
    mine = items[(items["session_uid"] == "P002-a") & (items["role"] == "critical")]
    cell = mine["cell"].iloc[0]
    row = cond[(cond["session_uid"] == "P002-a") & (cond["cell"] == cell)].iloc[0]
    posts = mine[mine["cell"] == cell]
    assert row["n_posts"] == len(posts)
    assert row["image_weighted_s"] == pytest.approx(posts["image_weighted_s"].mean(), abs=1e-4)
    assert row["attractive"] == pytest.approx(posts["attractive"].mean(), abs=1e-4)
    filler = cond[(cond["session_uid"] == "P002-a") & (cond["cell"] == "filler")].iloc[0]
    assert filler["n_posts"] == (items[(items["session_uid"] == "P002-a")]["role"] == "filler").sum()
    assert "recog_old_response" not in cond.columns  # answers, not measures


def test_codebook_explains_every_column(exported):
    _, _, _, t, root = exported
    book = pd.read_csv(root / "out" / "codebook.csv", encoding="utf-8-sig", keep_default_na=False)
    for name, df in t.items():
        described = book[book["table"] == name]
        assert list(described["column"]) == list(df.columns)
        assert (described["description"] != "").all(), described[described["description"] == ""]
    q = book[(book["table"] == "by_session") & (book["column"] == "body_sat_pre")].iloc[0]
    assert "How satisfied are you with your body" in q["description"] and q["values"].startswith("0-1")


def test_factor_named_like_a_fixed_column_gets_a_suffix():
    assert factor_col("seen") == "seen_level"
    assert factor_col("edit") == "edit"


def test_cli_export(exported, tmp_path, capsys):
    _, data, _, _, _ = exported
    copy = tmp_path / "data"
    shutil.copytree(data, copy, ignore=shutil.ignore_patterns("P009"))
    assert main(["export", str(EXAMPLE), "--data", str(copy)]) == 0
    assert "3 session(s)" in capsys.readouterr().out
    assert (copy / "export" / "by_item.csv").is_file()
    # the export folder inside the data folder isn't taken for a session the next time
    assert main(["export", str(EXAMPLE), "--data", str(copy)]) == 0
    assert "3 session(s)" in capsys.readouterr().out


def test_cli_export_without_data(tmp_path, capsys):
    assert main(["export", str(EXAMPLE), "--data", str(tmp_path / "nothing")]) == 1
    assert "unload some sessions first" in capsys.readouterr().err


def test_desktop_export_uses_the_study_folders(exported, tmp_path, monkeypatch):
    from socialeyes import settings
    from socialeyes.desktop.app import Api

    _, data, _, _, _ = exported
    monkeypatch.setenv("SOCIALEYES_SETTINGS", str(tmp_path / "settings.json"))
    copy = tmp_path / "sessions"
    shutil.copytree(data, copy, ignore=shutil.ignore_patterns("P009"))
    settings.set_study("example", data_dir=str(copy))
    r = Api().data_export(str(EXAMPLE))["ok"]
    assert r["sessions"] == 3 and r["out_dir"] == str(copy / "export")
    assert settings.export_dir("example") == copy / "export"


def test_exploration_is_blinded_until_unblinded(exported, tmp_path):
    build, data, r, _, root = exported
    page = (root / "out" / "exploration.html").read_text(encoding="utf-8")
    assert r.exploration.endswith("exploration.html") and not r.unblinded
    assert "Blinded." in page and "condition A" in page and "group X" in page
    levels = ["original", "retouched", "edited", "neutral", "appearance", "edit=", "label=", "comments="]
    assert not [w for w in levels if w in page.replace("by_session", "")]  # no condition name gives anything away
    assert "Image time on screen" in page and "Rating: attractive" in page and "Questionnaire: body_sat_pre" in page
    assert len(list((root / "out" / "exploration").glob("*.png"))) >= 10
    # the same codes every time
    again = export_study(EXAMPLE, data, tmp_path / "again", build_for=lambda _f: build)
    assert (tmp_path / "again" / "exploration.html").read_text(encoding="utf-8").split("<h2>Per post</h2>")[1] \
        .count("condition") == page.split("<h2>Per post</h2>")[1].count("condition")
    open_ = export_study(EXAMPLE, data, tmp_path / "open", build_for=lambda _f: build, unblind=True)
    shown = (tmp_path / "open" / "exploration.html").read_text(encoding="utf-8")
    assert open_.unblinded and "Unblinded:" in shown and "edit=original|label=none" in shown


def test_exploration_outliers_skip_yes_no_measures():
    import pandas as pd
    from socialeyes.session.explore import _outliers

    assert _outliers(pd.Series([0, 1, 0, 0, 1, 1, 0, 1])) is None
    assert _outliers(pd.Series([1, 2, 3, 2, 3, 2, 50.0])) == 1


def test_cli_unblind_flag(exported, tmp_path, capsys):
    _, data, _, _, _ = exported
    copy = tmp_path / "data"
    shutil.copytree(data, copy, ignore=shutil.ignore_patterns("P009"))
    assert main(["export", str(EXAMPLE), "--data", str(copy)]) == 0
    assert "blinded: conditions as codes" in capsys.readouterr().out
    assert main(["export", str(EXAMPLE), "--data", str(copy), "--unblind"]) == 0
    assert "UNBLINDED" in capsys.readouterr().out
