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

    # face analysis, automatic AOIs and heatmaps: MediaPipe, its bundled models, matplotlib
    def face_model():
        import numpy as np
        from socialeyes.face.analyze import _landmarker

        mp, lm = _landmarker()
        try:
            img = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.zeros((480, 640, 3), np.uint8))
            return f"{len(lm.detect_for_video(img, 1).face_landmarks)} faces in a blank frame"
        finally:
            lm.close()

    def body_models():
        import numpy as np
        from socialeyes.face.body_aois import Detector, image_aois

        with Detector() as det:
            return image_aois(np.full((400, 300, 3), 200, np.uint8), det).notes

    def colormap():
        from matplotlib import colormaps

        return [round(float(v), 3) for v in colormaps["inferno"](0.5)]

    # the AOI editor's click-to-outline: MediaPipe's (bundled) and ONNX Runtime, which runs SAM once downloaded
    def outliner():
        import numpy as np
        import onnxruntime
        from socialeyes.face.outline import Outliner

        o = Outliner(prefer="mediapipe")
        try:
            img = np.full((120, 100, 3), 220, np.uint8)
            img[40:80, 30:70] = 40
            o.set_image(img)
            return {"onnxruntime": onnxruntime.__version__, "outlines": len(o.outline([(50, 60, True)])),
                    "sam_downloaded": Outliner.sam_ready()}
        finally:
            o.close()

    check("face_model", face_model)
    check("outliner", outliner)
    check("body_models", body_models)
    check("heatmap_colours", colormap)
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
