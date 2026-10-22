"""Model files in models/. The face landmarker is committed; the larger MediaPipe models are
downloaded the first time they are needed (the installer carries them) and checked by SHA-256.

ON_DEMAND models (MobileSAM, for outlining AOIs with a click) are not in the installer: they are
downloaded on first use, into models/ when running from the repository and into the user's
local app data folder in the installed app (its own folder may not be writable)."""
from __future__ import annotations

import contextlib
import hashlib
import os
import sys
import urllib.request
from pathlib import Path

DIR = Path(__file__).parent / "models"
_BASE = "https://storage.googleapis.com/mediapipe-models/"
MODELS = {
    "face_landmarker.task": (
        _BASE + "face_landmarker/face_landmarker/float16/1/face_landmarker.task",
        "64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff"),
    "pose_landmarker_full.task": (
        _BASE + "pose_landmarker/pose_landmarker_full/float16/1/pose_landmarker_full.task",
        "5134a3aad27a58b93da0088d431f366da362b44e3ccfbe3462b3827a839011b1"),
    "selfie_multiclass_256x256.tflite": (
        _BASE + "image_segmenter/selfie_multiclass_256x256/float32/latest/selfie_multiclass_256x256.tflite",
        "c6748b1253a99067ef71f7e26ca71096cd449baefa8f101900ea23016507e0e0"),
    # the AOI editor's click-to-outline when SAM can't be downloaded
    "magic_touch.tflite": (
        _BASE + "interactive_segmenter/magic_touch/float32/latest/magic_touch.tflite",
        "e24338a717c1b7ad8d159666677ef400babb7f33b8ad60c4d96db4ecf694cd25"),
}
# MobileSAM (Apache-2.0) as ONNX (MIT): https://huggingface.co/Acly/MobileSAM, 45 MB together
_SAM = "https://huggingface.co/Acly/MobileSAM/resolve/main/"
ON_DEMAND = {
    "mobile_sam_image_encoder.onnx": (
        _SAM + "mobile_sam_image_encoder.onnx",
        "580f5fb648ea1062c0aabc26217aed56921985f03f0cbbd852bba81d760cc749"),
    "sam_mask_decoder_multi.onnx": (
        _SAM + "sam_mask_decoder_multi.onnx",
        "8976b90a87ba50a6a72217a5ff994f7d25ce16f2229fcc1ed259e1294c622ffe"),
}


def _download_dir(name: str) -> Path:
    if name in MODELS or not hasattr(sys, "_MEIPASS"):
        return DIR
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".cache")
    return Path(base) / "SocialEyes" / "models"


def available(name: str) -> bool:
    """Whether the model is already here (no download needed)."""
    return (DIR / name).is_file() or (_download_dir(name) / name).is_file()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def ensure(name: str) -> Path:
    """The model's path, downloading it first if it isn't there (about 6-30 MB, once)."""
    url, sha = MODELS[name] if name in MODELS else ON_DEMAND[name]
    if (DIR / name).is_file():
        return DIR / name
    path = _download_dir(name) / name
    if path.is_file():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    try:
        with urllib.request.urlopen(url, timeout=120) as r, tmp.open("wb") as out:
            while block := r.read(1 << 20):
                out.write(block)
    except OSError as e:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"couldn't download the {name} model ({e}); check the internet connection") from e
    if _sha256(tmp) != sha:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"the downloaded {name} model doesn't match its checksum; try again")
    tmp.replace(path)
    return path


@contextlib.contextmanager
def quiet_native_stderr():
    """Hides what MediaPipe's C++ side prints while its models load (start-up notices that
    ignore Python's logging settings). Python's own errors still show: they're raised, not printed."""
    try:
        fd = sys.stderr.fileno()
    except (AttributeError, OSError, ValueError):  # no real stderr (the packaged app)
        yield
        return
    sys.stderr.flush()
    saved = os.dup(fd)
    try:
        with open(os.devnull, "w") as null:
            os.dup2(null.fileno(), fd)
            yield
    finally:
        os.dup2(saved, fd)
        os.close(saved)
