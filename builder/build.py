"""Stitch the experiment builder into one offline file: builder/index.html.

Edit the files in builder/src/, then run:  python builder/build.py
"""
import re
from pathlib import Path
from urllib.parse import quote

HERE = Path(__file__).parent
ASSETS = HERE.parent / "docs" / "assets"


def _read(path: Path) -> str:
    # git may check files out with Windows line endings; the output is always \n
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def _svg_uri(path: Path) -> str:
    return "data:image/svg+xml," + quote(_read(path).strip(), safe=":/=',.-")


def _logo() -> str:
    """The SocialEyes logo, inline; the word "Social" takes the theme's text colour (.logo-ink)."""
    svg = _read(ASSETS / "socialeyes-logo-light.svg").strip()
    svg = re.sub(r'^<svg ([^>]*?)width="\d+" height="\d+" ', r'<svg \1class="logo" role="img" aria-label="SocialEyes" ', svg, count=1)
    assert svg.count('<path fill="#21005D" d=') == 1, "logo: the dark word isn't where build.py expects it"
    return svg.replace('<path fill="#21005D" d=', '<path class="logo-ink" d=')


def render() -> str:
    """The finished page."""
    page = _read(HERE / "src" / "page.html")
    for marker, value in {"<!--LOGO-->": _logo(), "/*FAVICON*/": _svg_uri(ASSETS / "favicon.svg"),
                          "/*MARK*/": _svg_uri(ASSETS / "socialeyes-mark.svg")}.items():
        assert marker in page, marker
        page = page.replace(marker, value, 1)
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
