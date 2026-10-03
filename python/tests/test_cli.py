from conftest import EXAMPLE, edit_file
from socialeyes.cli import main


def test_validate_ok(capsys):
    assert main(["validate", str(EXAMPLE)]) == 0
    assert "OK: example" in capsys.readouterr().out


def test_validate_reports_errors(example, capsys):
    edit_file(example / "posts.csv", "crit01,critical,acc1", "crit01,critical,nobody")
    assert main(["validate", str(example)]) == 1
    assert "account_id 'nobody'" in capsys.readouterr().err


def test_compile(example, tmp_path, capsys):
    out = tmp_path / "build"
    assert main(["compile", str(example), "-o", str(out)]) == 0
    assert (out / "plans" / "P016.json").is_file()
    assert main(["compile", str(example), "-o", str(out)]) == 1  # exists, no --clean
    assert main(["compile", str(example), "-o", str(out), "--clean"]) == 0


def test_case_sheet_from_study(tmp_path):
    out = tmp_path / "sheet.svg"
    assert main(["case-sheet", "--width-mm", "70", "--height-mm", "152", "--study", str(EXAMPLE), "-o", str(out)]) == 0
    assert out.read_text().startswith("<svg")
    assert out.with_suffix(".json").is_file()
