"""Click-to-outline for the AOI editor: click on a thing in a post image and get its outline.

Two ways, both on this computer (nothing is uploaded):

- MobileSAM (Segment Anything, the small version) through ONNX Runtime. Its two model files
  (45 MB) are downloaded the first time; the image is encoded once (about a second), then each
  click takes a few hundredths of a second. It gives three outlines per click, from a part to the
  whole thing (a sleeve, the shirt, the person), and takes more clicks to refine: clicks on the
  thing add to it, clicks marked "not this" take away.
- MediaPipe's interactive segmenter (magic_touch, in the installer) when SAM can't be downloaded
  or ONNX Runtime is missing: one outline per click, for the thing under the click.

Outlines are polygons in image pixels (``mask_polygon``), ready to keep as AOIs.
"""
from __future__ import annotations

from typing import Optional

import numpy as np

from .body_aois import mask_polygon
from .model_files import available, ensure, quiet_native_stderr

SAM_ENCODER = "mobile_sam_image_encoder.onnx"
SAM_DECODER = "sam_mask_decoder_multi.onnx"
SAM_SIDE = 1024      # the encoder's input: the image scaled to this on its longest side


class Outliner:
    """Outlines for clicks on one image at a time; the image's encoding is kept between clicks."""

    def __init__(self, prefer: str = "sam"):
        self.backend: Optional[str] = None
        self.why_not_sam: Optional[str] = None
        self._key = None
        self._rgb: Optional[np.ndarray] = None
        self._emb = None
        self._sam = None
        self._mp = None
        if prefer == "sam":
            try:
                self._load_sam()
                self.backend = "sam"
            except Exception as e:  # no internet for the download, no onnxruntime: use MediaPipe
                self.why_not_sam = str(e)
        if self.backend is None:
            self._load_mediapipe()
            self.backend = "mediapipe"

    @staticmethod
    def sam_ready() -> bool:
        """SAM can start without downloading anything."""
        return available(SAM_ENCODER) and available(SAM_DECODER)

    def _load_sam(self) -> None:
        import onnxruntime as ort

        opts = ort.SessionOptions()
        opts.log_severity_level = 3
        enc, dec = ensure(SAM_ENCODER), ensure(SAM_DECODER)
        self._sam = (ort.InferenceSession(str(enc), opts, providers=["CPUExecutionProvider"]),
                     ort.InferenceSession(str(dec), opts, providers=["CPUExecutionProvider"]))

    def _load_mediapipe(self) -> None:
        from mediapipe.tasks.python import BaseOptions, vision

        with quiet_native_stderr():
            self._mp = vision.InteractiveSegmenter.create_from_options(vision.InteractiveSegmenterOptions(
                base_options=BaseOptions(model_asset_path=str(ensure("magic_touch.tflite"))),
                output_confidence_masks=True))

    def close(self) -> None:
        if self._mp is not None:
            self._mp.close()
            self._mp = None

    def set_image(self, rgb: np.ndarray, key=None) -> None:
        """The image the next clicks are on (RGB, uint8); ``key`` skips re-encoding the same image."""
        if key is not None and key == self._key:
            return
        self._key, self._rgb, self._emb = key, np.ascontiguousarray(rgb[:, :, :3]), None
        if self.backend == "sam":
            import cv2

            h, w = self._rgb.shape[:2]
            s = SAM_SIDE / max(h, w)
            small = cv2.resize(self._rgb, (round(w * s), round(h * s)), interpolation=cv2.INTER_AREA)
            self._emb = self._sam[0].run(None, {"input_image": small.astype(np.float32)})[0]

    def masks(self, points: list) -> list[tuple[np.ndarray, float]]:
        """[(mask, score)] for clicks [(x, y, keep)] (keep False: "not this"); best first."""
        if self._rgb is None:
            raise RuntimeError("no image set")
        pts = [(float(x), float(y), bool(k)) for x, y, k in points]
        if not any(k for _, _, k in pts):
            return []
        return self._sam_masks(pts) if self.backend == "sam" else self._mp_masks(pts)

    def _sam_masks(self, pts) -> list:
        h, w = self._rgb.shape[:2]
        s = SAM_SIDE / max(h, w)
        coords = np.array([[[x * s, y * s] for x, y, _ in pts] + [[0.0, 0.0]]], np.float32)
        labels = np.array([[1.0 if k else 0.0 for _, _, k in pts] + [-1.0]], np.float32)   # -1: padding
        masks, iou, _ = self._sam[1].run(None, {
            "image_embeddings": self._emb, "point_coords": coords, "point_labels": labels,
            "mask_input": np.zeros((1, 1, 256, 256), np.float32), "has_mask_input": np.zeros(1, np.float32),
            "orig_im_size": np.array([h, w], np.float32)})
        # 0 is the single best guess (better for several clicks), 1-3 go from a part to the whole
        order = [0, 1, 2, 3] if len(pts) > 1 else [1, 2, 3, 0]
        return [(masks[0, i] > 0, float(iou[0, i])) for i in order]

    def _mp_masks(self, pts) -> list:
        import mediapipe as mp
        from mediapipe.tasks.python.components.containers import keypoint
        from mediapipe.tasks.python.vision import InteractiveSegmenterRegionOfInterest as ROI

        h, w = self._rgb.shape[:2]
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=self._rgb)
        out = np.zeros((h, w), bool)
        for x, y, keep in sorted(pts, key=lambda p: not p[2]):   # the clicks on it first, then "not this"
            roi = ROI(format=ROI.Format.KEYPOINT, keypoint=keypoint.NormalizedKeypoint(x / w, y / h))
            m = self._mp.segment(image, roi).confidence_masks[0].numpy_view() > 0.5   # the category mask has it as 0
            out = out | m if keep else out & ~m
        return [(out, 1.0)]

    def outline(self, points: list, max_outlines: int = 3) -> list[dict]:
        """Up to ``max_outlines`` different outlines for the clicks, best first:
        [{polygon: [[x, y], ...], score, area}] in image pixels."""
        found, kept = [], []
        for mask, score in self.masks(points):
            if not mask.any() or any(_iou(mask, k) > 0.92 for k in kept):
                continue
            poly = mask_polygon(mask)
            if poly is None:
                continue
            kept.append(mask)
            found.append({"polygon": np.round(poly, 1).tolist(), "score": round(score, 3),
                          "area": int(mask.sum())})
            if len(found) == max_outlines:
                break
        return found


def _iou(a: np.ndarray, b: np.ndarray) -> float:
    union = np.logical_or(a, b).sum()
    return float(np.logical_and(a, b).sum() / union) if union else 1.0
