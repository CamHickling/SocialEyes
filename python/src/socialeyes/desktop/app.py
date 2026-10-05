"""The SocialEyes desktop app: a window showing the experiment builder, with a
bridge to this package so the builder can open, save and check study folders.

Start it with ``socialeyes app``. Needs pywebview (``pip install -e "./python[desktop]"``);
on Windows it uses the Edge WebView2 runtime that comes with Windows 10/11.
"""
from __future__ import annotations

import functools
import json
import sys
import traceback
from pathlib import Path

from .. import __version__
from .studyfolder import FolderError, check_folder, new_study_folder, read_study, save_study

REPO = Path(__file__).resolve().parents[4]  # python/src/socialeyes/desktop/app.py -> repo root


def builder_page() -> Path:
    """The built experiment builder page (builder/index.html)."""
    base = Path(getattr(sys, "_MEIPASS", REPO))  # PyInstaller unpacks bundled files to _MEIPASS
    page = base / "builder" / "index.html"
    if not page.is_file():
        raise FileNotFoundError(f"{page} is missing; build it with: python builder/build.py")
    return page


def default_studies_dir() -> Path:
    """Where folder dialogs start: the repo's studies/ when developing, else Documents."""
    studies = REPO / "studies"
    return studies if studies.is_dir() else Path.home() / "Documents"


def _reply(fn):
    """Bridge methods return {"ok": ...} or {"error": message} instead of raising into JavaScript."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return {"ok": fn(*args, **kwargs)}
        except (FolderError, OSError) as e:
            return {"error": str(e)}
        except Exception as e:  # a bug: show it rather than leave the page waiting
            traceback.print_exc()
            return {"error": f"Unexpected problem ({type(e).__name__}): {e}"}
    return wrapper


class Api:
    """Methods the page calls as ``window.pywebview.api.<name>(...)``; each returns a promise."""

    def __init__(self):
        self._window = None  # set once the window exists; underscore keeps it out of the JS bridge

    @_reply
    def app_info(self) -> dict:
        return {"version": __version__, "studies_dir": str(default_studies_dir())}

    @_reply
    def pick_folder(self, start: str | None = None) -> str | None:
        """A folder chosen in the system dialog, or None if cancelled."""
        import webview

        start_dir = start if start and Path(start).is_dir() else str(default_studies_dir())
        chosen = self._window.create_file_dialog(webview.FileDialog.FOLDER, directory=start_dir)
        return chosen[0] if chosen else None

    @_reply
    def open_folder(self, folder: str) -> dict:
        return {"study": read_study(folder), "check": check_folder(folder)}

    @_reply
    def save(self, folder: str, files: dict) -> dict:
        saved = save_study(folder, files)
        return {"saved": saved, "check": check_folder(folder)}

    @_reply
    def save_new(self, parent: str, study_id: str, files: dict) -> dict:
        folder = new_study_folder(parent, study_id)
        saved = save_study(folder, files)
        return {"saved": saved, "check": check_folder(folder)}

    @_reply
    def check(self, folder: str) -> dict:
        return check_folder(folder)

    # ---------------------------------------------------------- Phone tab

    @_reply
    def phone_check(self, folder: str | None = None, serial: str | None = None) -> dict:
        from ..phone.loader import phone_check

        return phone_check(folder or None, serial=serial or None).to_json()

    @_reply
    def phone_load(self, folder: str, update_app: bool = False, anyway: bool = False,
                   serial: str | None = None) -> dict:
        from ..phone.loader import load

        return load(folder, serial=serial or None, update_app=update_app, anyway=anyway,
                    progress=self._progress).to_json()

    @_reply
    def phone_devices(self) -> list:
        from ..phone.adb import Adb, AdbError

        try:
            return [{"serial": d.serial, "state": d.state, "model": d.model} for d in Adb().devices()]
        except AdbError:
            return []

    def _progress(self, text: str) -> None:
        """Shows what a long phone operation is doing, while it runs."""
        if self._window is not None:
            try:
                self._window.evaluate_js(f"window.socialeyesProgress && window.socialeyesProgress({json.dumps(text)})")
            except Exception:  # the window may be closing; progress is only a nicety
                pass


def run(debug: bool = False) -> None:
    import webview

    api = Api()
    api._window = webview.create_window(
        "SocialEyes", url=builder_page().as_uri(), js_api=api,
        width=1360, height=900, min_size=(900, 600), text_select=True,
    )
    # private_mode=False keeps the builder's draft (localStorage) between runs
    webview.start(debug=debug, private_mode=False)
