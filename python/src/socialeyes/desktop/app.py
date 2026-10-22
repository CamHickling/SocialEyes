"""The SocialEyes desktop app: a window showing the experiment builder, with a
bridge to this package so the builder can open, save and check study folders.

Start it with ``socialeyes app``. Needs pywebview (``pip install -e "./python[desktop]"``);
on Windows it uses the Edge WebView2 runtime that comes with Windows 10/11.
"""
from __future__ import annotations

import functools
import json
import sys
import threading
import traceback
from pathlib import Path

from .. import __version__
from .studyfolder import (FolderError, check_folder, new_study_folder, protection_check, read_study, save_study,
                          sessions_of)

REPO = Path(__file__).resolve().parents[4]  # python/src/socialeyes/desktop/app.py -> repo root


def builder_page() -> Path:
    """The built experiment builder page (builder/index.html)."""
    base = Path(getattr(sys, "_MEIPASS", REPO))  # PyInstaller unpacks bundled files to _MEIPASS
    page = base / "builder" / "index.html"
    if not page.is_file():
        raise FileNotFoundError(f"{page} is missing; build it with: python builder/build.py")
    return page


def default_studies_dir() -> Path:
    """Where folder dialogs start: the workspace's studies folder (the repo's when developing)."""
    from .. import settings

    return settings.studies_dir()


def _reply(fn):
    """Bridge methods return {"ok": ...} or {"error": message} instead of raising into JavaScript."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return {"ok": fn(*args, **kwargs)}
        except (ValueError, OSError) as e:  # FolderError, bad study folders, files: plain messages
            return {"error": str(e)}
        except Exception as e:  # a bug: show it rather than leave the page waiting
            traceback.print_exc()
            return {"error": f"Unexpected problem ({type(e).__name__}): {e}"}
    return wrapper


class Api:
    """Methods the page calls as ``window.pywebview.api.<name>(...)``; each returns a promise."""

    def __init__(self):
        self._window = None  # set once the window exists; underscore keeps it out of the JS bridge
        self._storage: dict = {}  # folder -> cloud-sync service, looked up once per run
        self._outliner = None     # the AOI editor's click-to-outline, loaded on its first click
        self._outline_lock = threading.Lock()

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
    def guides(self) -> list:
        """The researcher's guides as pages to open: [{title, path}]."""
        from .guides import guide_pages

        return guide_pages()

    @_reply
    def open_folder(self, folder: str) -> dict:
        return {"study": read_study(folder), "check": check_folder(folder), "sessions": len(sessions_of(folder))}

    @_reply
    def save(self, folder: str, files: dict) -> dict:
        """Saves, unless the study has sessions and the edit would break them without a new
        version number: then nothing is written and {"needs_version": ...} says why."""
        protect = protection_check(folder, files.get("study.yaml", ""))
        if protect:
            return {"needs_version": protect}
        saved = save_study(folder, files)
        return {"saved": saved, "check": check_folder(folder), "sessions": len(sessions_of(folder))}

    @_reply
    def save_new(self, parent: str, study_id: str, files: dict) -> dict:
        folder = new_study_folder(parent, study_id)
        saved = save_study(folder, files)
        return {"saved": saved, "check": check_folder(folder)}

    @_reply
    def check(self, folder: str) -> dict:
        return check_folder(folder)

    # ---------------------------------------------------------- Studies and Content tabs

    @_reply
    def studies_list(self) -> dict:
        from .studies import list_studies

        return list_studies()

    @_reply
    def studies_copy_example(self, new_id: str) -> str:
        from .studies import copy_example

        return copy_example(new_id.strip())

    @_reply
    def content(self, folder: str) -> dict:
        from .images import sources
        from .studies import content_checklist

        out = content_checklist(folder)
        try:
            out["sources"] = sources(folder, create=False)   # keeps an existing sources.csv in step with the CSVs
        except OSError as e:                     # e.g. sources.csv open in Excel
            out["sources"] = {"error": str(e)}
        return out

    @_reply
    def sources_make(self, folder: str) -> dict:
        """Starts sources.csv: a row per image and video, for where each came from."""
        from .images import sources

        return sources(folder)

    @_reply
    def images_match(self, folder: str, source: str) -> dict:
        """The files in `source` matched to the study's image and video slots by name."""
        from .images import match

        return match(folder, source)

    @_reply
    def images_copy(self, folder: str, pairs: list, replace: bool = False) -> dict:
        from .images import copy_in

        return copy_in(folder, pairs, replace=bool(replace))

    @_reply
    def images_report(self, folder: str) -> dict:
        from .images import image_report

        return image_report(folder)

    @_reply
    def images_resize(self, folder: str) -> dict:
        from .images import resize_large

        return resize_large(folder)

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
    def phone_setup(self, serial: str | None = None) -> dict:
        """The phone setup guide: each step's state, read from the phone."""
        from ..phone.setup import guide

        return guide(serial or None)

    @_reply
    def phone_setup_do(self, action: str, serial: str | None = None) -> dict:
        """Runs one setup step on the phone, then reads the guide again."""
        from ..phone.setup import do, guide

        if action == "install":
            self._progress("Installing the app (about a minute)…")
        done = do(action, serial or None)
        return {"done": done, "guide": guide(serial or None)}

    @_reply
    def phone_devices(self) -> list:
        from ..phone.adb import Adb, AdbError

        try:
            return [{"serial": d.serial, "state": d.state, "model": d.model} for d in Adb().devices()]
        except AdbError:
            return []

    # ---------------------------------------------------------- Data tab

    @_reply
    def data_status(self, folder: str, serial: str | None = None) -> dict:
        """The study's folders, its register, and how many of its sessions are on the phone."""
        from .. import settings
        from ..phone.adb import Adb, AdbError
        from ..phone.unload import phone_sessions, study_id_of
        from ..session import register

        sid = study_id_of(folder)
        data = settings.data_dir(sid)
        second = settings.second_copy_dir(sid)
        _, rows = register.read(data / register.REGISTER)
        phone: dict = {}
        try:
            adb = Adb(serial or None)
            device = adb.choose()
            phone = {"name": device.model or device.serial, "sessions": len(phone_sessions(adb, sid))}
        except AdbError as e:
            phone = {"error": str(e)}
        analysis = settings.analysis_dir(sid)
        videos = [p.parent for p in data.glob("*/*/camera_frames.csv")]
        analysed = sum((analysis / v.parent.name / v.name / "face_summary.json").is_file() for v in videos)
        sessions = [p.parent for p in data.glob("*/*/session.json") if not p.parent.parent.name.startswith(".")]
        gaze = sum((analysis / s.parent.name / s.name / "fixations.csv").is_file() for s in sessions)
        from ..phone.unload import _recording_id, neon_recording

        recorded = [s for s in sessions if _recording_id(s)]
        copied = sum(neon_recording(s) is not None for s in recorded)
        heatmaps = analysis / "heatmaps" / "index.html"
        from ..session import retention

        storage = []
        for name, path in (("data", data), ("second copy", second)):
            if path is None:
                continue
            key = str(path)
            if key not in self._storage:  # asking Windows takes a moment: once per folder per run
                self._storage[key] = {"cloud": retention.cloud_folder(path)}
            storage.append({"folder": name, "path": key, **self._storage[key]})
        try:
            due = retention.due(folder)
        except (ValueError, OSError):
            due = None
        return {"study_id": sid, "data_dir": str(data), "second_copy_dir": str(second) if second else None,
                "register": rows, "phone": phone, "storage": storage, "retention": due,
                "clear_after_unload": bool(settings.study(sid).get("clear_after_unload")),
                "faces": {"videos": len(videos), "analysed": analysed},
                "gaze": {"sessions": gaze, "recorded": len(recorded), "copied": copied,
                         "heatmaps": str(heatmaps) if heatmaps.is_file() else None}}

    @_reply
    def data_set_folder(self, folder: str, which: str, path: str | None) -> bool:
        from .. import settings
        from ..phone.unload import study_id_of

        key = {"data": "data_dir", "second": "second_copy_dir"}[which]
        settings.set_study(study_id_of(folder), **{key: path or None})
        return True

    @_reply
    def data_unload(self, folder: str, serial: str | None = None) -> dict:
        from ..phone.unload import unload

        return unload(folder, serial=serial or None, progress=self._progress).to_json()

    @_reply
    def data_clear(self, folder: str, serial: str | None = None) -> dict:
        """Deletes from the phone the sessions safely copied to this computer (and the second copy)."""
        from ..phone.unload import clear_phone

        return clear_phone(folder, serial=serial or None, progress=self._progress).to_json()

    @_reply
    def data_withdraw(self, folder: str, participant_id: str, reason: str = "") -> dict:
        from ..session.withdraw import withdraw

        return withdraw(folder, participant_id, reason or "").to_json()

    @_reply
    def data_restore(self, folder: str, participant_id: str) -> dict:
        from ..session.withdraw import restore

        return restore(folder, participant_id).to_json()

    @_reply
    def data_delete_withdrawn(self, folder: str, participant_id: str, serial: str | None = None) -> dict:
        from ..session.withdraw import delete_permanently

        return delete_permanently(folder, participant_id, serial=serial or None).to_json()

    @_reply
    def data_retention_delete(self, folder: str, what: str) -> dict:
        from ..session.retention import delete_due

        return delete_due(folder, what)

    @_reply
    def data_export(self, folder: str, unblind: bool = False) -> dict:
        """Tables of every unloaded session (by session, by item, by condition), their codebook and
        the blinded exploration page (``unblind``: with the real condition names)."""
        from ..session.export import export

        return export(folder, progress=self._progress, unblind=bool(unblind)).to_json()

    @_reply
    def data_faces(self, folder: str, blur: bool = False) -> dict:
        """Analyses the face videos not analysed yet (and makes blurred copies, with ``blur``)."""
        from ..face.analyze import study_faces

        return study_faces(folder, blur=blur, progress=self._progress)

    @_reply
    def data_gaze(self, folder: str, redo: bool = False) -> dict:
        """Analyses the eye tracking of the sessions whose Neon recording is copied and not analysed yet."""
        from ..gaze.pipeline import study_gaze

        return study_gaze(folder, redo=bool(redo), progress=self._progress)

    @_reply
    def data_heatmaps(self, folder: str, by: str = "cell") -> dict:
        """Gaze heatmaps over the post images from every session's fixations.csv."""
        from ..gaze.heatmap import study_heatmaps

        r, skipped = study_heatmaps(folder, by=by or "cell", progress=self._progress)
        return {"page": r.page, "images": len(r.images), "skipped": [{"folder": f, "why": w} for f, w in skipped]}

    @_reply
    def preview(self, folder: str, participant_id: str | None = None) -> dict:
        """A participant's feed as the phone will show it, from the study as saved."""
        from .preview import feed_preview

        return feed_preview(folder, participant_id or None)

    # ---------------------------------------------------------- Design > Content

    @_reply
    def aois_draw(self, folder: str, overwrite: bool = False) -> dict:
        """Face and body AOIs drawn on the critical posts' images (socialeyes aois)."""
        from .. import settings
        from ..face.body_aois import study_aois
        from ..phone.unload import study_id_of

        review = settings.analysis_dir(study_id_of(folder)) / "aoi_review"
        r = study_aois(folder, overwrite=overwrite, review_dir=review, progress=self._progress)
        return {"written": [a for _, a in r.written], "kept": len(r.kept),
                "empty": [{"image": i, "why": w} for i, w in r.empty],
                "check": [{"image": x.image, "note": n} for x in r.images if x.aois for n in x.notes],
                "review": r.review}

    @_reply
    def aoi_images(self, folder: str) -> dict:
        """The images AOIs can be drawn on, and how click-to-outline will work."""
        from ..face.outline import Outliner
        from .aoi_editor import aoi_images

        o = self._outliner
        return {"images": aoi_images(folder),
                "outline": o.backend if o else ("sam" if Outliner.sam_ready() else "download")}

    @_reply
    def aoi_load(self, folder: str, image: str) -> dict:
        from .aoi_editor import load

        return load(folder, image)

    @_reply
    def aoi_save(self, folder: str, image: str, aois: list) -> dict:
        from .aoi_editor import save

        return save(folder, image, aois)

    @_reply
    def aoi_outline(self, folder: str, image: str, points: list) -> dict:
        """Outlines for clicks [[x, y, keep], ...] on the image: {backend, note, outlines}."""
        import cv2

        from ..face.outline import Outliner

        root = Path(folder)
        with self._outline_lock:
            if self._outliner is None:
                if not Outliner.sam_ready():
                    self._progress("Downloading the outlining model (45 MB, once)…")
                self._outliner = Outliner()
            o = self._outliner
            path = root / image
            stamp = (str(path), path.stat().st_mtime_ns)
            if o._key != stamp:
                self._progress("Reading the image…")
                bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
                if bgr is None:
                    raise ValueError(f"can't read {image}")
                o.set_image(bgr[:, :, ::-1].copy(), stamp)
            note = None
            if o.backend == "mediapipe" and o.why_not_sam:
                note = f"Using the simpler outliner: SAM couldn't start ({o.why_not_sam})"
            return {"backend": o.backend, "note": note, "outlines": o.outline([tuple(p) for p in points])}

    @_reply
    def open_path(self, path: str) -> bool:
        """Shows a folder in Explorer, or opens a file (e.g. a report page) with its usual program."""
        import os
        import subprocess

        if not Path(path).exists():
            raise FolderError(f"{path} doesn't exist yet")
        if os.name == "nt":
            os.startfile(path)  # noqa: S606 - a folder the app itself chose
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", path])
        return True

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
