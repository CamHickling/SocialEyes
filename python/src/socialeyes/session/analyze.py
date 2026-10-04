"""Run all session analyses and write the derived tables (see docs/EVENT_LOG.md)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import pandas as pd

from ..study.aoi import aoiset_from_json
from .gestures import GestureParams, strokes
from .io import load_session
from .quality import session_quality
from .touch import occlusion, touch_targets
from .viewport import Layout

INTERACTION_TYPES = ("like", "comments_open", "comments_close", "comments_sheet", "comment_like", "caption_expand",
                     "profile_tap", "label_tap", "image_tap", "save", "share", "home_tap", "comment_submit",
                     "story_open", "story_start", "story_end", "story_swipe", "story_close", "story_like",
                     "story_share", "story_reply",
                     "done_button_shown")  # comment_edit, story_reply_edit (every draft change) stay in events.jsonl only


def analyze_session(session_dir: Path | str, build_dir: Path | str | None = None,
                    params: GestureParams = GestureParams(), finger_radius_mm: float = 8.0) -> dict:
    """Returns {"quality": dict, "strokes", "exposure", "touch_targets", "occlusion", "interactions": DataFrames}.

    With ``build_dir`` (the compiled study) touches are mapped to image pixels
    and AOIs, and exposure/occlusion rows get the post's role, cell and image.
    """
    s = load_session(session_dir)
    layout = Layout(s.viewport)
    plan_posts: dict[str, dict] = {}
    aois, sizes = {}, {}
    if build_dir is not None:
        build = Path(build_dir)
        manifest = json.loads((build / "study.json").read_text(encoding="utf-8"))
        if manifest["study"]["id"] != s.meta.get("study_id"):
            raise ValueError(f"session is from study {s.meta.get('study_id')!r} but {build} is "
                             f"{manifest['study']['id']!r}")
        plan_path = build / "plans" / f"{s.participant_id}.json"
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        plan_posts = {e["post_id"]: e for e in plan["feed"]}
        for image_id, img in manifest["images"].items():
            sizes[image_id] = (img["width"], img["height"])
            if img["aoi"]:
                aois[image_id] = aoiset_from_json(json.loads((build / img["aoi"]).read_text(encoding="utf-8")))

    _, feed_end = s.feed_window()
    targets = touch_targets(s.touch, layout, {p: e["image_id"] for p, e in plan_posts.items()}, aois, sizes)
    results = {
        "quality": session_quality(s),
        "strokes": strokes(s.touch, s.px_per_dp, params),
        "exposure": layout.exposure(feed_end, s.feed_area),
        "touch_targets": targets.drop(columns="image_screen_w"),
        "occlusion": occlusion(targets, aois, s.px_per_mm, finger_radius_mm),
        "interactions": s.events_of(*INTERACTION_TYPES).reset_index(drop=True),
    }
    if plan_posts:
        for key in ("exposure", "occlusion"):
            df = results[key]
            df.insert(1, "role", df["post_id"].map(lambda p: plan_posts.get(p, {}).get("role", "")))
            df.insert(2, "cell", df["post_id"].map(lambda p: plan_posts.get(p, {}).get("cell") or ""))
            if "image_id" not in df.columns:
                df.insert(3, "image_id", df["post_id"].map(lambda p: plan_posts.get(p, {}).get("image_id", "")))
    return results


def write_results(results: dict, out_dir: Path | str) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "quality.json").write_text(json.dumps(results["quality"], indent=2) + "\n", encoding="utf-8")
    for name, df in results.items():
        if isinstance(df, pd.DataFrame):
            df.to_csv(out / f"{name}.csv", index=False)
    return out


def default_out_dir(session_dir: Path | str, quality: dict, study_id: Optional[str]) -> Path:
    return Path("analysis_out") / (study_id or "unknown") / quality["participant_id"] / (
        quality.get("session_uid") or Path(session_dir).name)
