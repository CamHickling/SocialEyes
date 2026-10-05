"""Which edits would break a study that already has sessions (CAM-160).

Two compiled builds are compared on what participants get and what the analysis
relies on; text and looks are left out, so fixing a typo is never "breaking":

- each participant's plan: group, list, feed order, conditions, the image each post
  shows, labels, like counts, comment variant, which comments a post has and their
  order (not their wording), and the order of rating and recognition trials;
- the content of every image, story image and reel video (by SHA-256, so replacing an
  image under the same name counts);
- procedure step ids and types and question ids (the data's columns);
- the study id, and participant ids that would disappear.

A breaking edit needs a new version number; sessions keep the package hash they ran,
so the analysis can tell versions apart.
"""
from __future__ import annotations

import json
from pathlib import Path

from .compiler import CHECKSUM_FILE

FEED_KEYS = ("post_id", "role", "cell", "image_id", "label", "like_count", "comment_variant")
CATEGORIES = {"feed": "post order or conditions", "comments": "comments shown", "steps": "rating or recognition trials",
              "group": "between-subjects group"}


def _plan_parts(plan: dict) -> dict:
    return {
        "group": (plan.get("group_key"), plan.get("list")),
        "feed": [tuple(e.get(k) for k in FEED_KEYS) for e in plan.get("feed", [])],
        "comments": [(e.get("post_id"), [c.get("comment_id") for c in e.get("comments", [])]) for e in plan.get("feed", [])],
        "texts": [[c.get("text", "") for c in e.get("comments", [])] for e in plan.get("feed", [])],
        "steps": plan.get("steps", {}),
    }


def _comments_changed(a: dict, b: dict) -> bool:
    """Comments added, removed or re-identified, or the same comments in another order.

    Default comment ids follow the order (crit01_neutral_1, _2, ...), so a reorder keeps
    the ids and moves the texts: same texts in a different order is a reorder, while a
    changed text is a wording edit (safe).
    """
    if a["comments"] != b["comments"]:
        return True
    return any(x != y and sorted(x) == sorted(y) for x, y in zip(a["texts"], b["texts"]))


def _media_hashes(build: Path, manifest: dict) -> dict:
    sums = {}
    for line in (build / CHECKSUM_FILE).read_text(encoding="utf-8").splitlines():
        digest, _, rel = line.partition("  ")
        sums[rel] = digest
    shown = {f"image {i}": img["file"] for i, img in manifest.get("images", {}).items()}
    shown.update({f"story {s['story_id']}": s["file"] for s in manifest.get("stories", [])})
    shown.update({f"reel {r['reel_id']}": r["file"] for r in manifest.get("reels", [])})
    return {name: (rel, sums.get(rel)) for name, rel in shown.items()}


def _steps(manifest: dict) -> list:
    return [(s.get("id"), s.get("type"), [i.get("id") for i in s.get("items", [])])
            for s in manifest["study"].get("procedure", [])]


def _load(build: Path) -> tuple[dict, dict]:
    manifest = json.loads((build / "study.json").read_text(encoding="utf-8"))
    plans = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted((build / "plans").glob("*.json"))}
    return manifest, plans


def _ids(ids: list[str]) -> str:
    return ", ".join(ids[:5]) + (f" and {len(ids) - 5} more" if len(ids) > 5 else "")


def against_sessions(study_id: str, new_build: Path | str) -> dict | None:
    """Compare a new build with the build the study's latest registered session ran (its snapshot).

    None when there are no sessions, no snapshot to compare with, the version number went up,
    or nothing breaks; else {"reasons", "sessions", "version"}.
    """
    from .. import settings
    from ..session import register

    _, rows = register.read(settings.data_dir(study_id) / register.REGISTER)
    for row in reversed(rows):
        sha = row.get("package_sha256")
        snap = settings.build_snapshot(study_id, sha) if sha else None
        if snap and (snap / CHECKSUM_FILE).is_file():
            break
    else:
        return None
    old_version = json.loads((snap / "study.json").read_text(encoding="utf-8"))["study"]["version"]
    new_version = json.loads((Path(new_build) / "study.json").read_text(encoding="utf-8"))["study"]["version"]
    if new_version > old_version:
        return None
    reasons = breaking_changes(snap, new_build)
    return {"reasons": reasons, "sessions": len(rows), "version": old_version} if reasons else None


def breaking_changes(old_build: Path | str, new_build: Path | str) -> list[str]:
    """Plain-language reasons the new build would break sessions run with the old one ([] = safe)."""
    old_m, old_plans = _load(Path(old_build))
    new_m, new_plans = _load(Path(new_build))
    reasons: list[str] = []

    if old_m["study"]["id"] != new_m["study"]["id"]:
        reasons.append(f"The study id would change from {old_m['study']['id']} to {new_m['study']['id']}; "
                       "its sessions are filed under the old id.")

    gone = [pid for pid in old_plans if pid not in new_plans]
    if gone:
        reasons.append(f"Participant ids {_ids(gone)} would no longer have a plan.")

    changed: dict[str, list[str]] = {}
    for pid, plan in old_plans.items():
        if pid not in new_plans:
            continue
        a, b = _plan_parts(plan), _plan_parts(new_plans[pid])
        for part in ("group", "feed", "comments", "steps"):
            if (_comments_changed(a, b) if part == "comments" else a[part] != b[part]):
                changed.setdefault(part, []).append(pid)
    for part, pids in changed.items():
        reasons.append(f"The {CATEGORIES[part]} would change for {len(pids)} participant(s) ({_ids(pids)}).")

    old_media, new_media = _media_hashes(Path(old_build), old_m), _media_hashes(Path(new_build), new_m)
    replaced = [f"{name} ({old_media[name][0]})" for name in old_media
                if name in new_media and old_media[name] != new_media[name]]
    if replaced:
        reasons.append(f"Shown content would be replaced or renamed: {_ids(replaced)}.")

    if _steps(old_m) != _steps(new_m):
        reasons.append("Procedure steps or question ids would change, so the data's columns wouldn't line up "
                       "with the sessions already collected.")
    return reasons
