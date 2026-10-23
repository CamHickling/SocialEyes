"""Features marked experimental: they pass the tests, but haven't yet been shown to give results
to rely on in a real study. Wherever one appears, it says so and why: a badge in the desktop app
(ui.js EXPERIMENTAL, kept the same as this list by a test), a note from the command line, the
codebook's descriptions of its columns, and the README's Feature status.

Take a feature off this list once it has been checked on real data, and say how in the commit.
"""
from __future__ import annotations

from typing import Optional

FEATURES = {
    "face_analysis": (
        "Face video analysis",
        "Looking away and distance were checked on one recording of known actions. Expressions are "
        "MediaPipe's estimates, not coded facial action units, and haven't been checked against human coding."),
    "auto_aois": (
        "Automatic AOIs and click-to-outline",
        "The outlines come from segmentation models and haven't been checked on real stimuli: look at "
        "every AOI before collecting data."),
    "gaze": (
        "Fixations and heatmaps",
        "Tested on one real session and on simulated fixations."),
}


def note(key: str) -> str:
    title, why = FEATURES[key]
    return f"{title} is experimental. {why}"


def column_feature(column: str) -> Optional[str]:
    """The experimental feature an export column comes from, if any."""
    if column.startswith("face_") or column == "looking_at_phone":
        return "face_analysis"
    if column.startswith("gaze_"):
        return "gaze"
    return None
