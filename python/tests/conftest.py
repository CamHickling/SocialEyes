import shutil
from pathlib import Path

import pytest

EXAMPLE = Path(__file__).resolve().parents[2] / "studies" / "example"


@pytest.fixture
def example(tmp_path: Path) -> Path:
    """A writable copy of studies/example."""
    dest = tmp_path / "example"
    shutil.copytree(EXAMPLE, dest)
    return dest


def edit_file(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text, f"{old!r} not in {path.name}"
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
