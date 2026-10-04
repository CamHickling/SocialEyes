"""Stitch the experiment builder into one offline file: builder/index.html.

Edit the files in builder/src/, then run:  python builder/build.py
"""
from pathlib import Path

HERE = Path(__file__).parent


def _read(path: Path) -> str:
    # git may check files out with Windows line endings; the output is always \n
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def render() -> str:
    """The finished page."""
    page = _read(HERE / "src" / "page.html")
    parts = {
        "/*JSYAML*/": HERE / "vendor" / "js-yaml.min.js",
        "/*CORE*/": HERE / "src" / "core.js",
        "/*UI*/": HERE / "src" / "ui.js",
    }
    for marker, path in parts.items():
        code = _read(path).replace("</script", "<\\/script")
        assert marker in page, marker
        page = page.replace(marker, code, 1)
    banner = "<!-- Built by builder/build.py from builder/src/ - edit those files, not this one. -->\n"
    return page.replace("<!doctype html>\n", "<!doctype html>\n" + banner, 1)


def main() -> None:
    (HERE / "index.html").write_text(render(), encoding="utf-8", newline="\n")
    print(f"wrote {HERE / 'index.html'}")


if __name__ == "__main__":
    main()
