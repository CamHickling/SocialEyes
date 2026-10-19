"""Golden sessions (CAM-187): four fixed simulated sessions of the example study, analysed and exported,
compared with the results saved in tests/golden/. A change that alters any number fails here.

When a change is meant to alter the results, check the differences, then save the new results:

    $env:UPDATE_GOLDEN = "1"; python -m pytest python/tests/test_golden.py; Remove-Item Env:UPDATE_GOLDEN

and commit tests/golden/ with the change, saying why the numbers changed.
"""
import json
import math
import os
import shutil
from pathlib import Path

import pandas as pd
import pytest

from conftest import EXAMPLE
from socialeyes.session.analyze import analyze_session
from socialeyes.session.export import export_study
from socialeyes.session.simulate import simulate_session
from socialeyes.study.compiler import compile_study

GOLDEN = Path(__file__).parent / "golden"
PARTICIPANTS = ("P001", "P002", "P003", "P004")
# build-dependent, not results: the package hash changes with any compiler change
VOLATILE = {"package_sha256", "event_types"}


def _clean(q: dict) -> dict:
    return {k: v for k, v in q.items() if k not in VOLATILE}


@pytest.fixture(scope="module")
def outputs(tmp_path_factory):
    root = tmp_path_factory.mktemp("golden")
    build, _ = compile_study(EXAMPLE, root / "build")
    data = root / "data"
    out = {}
    for k, pid in enumerate(PARTICIPANTS):
        session = simulate_session(build, pid, data / pid / f"{pid}-golden", seed=100 + k)
        meta = json.loads((session / "session.json").read_text(encoding="utf-8"))
        meta["session_uid"] = f"{pid}-golden"
        (session / "session.json").write_text(json.dumps(meta), encoding="utf-8")
        r = analyze_session(session, build)
        out[f"{pid}/quality.json"] = _clean(r["quality"])
        out[f"{pid}/exposure.csv"] = r["exposure"]
        out[f"{pid}/gestures.csv"] = r["strokes"]["gesture"].value_counts().sort_index().rename_axis("gesture").reset_index()
        out[f"{pid}/touch_targets.csv"] = r["touch_targets"].groupby(["post_id", "aoi"], dropna=False).size() \
            .rename("samples").reset_index()
    export_study(EXAMPLE, data, root / "export", build_for=lambda _f: build)
    for t in ("by_session", "by_item", "by_condition", "codebook"):
        out[f"export/{t}.csv"] = pd.read_csv(root / "export" / f"{t}.csv", encoding="utf-8-sig", keep_default_na=False,
                                             na_values=[""])
    return out


def _save(name: str, value) -> None:
    path = GOLDEN / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, pd.DataFrame):
        value.to_csv(path, index=False, lineterminator="\n")
    else:
        path.write_text(json.dumps(value, indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _close(a, b, where: str) -> None:
    if isinstance(a, dict) and isinstance(b, dict):
        assert sorted(a) == sorted(b), f"{where}: keys differ: {sorted(set(a) ^ set(b))}"
        for k in a:
            _close(a[k], b[k], f"{where}.{k}")
    elif isinstance(a, list) and isinstance(b, list):
        assert len(a) == len(b), f"{where}: {len(a)} items, golden {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            _close(x, y, f"{where}[{i}]")
    elif isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        assert math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9), f"{where}: {a} != golden {b}"
    else:
        assert a == b, f"{where}: {a!r} != golden {b!r}"


@pytest.mark.parametrize("name", [f"{p}/{f}" for p in PARTICIPANTS
                                  for f in ("quality.json", "exposure.csv", "gestures.csv", "touch_targets.csv")]
                         + [f"export/{t}.csv" for t in ("by_session", "by_item", "by_condition", "codebook")])
def test_matches_golden(outputs, name):
    value = outputs[name]
    if os.environ.get("UPDATE_GOLDEN") == "1":
        _save(name, value)
        pytest.skip("golden result saved")
    path = GOLDEN / name
    assert path.is_file(), f"no golden result {path}: run with UPDATE_GOLDEN=1 and commit it"
    if isinstance(value, pd.DataFrame):
        golden = pd.read_csv(path, keep_default_na=False, na_values=[""])
        fresh = pd.read_csv(pd.io.common.StringIO(value.to_csv(index=False, lineterminator="\n")),
                            keep_default_na=False, na_values=[""])
        assert list(fresh.columns) == list(golden.columns), f"{name}: columns changed"
        pd.testing.assert_frame_equal(fresh, golden, check_exact=False, rtol=1e-9, atol=1e-9, check_dtype=False)
    else:
        _close(json.loads(json.dumps(value, default=str)), json.loads(path.read_text(encoding="utf-8")), name)


def test_golden_files_are_all_used():
    used = {f"{p}/{f}" for p in PARTICIPANTS for f in ("quality.json", "exposure.csv", "gestures.csv", "touch_targets.csv")} \
        | {f"export/{t}.csv" for t in ("by_session", "by_item", "by_condition", "codebook")}
    if not GOLDEN.is_dir():
        pytest.skip("no golden results yet")
    found = {p.relative_to(GOLDEN).as_posix() for p in GOLDEN.rglob("*") if p.is_file()}
    assert found <= used, f"golden files nobody checks: {sorted(found - used)}"
