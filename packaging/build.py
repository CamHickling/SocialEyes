"""Build the Windows installer for the SocialEyes desktop app.

    . .\\scripts\\env.ps1
    python packaging/build.py          # release: needs the signing key (android/keystore.properties)
    python packaging/build.py --dev    # test build with this computer's debug-signed phone app

Steps: the builder page -> the phone app (APK) -> a PyInstaller folder holding Python,
the socialeyes package, the builder, adb, the APK and the example study -> an Inno
Setup installer. Everything is written to packaging/out/ (git-ignored):

    packaging/out/SocialEyes-Setup-<version>.exe        (or ...-dev.exe for --dev)

A --dev installer must not be given to other labs: its phone app is signed with this
computer's debug key, so phones that have it can't take the release app later without
uninstalling it (which deletes its data).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "packaging" / "out"
TOOL = ROOT / ".toolchain"


def step(text: str) -> None:
    print(f"\n== {text}", flush=True)


def run(cmd: list, cwd: Path = ROOT, env: dict | None = None) -> None:
    print("  $ " + " ".join(str(c) for c in cmd), flush=True)
    subprocess.run([str(c) for c in cmd], cwd=cwd, env=env, check=True)


def toolchain_env() -> dict:
    env = dict(os.environ)
    jdk, sdk = TOOL / "env" / "Library", TOOL / "android-sdk"
    if (jdk / "bin" / "java.exe").is_file():
        env["JAVA_HOME"] = str(jdk)
    if sdk.is_dir():
        env["ANDROID_HOME"] = env["ANDROID_SDK_ROOT"] = str(sdk)
    return env


def app_version() -> tuple[int, str]:
    text = (ROOT / "android" / "app" / "build.gradle.kts").read_text(encoding="utf-8")
    code = int(re.search(r"versionCode\s*=\s*(\d+)", text).group(1))
    name = re.search(r'versionName\s*=\s*"([^"]+)"', text).group(1)
    return code, name


def build_apk(dev: bool) -> Path:
    keystore = ROOT / "android" / "keystore.properties"
    if not dev and not keystore.is_file():
        sys.exit("No signing key: android/keystore.properties is missing. Create the release key first "
                 "(README, 'Release signing key'), or make a test build with --dev.")
    task, apk = (("assembleDebug", "debug/app-debug.apk") if dev else ("assembleRelease", "release/app-release.apk"))
    run([ROOT / "android" / "gradlew.bat", task, "--console=plain", "-q"], cwd=ROOT / "android", env=toolchain_env())
    path = ROOT / "android" / "app" / "build" / "outputs" / "apk" / apk
    if not path.is_file():
        sys.exit(f"The phone app wasn't built ({path} is missing).")
    return path


def make_icon(dest: Path) -> Path:
    from PIL import Image

    mark = Image.open(ROOT / "docs" / "assets" / "socialeyes-mark.png").convert("RGBA")
    side = max(mark.size)
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    square.paste(mark, ((side - mark.width) // 2, (side - mark.height) // 2))
    square.save(dest, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    return dest


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dev", action="store_true", help="test build with the debug-signed phone app (not for distribution)")
    args = ap.parse_args()

    sys.path.insert(0, str(ROOT / "python" / "src"))
    from socialeyes import __version__

    shutil.rmtree(OUT, ignore_errors=True)
    stage = OUT / "stage"
    stage.mkdir(parents=True)

    step("Building the experiment builder page")
    run([sys.executable, ROOT / "builder" / "build.py"])

    step("Building the phone app" + (" (debug-signed: --dev)" if args.dev else " (release)"))
    apk = build_apk(args.dev)
    (stage / "app").mkdir()
    shutil.copy2(apk, stage / "app" / "socialeyes.apk")
    code, name = app_version()
    (stage / "app" / "socialeyes.json").write_text(
        json.dumps({"version_code": code, "version_name": name, "debug_signed": args.dev}) + "\n", encoding="utf-8")

    step("Staging the example study and adb")
    shutil.copytree(ROOT / "studies" / "example", stage / "example",
                    ignore=shutil.ignore_patterns("__pycache__", "make_placeholders.py"))
    platform_tools = TOOL / "android-sdk" / "platform-tools"
    (stage / "adb").mkdir()
    for f in ("adb.exe", "AdbWinApi.dll", "AdbWinUsbApi.dll", "NOTICE.txt"):
        shutil.copy2(platform_tools / f, stage / "adb" / f)
    icon = make_icon(stage / "socialeyes.ico")

    step("Bundling Python and the socialeyes package (PyInstaller)")
    sep = ";"
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed", "--name", "SocialEyes",
         "--icon", icon, "--distpath", OUT / "pyinstaller", "--workpath", OUT / "work", "--specpath", OUT,
         "--paths", ROOT / "python" / "src",
         "--add-data", f"{ROOT / 'builder' / 'index.html'}{sep}builder",
         "--add-data", f"{stage / 'example'}{sep}example",
         "--add-data", f"{stage / 'app'}{sep}app",
         "--add-binary", f"{stage / 'adb'}{sep}adb",
         "--collect-submodules", "socialeyes",
         *[a for m in ("matplotlib", "scipy", "tkinter", "IPython", "pytest") for a in ("--exclude-module", m)],
         ROOT / "packaging" / "launch.py"],
        env={**os.environ, "PYTHONNOUSERSITE": "1"})  # only the toolchain's packages, never the user's own
    folder = OUT / "pyinstaller" / "SocialEyes"

    step("Making the installer (Inno Setup)")
    iscc = TOOL / "innosetup" / "ISCC.exe"
    if not iscc.is_file():
        sys.exit("Inno Setup is missing: run scripts/setup-toolchain.ps1 (it installs a portable copy).")
    suffix = "-dev" if args.dev else ""
    run([iscc, "/Q", f"/DAppVersion={__version__}", f"/DSourceDir={folder}", f"/DOutDir={OUT}",
         f"/DIcon={icon}", f"/DSuffix={suffix}", ROOT / "packaging" / "socialeyes.iss"])
    installer = OUT / f"SocialEyes-Setup-{__version__}{suffix}.exe"
    size = installer.stat().st_size / 2**20
    print(f"\nWrote {installer} ({size:.0f} MB)" + ("\nTEST BUILD: not for distribution (debug-signed phone app)." if args.dev else ""))


if __name__ == "__main__":
    main()
