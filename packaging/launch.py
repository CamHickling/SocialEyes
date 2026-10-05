"""Entry point of the packaged desktop app (SocialEyes.exe, built by packaging/build.py).

A windowed app has no console, so a crash at start-up would vanish without a word:
write it to %APPDATA%\\SocialEyes\\error.log and say so in a message box.
"""
import os
import sys
import traceback
from pathlib import Path


def selftest(report: Path) -> None:
    """SocialEyes.exe --selftest REPORT.json: checks the bundled parts work, without a window."""
    import json
    import subprocess
    import tempfile

    results: dict = {}

    def check(name, fn):
        try:
            results[name] = {"ok": True, "value": fn()}
        except Exception as e:  # report every failure, keep checking the rest
            results[name] = {"ok": False, "error": f"{type(e).__name__}: {e}"}

    from socialeyes import settings
    from socialeyes.desktop.app import builder_page
    from socialeyes.phone.adb import find_adb
    from socialeyes.phone.loader import find_apk
    from socialeyes.study.compiler import compile_study, package_hash

    check("builder_page", lambda: str(builder_page()))
    check("adb", lambda: subprocess.run([str(find_adb()), "version"], capture_output=True, text=True,
                                         check=True).stdout.splitlines()[0])
    check("apk", lambda: (lambda a: {"path": str(a.path), "version": a.version_name})(find_apk()))
    check("example", lambda: package_hash(compile_study(settings.example_study(),
                                                        Path(tempfile.mkdtemp()) / "pkg")[0]))
    check("workspace", lambda: str(settings.workspace()))
    # the Windows backend loads .NET through pythonnet: importing it is what fails when a part is missing
    check("webview", lambda: __import__("webview.platforms.winforms").__name__)
    report.write_text(json.dumps(results, indent=2), encoding="utf-8")


def main() -> None:
    if len(sys.argv) == 3 and sys.argv[1] == "--selftest":
        selftest(Path(sys.argv[2]))
        return
    try:
        from socialeyes.desktop.app import run

        run()
    except Exception:
        log = Path(os.environ.get("APPDATA", Path.home())) / "SocialEyes" / "error.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(traceback.format_exc(), encoding="utf-8")
        if sys.platform == "win32":
            import ctypes

            ctypes.windll.user32.MessageBoxW(
                None, f"SocialEyes couldn't start. The details are in:\n{log}\n\n"
                      "If the window never appeared, the Microsoft Edge WebView2 Runtime may be missing.",
                "SocialEyes", 0x10)
        raise


if __name__ == "__main__":
    main()
