"""The researcher's guides, as pages the desktop app opens in the browser (the installer carries the
Markdown files; each is turned into a page when it's first opened)."""
from __future__ import annotations

import html
import re
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]

# (file, title): the guides a researcher needs, in the order the Studies page lists them
GUIDES = [
    ("FIRST_STUDY.md", "Your first study"),
    ("RUNNING_A_SESSION.md", "Running a session (printable checklist)"),
    ("STUDY_DESIGN.md", "Study files: what every CSV column means"),
]

STYLE = """body{margin:0;background:#fafafa;color:#18181b;font:16px/1.6 system-ui,sans-serif}
main{max-width:46rem;margin:0 auto;padding:32px 20px 64px}h1{font-size:1.9rem;line-height:1.2}h2{margin-top:2em}
code{background:#f0f0f3;padding:1px 5px;border-radius:4px;font-size:.92em}pre code{display:block;padding:12px;overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:.95rem}th,td{border:1px solid #d4d4d8;padding:6px 8px;text-align:left;vertical-align:top}
a{color:#1d4ed8}li.todo{list-style:none;margin-left:-1.1em}@media print{body{background:#fff}main{padding:0}}
@media (prefers-color-scheme:dark){body{background:#18181b;color:#e4e4e7}code{background:#27272a}th,td{border-color:#3f3f46}a{color:#93c5fd}}"""


def source_dir() -> Path:
    """Where the Markdown guides are: bundled with the installer, or the repo's docs when developing."""
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "guides"
    return REPO / "docs"


def _source(name: str) -> Path:
    base = source_dir()
    for p in (base / name, base / "guides" / name):
        if p.is_file():
            return p
    raise FileNotFoundError(f"guide {name} isn't installed")


def render(md: str, title: str) -> str:
    from markdown_it import MarkdownIt

    body = MarkdownIt("commonmark").enable("table").render(md)
    body = re.sub(r'href="([A-Z_]+)\.md"', r'href="\1.html"', body)          # links between the guides
    body = body.replace("<li>[ ]", '<li class="todo">&#9744;')                # checklist boxes, no bullet
    return (f"<!doctype html><html lang=en><meta charset=utf-8><meta name=viewport content=\"width=device-width,"
            f"initial-scale=1\"><title>{html.escape(title)}</title><style>{STYLE}</style><main>{body}</main></html>")


def guide_pages(out: Path | None = None) -> list[dict]:
    """Every guide as a page (written to `out`, default a folder in the temp directory): [{title, path}]."""
    out = Path(out) if out else Path(tempfile.gettempdir()) / "socialeyes-guides"
    out.mkdir(parents=True, exist_ok=True)
    pages = []
    for name, title in GUIDES:
        try:
            src = _source(name)
        except FileNotFoundError:
            continue
        page = out / (Path(name).stem + ".html")
        page.write_text(render(src.read_text(encoding="utf-8"), title), encoding="utf-8")
        pages.append({"title": title, "path": str(page)})
    return pages
