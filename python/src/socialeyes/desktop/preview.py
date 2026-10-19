"""Feed preview for the desktop app: a participant's feed as the phone will show it, from the study
as saved (compiled the same way `socialeyes load` compiles it), with small images inlined."""
from __future__ import annotations

import base64
import io
import json
import shutil
import tempfile
from pathlib import Path
from typing import Optional

from ..study.compiler import compile_study

IMAGE_WIDTH = 420   # preview pixels; the phone shows the full image
AVATAR = 64


def _data_uri(path: Path, width: int) -> Optional[str]:
    from PIL import Image

    try:
        with Image.open(path) as im:
            im = im.convert("RGB")
            if im.width > width:
                im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=82)
    except (OSError, ValueError):
        return None
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def feed_preview(folder: Path | str, participant_id: Optional[str] = None) -> dict:
    """{"participants", "participant", "platform", "theme", "group", "posts": [...]} for one participant."""
    tmp = Path(tempfile.mkdtemp(prefix="socialeyes-preview-"))
    try:
        build, _ = compile_study(folder, tmp / "package")
        manifest = json.loads((build / "study.json").read_text(encoding="utf-8"))
        ids = sorted(p.stem for p in (build / "plans").glob("*.json"))
        if not ids:
            raise ValueError("the study has no participant plans")
        pid = participant_id if participant_id in ids else ids[0]
        plan = json.loads((build / "plans" / f"{pid}.json").read_text(encoding="utf-8"))
        study, accounts = manifest["study"], manifest["accounts"]
        avatars: dict[str, Optional[str]] = {}

        def avatar(acc: str) -> Optional[str]:
            if acc not in avatars:
                a = accounts.get(acc, {}).get("avatar")
                avatars[acc] = _data_uri(build / a, AVATAR) if a else None
            return avatars[acc]

        posts = []
        for p in plan["feed"]:
            img = manifest["images"].get(p["image_id"], {})
            label = study.get("labels", {}).get(p["label"]) if p.get("label") else None
            posts.append({
                "post_id": p["post_id"], "role": p["role"], "cell": p.get("cell") or "",
                "handle": accounts.get(p["account_id"], {}).get("handle", p["account_id"]),
                "verified": bool(accounts.get(p["account_id"], {}).get("verified")),
                "avatar": avatar(p["account_id"]),
                "image": _data_uri(build / img["file"], IMAGE_WIDTH) if img.get("file") else None,
                "image_id": p["image_id"],
                "label": label, "caption": p.get("caption") or "", "likes": p.get("like_count"),
                "posted_ago": p.get("posted_ago") or "",
                "comments": [{"handle": accounts.get(c["account_id"], {}).get("handle", c["account_id"]), "text": c["text"]}
                             for c in p.get("comments", [])[:2]],
                "n_comments": len(p.get("comments", [])),
            })
        return {"participants": ids, "participant": pid, "platform": study["platform"]["name"],
                "theme": study["platform"].get("theme", "light"), "group": plan.get("group_key") or "",
                "posts": posts}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
