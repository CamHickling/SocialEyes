"""Loading a study onto the phone: readiness checks, app install/update, verified copy.

``socialeyes phone-check`` and ``socialeyes load`` and the desktop app's Phone tab
all use these functions. Rules (CAM-156):

- *block*: no usable phone, study has errors, app missing with nothing to install,
  not enough storage, or replacing a study whose sessions are still on the phone.
- *warn* (needs "load anyway"): battery under 50%, Do Not Disturb off, display
  size or font size not the default.
- the app is installed when missing; a newer app is only installed when asked
  (``update_app``). The phone's app is never uninstalled (that deletes its data).
"""
from __future__ import annotations

import json
import re
import shutil
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Optional

from ..study.compiler import CHECKSUM_FILE, StudyError, compile_study, package_hash
from .adb import APP_FILES, PACKAGE, REPO, Adb, AdbError

MIN_BATTERY = 50
STORAGE_MARGIN = 500 * 2**20          # room for session data beyond the study itself
CAMERA_MARGIN = 2 * 2**30             # front camera video
ZEN_MODES = {"0": "off", "1": "priority only", "2": "total silence", "3": "alarms only"}


# ---------------------------------------------------------------- the app file to install


@dataclass(frozen=True)
class ApkInfo:
    path: Path
    version_code: int
    version_name: str


def find_apk() -> Optional[ApkInfo]:
    """The SocialEyes app file this computer can install: bundled with the desktop app,
    or the newest local build (release before debug) when developing."""
    if hasattr(sys, "_MEIPASS"):
        apk = Path(sys._MEIPASS) / "app" / "socialeyes.apk"
        meta = apk.with_suffix(".json")
        if apk.is_file() and meta.is_file():
            m = json.loads(meta.read_text(encoding="utf-8"))
            return ApkInfo(apk, int(m["version_code"]), m["version_name"])
        return None
    gradle = REPO / "android" / "app" / "build.gradle.kts"
    out = REPO / "android" / "app" / "build" / "outputs" / "apk"
    for apk in (out / "release" / "app-release.apk", out / "debug" / "app-debug.apk"):
        if apk.is_file() and gradle.is_file():
            code, name = _gradle_version(gradle.read_text(encoding="utf-8"))
            return ApkInfo(apk, code, name)
    return None


def _gradle_version(text: str) -> tuple[int, str]:
    code = re.search(r"versionCode\s*=\s*(\d+)", text)
    name = re.search(r'versionName\s*=\s*"([^"]+)"', text)
    return int(code.group(1)) if code else 0, name.group(1) if name else "?"


# ---------------------------------------------------------------- what the phone says


@dataclass
class PhoneState:
    serial: str
    model: str = ""
    android: str = ""
    app_installed: bool = False
    app_version_code: Optional[int] = None
    app_version_name: Optional[str] = None
    camera_granted: Optional[bool] = None
    app_running: bool = False
    battery: Optional[int] = None
    charging: bool = False
    free_bytes: Optional[int] = None
    dnd: Optional[str] = None             # off, priority only, total silence, alarms only
    display_changed: bool = False         # display size changed from the phone's default
    font_scale: Optional[float] = None
    studies: dict = field(default_factory=dict)    # study id -> package hash on the phone (None: unknown)
    sessions: dict = field(default_factory=dict)   # study id -> sessions still on the phone


def parse_package(dumpsys: str) -> tuple[bool, Optional[int], Optional[str], Optional[bool]]:
    """`dumpsys package <pkg>` -> installed, versionCode, versionName, camera permission granted."""
    code = re.search(r"versionCode=(\d+)", dumpsys)
    if not code:
        return False, None, None, None
    name = re.search(r"versionName=(\S+)", dumpsys)
    cam = re.search(r"android\.permission\.CAMERA: granted=(true|false)", dumpsys)
    return True, int(code.group(1)), name.group(1) if name else None, (cam.group(1) == "true") if cam else False


def parse_battery(dumpsys: str) -> tuple[Optional[int], bool]:
    level = re.search(r"^\s*level: (\d+)", dumpsys, re.M)
    charging = bool(re.search(r"(AC|USB|Wireless) powered: true", dumpsys))
    return (int(level.group(1)) if level else None), charging


def parse_df(df: str) -> Optional[int]:
    """`df -k <path>` -> available bytes."""
    rows = [line.split() for line in df.splitlines() if line.strip() and not line.startswith("Filesystem")]
    try:
        return int(rows[-1][3]) * 1024
    except (IndexError, ValueError):
        return None


def parse_study_hashes(sha256sum_out: str, listing: str) -> dict:
    """`sha256sum */files.sha256` and `ls` of the studies folder -> {study id: package hash or None}."""
    studies = {name.strip(): None for name in listing.split() if name.strip()}
    for line in sha256sum_out.splitlines():
        m = re.match(r"([0-9a-f]{64})\s+(.+?)/" + re.escape(CHECKSUM_FILE) + r"$", line.strip())
        if m:
            studies[m.group(2)] = m.group(1)
    return studies


def parse_sessions(find_out: str) -> dict:
    """`find data -mindepth 3 -maxdepth 3 -type d` -> {study id: number of session folders}."""
    counts: dict = {}
    for line in find_out.splitlines():
        parts = line.strip().rstrip("/").split("/")
        if len(parts) >= 3 and parts[-3] and "No such file" not in line:
            counts[parts[-3]] = counts.get(parts[-3], 0) + 1
    return counts


def read_phone(adb: Adb) -> PhoneState:
    device = adb.choose()
    s = PhoneState(serial=device.serial, model=device.model)
    s.android = adb.shell("getprop ro.build.version.release").strip()
    s.app_installed, s.app_version_code, s.app_version_name, s.camera_granted = parse_package(
        adb.shell(f"dumpsys package {PACKAGE}"))
    s.app_running = bool(adb.shell(f"pidof {PACKAGE}").strip())
    s.battery, s.charging = parse_battery(adb.shell("dumpsys battery"))
    s.free_bytes = parse_df(adb.shell("df -k /sdcard"))
    s.dnd = ZEN_MODES.get(adb.shell("settings get global zen_mode").strip())
    s.display_changed = "Override" in adb.shell("wm size") + adb.shell("wm density")
    try:
        s.font_scale = float(adb.shell("settings get system font_scale").strip())
    except ValueError:
        s.font_scale = None  # "null": never changed, which means the default
    studies = f"{APP_FILES}/studies"
    s.studies = parse_study_hashes(adb.shell(f"cd {studies} 2>/dev/null && sha256sum */{CHECKSUM_FILE} 2>/dev/null"),
                                   adb.shell(f"ls -1 {studies} 2>/dev/null"))
    s.sessions = parse_sessions(adb.shell(f"find {APP_FILES}/data -mindepth 3 -maxdepth 3 -type d 2>/dev/null"))
    return s


# ---------------------------------------------------------------- the study


@dataclass
class StudyInfo:
    id: str
    version: int
    build: Path                 # compiled package (a temporary folder)
    package_sha256: str
    size_bytes: int
    needs_camera: bool


def build_study(study_dir: Path | str) -> StudyInfo:
    """Compile the study into a temporary folder. Raises StudyError if it has errors."""
    tmp = Path(tempfile.mkdtemp(prefix="socialeyes-load-"))
    try:
        out, _ = compile_study(study_dir, tmp / "package")
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    study = json.loads((out / "study.json").read_text(encoding="utf-8"))["study"]
    return StudyInfo(
        id=study["id"], version=study["version"], build=out, package_sha256=package_hash(out),
        size_bytes=sum(p.stat().st_size for p in out.rglob("*") if p.is_file()),
        needs_camera=bool(study.get("logging", {}).get("front_camera", {}).get("enabled")),
    )


def discard(study: Optional[StudyInfo]) -> None:
    if study is not None:
        shutil.rmtree(study.build.parent, ignore_errors=True)


# ---------------------------------------------------------------- readiness


@dataclass
class Check:
    level: str   # block, warn, info (something Load will do), ok
    text: str


def _gb(n: int) -> str:
    return f"{n / 2**30:.1f} GB"


def readiness(phone: PhoneState, study: Optional[StudyInfo] = None, apk: Optional[ApkInfo] = None,
              study_errors: Optional[list[str]] = None) -> list[Check]:
    checks: list[Check] = []
    add = lambda level, text: checks.append(Check(level, text))  # noqa: E731

    # the app
    if not phone.app_installed:
        if apk:
            add("info", f"The SocialEyes app isn't on the phone; loading installs it (version {apk.version_name}).")
        else:
            add("block", "The SocialEyes app isn't on the phone, and there is no app file on this computer to "
                         "install. Build it first (android: gradlew assembleDebug).")
    elif apk and phone.app_version_code is not None and apk.version_code > phone.app_version_code:
        add("info", f"App {phone.app_version_name} is installed; {apk.version_name} is available. "
                    "Update app installs it and keeps the phone's data.")
    else:
        add("ok", f"SocialEyes app {phone.app_version_name} is installed.")

    # the study
    if study_errors:
        add("block", f"The study has {len(study_errors)} problem(s) to fix first (Design tab or "
                     f"socialeyes validate): {study_errors[0]}")
    if study is not None:
        on_phone = phone.studies.get(study.id, False)
        waiting = phone.sessions.get(study.id, 0)
        if on_phone is False:
            add("info", f"Loads study {study.id} (version {study.version}).")
        elif on_phone == study.package_sha256:
            add("ok", f"This exact version of {study.id} is already on the phone.")
        elif waiting:
            add("block", f"The phone holds {waiting} session(s) of {study.id} that haven't been copied off. "
                         "Unload the data before loading a changed study.")
        else:
            add("info", f"Replaces the different version of {study.id} that is on the phone.")
        if study.needs_camera and phone.app_installed and not phone.camera_granted:
            add("info", "The study records the front camera; loading allows the app to use the camera.")

        need = study.size_bytes + STORAGE_MARGIN + (CAMERA_MARGIN if study.needs_camera else 0)
        if phone.free_bytes is not None and phone.free_bytes < need:
            add("block", f"Not enough storage: {_gb(phone.free_bytes)} free, {_gb(need)} needed "
                         "(the study plus room for session data).")
        elif phone.free_bytes is not None:
            add("ok", f"{_gb(phone.free_bytes)} free on the phone.")

    # the session conditions
    if phone.battery is not None and phone.battery < MIN_BATTERY:
        add("warn", f"Battery at {phone.battery}%{' (charging)' if phone.charging else ''}; charge it to at "
                    f"least {MIN_BATTERY}% before a session.")
    elif phone.battery is not None:
        add("ok", f"Battery at {phone.battery}%.")
    if phone.dnd == "off":
        add("warn", "Do Not Disturb is off: notifications could interrupt sessions.")
    elif phone.dnd:
        add("ok", f"Do Not Disturb is on ({phone.dnd}).")
    if phone.display_changed:
        add("warn", "The phone's display size has been changed from its default; layouts and logged "
                    "sizes will differ from other phones.")
    if phone.font_scale is not None and abs(phone.font_scale - 1.0) > 1e-6:
        add("warn", f"The phone's font size is {phone.font_scale:g}x, not the default; text in the feed "
                    "will look different.")
    return checks


def blocked(checks: list[Check]) -> bool:
    return any(c.level == "block" for c in checks)


def warned(checks: list[Check]) -> bool:
    return any(c.level == "warn" for c in checks)


# ---------------------------------------------------------------- phone-check and load


@dataclass
class Result:
    phone: Optional[PhoneState] = None
    checks: list = field(default_factory=list)
    study_id: Optional[str] = None
    loaded: bool = False
    needs_confirmation: bool = False   # only warnings stand in the way: "load anyway"
    update_available: bool = False
    steps: list = field(default_factory=list)   # what loading did, in order
    error: Optional[str] = None

    def to_json(self) -> dict:
        d = asdict(self)
        d["checks"] = [asdict(c) for c in self.checks]
        return d


def _assess(adb: Adb, study_dir: Optional[Path | str]) -> tuple[Result, Optional[StudyInfo], Optional[ApkInfo]]:
    r = Result()
    apk = find_apk()
    r.phone = read_phone(adb)  # first: no phone means no point compiling
    study, errors = None, None
    if study_dir is not None:
        try:
            study = build_study(study_dir)
            r.study_id = study.id
        except StudyError as e:
            errors = e.errors
    r.checks = readiness(r.phone, study, apk, errors)
    r.update_available = bool(apk and r.phone.app_installed and r.phone.app_version_code is not None
                              and apk.version_code > r.phone.app_version_code)
    r.needs_confirmation = warned(r.checks) and not blocked(r.checks)
    return r, study, apk


def phone_check(study_dir: Optional[Path | str] = None, serial: Optional[str] = None) -> Result:
    """The phone's readiness (for loading ``study_dir``, if given). Changes nothing."""
    study = None
    try:
        r, study, _ = _assess(Adb(serial), study_dir)
    except AdbError as e:  # no usable phone: say why
        return Result(error=str(e))
    finally:
        discard(study)
    return r


def load(study_dir: Path | str, serial: Optional[str] = None, update_app: bool = False, anyway: bool = False,
         progress: Callable[[str], None] = lambda s: None) -> Result:
    """Check, then install/update the app if needed, then copy the study and verify every file."""
    study = None
    r = Result()
    try:
        adb = Adb(serial)
        progress("Checking the study and the phone…")
        r, study, apk = _assess(adb, study_dir)
        if blocked(r.checks) or study is None:
            return r
        if r.needs_confirmation and not anyway:
            return r

        def step(text: str) -> None:
            r.steps.append(text)
            progress(text)

        if not r.phone.app_installed or (update_app and r.update_available):
            step(f"Installing the SocialEyes app {apk.version_name}…")
            _install(adb, apk)
            r.phone.app_installed = True
        if study.needs_camera:
            granted = parse_package(adb.shell(f"dumpsys package {PACKAGE}"))[3]
            if not granted:
                step("Allowing the app to use the camera…")
                adb.shell(f"pm grant {PACKAGE} android.permission.CAMERA", check=True)
        if r.phone.studies.get(study.id) == study.package_sha256:
            step(f"{study.id} is already on the phone; nothing to copy.")
        else:
            step(f"Copying {study.id} to the phone…")
            _push_verified(adb, study, progress)
            step(f"Copied and checked {_count(study)} files.")
            if r.phone.app_running:
                step("SocialEyes is open on the phone: close it and open it again to see the study.")
        r.loaded = True
        return r
    except AdbError as e:
        r.error = str(e)
        r.loaded = False
        return r
    finally:
        discard(study)


def _count(study: StudyInfo) -> int:
    return len((study.build / CHECKSUM_FILE).read_text(encoding="utf-8").splitlines()) + 1


def _install(adb: Adb, apk: ApkInfo) -> None:
    out = adb.run("install", "-r", str(apk.path), timeout=300, check=False)
    if "Success" in out:
        return
    if "INSTALL_FAILED_UPDATE_INCOMPATIBLE" in out:
        raise AdbError("The app on the phone was signed with a different key, so it can't be updated in place. "
                       "Uninstalling it would delete its data: unload all sessions first, then uninstall "
                       "SocialEyes on the phone and load again.")
    if "INSTALL_FAILED_VERSION_DOWNGRADE" in out:
        raise AdbError("The phone has a newer SocialEyes app than this computer; leave it as it is.")
    raise AdbError("Installing the app failed: " + (out.strip().splitlines() or ["no output"])[-1])


def _push_verified(adb: Adb, study: StudyInfo, progress: Callable[[str], None]) -> None:
    """Push to a staging folder, check every file's SHA-256 on the phone, then swap it in."""
    staging = f"{APP_FILES}/incoming/{study.id}"
    final = f"{APP_FILES}/studies/{study.id}"
    adb.shell(f"rm -rf {staging} && mkdir -p {APP_FILES}/incoming {APP_FILES}/studies", check=True)
    adb.run("push", str(study.build), staging, timeout=600)
    progress("Checking every file arrived intact…")
    expected = expected_hashes(study.build)
    got = parse_sha256sum(adb.shell(f"cd {staging} && find . -type f -exec sha256sum {{}} +", timeout=300))
    bad = sorted(name for name, h in expected.items() if got.get(name) != h)
    if bad:
        adb.shell(f"rm -rf {staging}")
        raise AdbError(f"{len(bad)} file(s) didn't arrive intact (e.g. {bad[0]}); nothing was replaced. "
                       "Check the cable and try again.")
    adb.shell(f"rm -rf {final} && mv {staging} {final} && rmdir {APP_FILES}/incoming 2>/dev/null; true", check=True)


def expected_hashes(build: Path) -> dict:
    """Every file of a package and its SHA-256, from its files.sha256 (plus that file itself)."""
    sums = parse_sha256sum((build / CHECKSUM_FILE).read_text(encoding="utf-8"))
    sums[CHECKSUM_FILE] = package_hash(build)
    return sums


def parse_sha256sum(text: str) -> dict:
    out = {}
    for line in text.splitlines():
        m = re.match(r"([0-9a-f]{64})\s+\*?(?:\./)?(.+)$", line.strip())
        if m:
            out[m.group(2)] = m.group(1)
    return out
