"""Tidy tables of a whole study, ready for Excel, SPSS or R (`socialeyes export`).

Every session in the study's data folder becomes rows in three tables:

- ``by_session.csv``: one row per session (the participant's group, questionnaire answers,
  session length, totals over the feed, recognition summary, quality flags for exclusions)
- ``by_item.csv``: one row per session x feed post (the post's conditions, time on screen,
  likes, comments, image ratings, recognition answers)
- ``by_condition.csv``: one row per session x cell of the within-subjects design (and one for
  the fillers): the means of by_item's numeric columns over that cell's posts

and ``codebook.csv`` describes every column. ``exploration.html`` is a blinded first look at them
(session flags, missing values, distributions, conditions behind codes; no tests; see explore.py). Files are UTF-8 with a byte-order mark, so Excel
shows accents correctly. Gaze columns join by_item once the gaze pipeline maps fixations to AOIs.
"""
from __future__ import annotations

import csv
import json
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import pandas as pd

from ..study.compiler import CHECKSUM_FILE, compile_study
from . import register
from .analyze import analyze_session
from .io import Session, load_session

FORMAT_VERSION = 1
TABLES = ("by_session", "by_item", "by_condition")

# Fixed columns: (table, column, description, values). Columns named after the study's factors,
# questionnaire items, rating items and recognition steps are added per study (see _codebook).
_ID = [
    ("participant_id", "Participant id", ""),
    ("session_uid", "The session (a participant can have more than one, see duplicate_id)", ""),
    ("group", "Between-subjects group number (1-based)", ""),
    ("group_key", "The group's levels, factor=level joined by |", ""),
    ("list", "Counterbalancing list of the within-subjects design (0-based)", ""),
]
_SESSION = [
    ("started", "When the session started (phone's local time)", "ISO 8601"),
    ("completed", "The session ran to its end", "1 = yes, 0 = no"),
    ("end_reason", "How it ended", "completed, aborted, ..."),
    ("duration_s", "Length of the whole session", "seconds"),
    ("feed_s", "Time on the feed step", "seconds"),
    ("feed_end_reason", "How the feed ended", "done_button, time_limit, continue"),
    ("posts_seen", "Feed posts that came on screen", "count"),
    ("critical_seen", "Critical posts that came on screen", "count"),
    ("likes", "Posts liked at the end of the feed", "count"),
    ("saves", "Posts saved at the end of the feed", "count"),
    ("shares", "Times the send button was used on posts", "count"),
    ("comments_opened", "Times a comments sheet was opened", "count"),
    ("comments_posted", "Comments and replies the participant posted", "count"),
    ("stories_viewed", "Different stories shown", "count"),
    ("stories_s", "Time stories were shown", "seconds"),
    ("reels_viewed", "Different reels played", "count"),
    ("reels_s", "Time reels were watched", "seconds"),
    ("background_s", "Time the app was in the background", "seconds"),
    ("interruptions", "Notifications, calls, alarms and covered screens", "count"),
    ("dnd_at_start", "Do Not Disturb at the start", "off, priority, alarms, total_silence"),
    ("n_warnings", "Quality warnings (see warnings)", "count"),
    ("warnings", "Quality warnings, joined by ;", ""),
    ("duplicate_id", "The participant id has more than one session (from sessions.csv)", "1 = yes, 0 = no"),
    ("notes", "The researcher's notes in sessions.csv", ""),
]
_ITEM = [
    ("position", "Position in the participant's feed (0 = top)", ""),
    ("post_id", "The post (posts.csv)", ""),
    ("role", "critical (manipulated) or filler", "critical, filler"),
    ("cell", "Within-subjects cell, factor=level joined by | (blank for fillers)", ""),
    ("image_id", "The image shown (images.csv)", ""),
    ("account_id", "Account that posted it (accounts.csv)", ""),
    ("label_shown", "Label shown on the post (blank: none)", ""),
    ("comment_variant", "Comment set shown (comments.csv variant)", ""),
    ("seen", "Came on screen at all", "1 = yes, 0 = no"),
    ("post_visible_s", "Any part of the post on screen", "seconds"),
    ("post_weighted_s", "Post time on screen x share of it visible", "seconds"),
    ("image_visible_s", "Any part of the image on screen", "seconds"),
    ("image_full_s", "The whole image on screen", "seconds"),
    ("image_weighted_s", "Image time on screen x share of it visible", "seconds"),
    ("first_seen_s", "When the post first came on screen, from the start of the feed", "seconds"),
    ("entries", "Times the post scrolled into view", "count"),
    ("comments_sheet_s", "Time its comments sheet was on screen", "seconds"),
    ("liked", "Liked at the end of the feed", "1 = yes, 0 = no"),
    ("like_via", "How it was first liked", "button, double_tap"),
    ("saved", "Saved at the end of the feed", "1 = yes, 0 = no"),
    ("shares", "Times the send button was used", "count"),
    ("comments_opened", "Times its comments sheet was opened", "count"),
    ("comments_posted", "Comments and replies the participant posted on it", "count"),
    ("comment_likes", "Comments the participant liked on it", "count"),
    ("caption_expanded", "The caption's \"more\" was tapped", "1 = yes, 0 = no"),
    ("label_tapped", "The label was tapped", "1 = yes, 0 = no"),
    ("profile_tapped", "The account's name or picture was tapped", "1 = yes, 0 = no"),
    ("image_taps", "Single taps on the image that did nothing else", "count"),
]
_FACE = [  # only in studies that record the front camera; from `socialeyes face`, over the feed step
    ("face_present", "Share of the feed's front camera frames with a face", "0-1"),
    ("face_multiple", "Share of the feed's frames with more than one face (someone else in view)", "0-1"),
    ("looking_at_phone", "Share of the feed's frames with a face where the participant looked at the phone, "
                         "against their own typical head pose and eye position", "0-1"),
    ("face_distance_cm", "Median distance from the face to the phone during the feed, from the iris size", "cm"),
    ("face_warnings", "The face analysis's warnings, joined by ;", ""),
]
_CONDITION = [
    ("cell", "Within-subjects cell (filler: all filler posts)", ""),
    ("n_posts", "Posts of this cell in the participant's feed", "count"),
]


@dataclass
class ExportResult:
    out_dir: Optional[str] = None
    exploration: Optional[str] = None
    unblinded: bool = False
    sessions: int = 0
    skipped: list = field(default_factory=list)   # (session folder, why)
    files: list = field(default_factory=list)

    def to_json(self) -> dict:
        return {"out_dir": self.out_dir, "exploration": self.exploration, "unblinded": self.unblinded,
                "sessions": self.sessions, "files": self.files,
                "skipped": [{"folder": f, "why": w} for f, w in self.skipped]}


def export_study(study_dir: Path | str, data_dir: Path | str, out_dir: Path | str,
                 build_for: Optional[Callable[[Path], Optional[Path]]] = None,
                 progress: Callable[[str], None] = lambda s: None,
                 analysis_dir: Optional[Path | str] = None, faces: bool = True, unblind: bool = False) -> ExportResult:
    """Writes the tables for every session under ``data_dir`` (<participant>/<session>/) to ``out_dir``.

    ``build_for(session folder)`` returns the compiled package the session ran, or None for the
    study as it compiles now; its plans give each participant's feed and trials. With
    ``analysis_dir`` (<participant>/<session>/ inside), sessions with front camera video get their
    face summary from there; with ``faces`` the ones not analysed yet are analysed first (slow:
    about real time).
    """
    r = ExportResult(out_dir=str(out_dir))
    data = Path(data_dir)
    if not data.is_dir():
        raise ValueError(f"no data folder yet ({data}): unload some sessions first")
    folders = sorted(p.parent for p in data.glob("*/*/session.json") if not p.parent.parent.name.startswith("."))
    reg = {row.get("session_uid"): row for row in register.read(data / register.REGISTER)[1]}
    tmp: Optional[Path] = None
    fresh: Optional[Path] = None

    def compiled() -> Path:
        nonlocal tmp, fresh
        if fresh is None:
            tmp = Path(tempfile.mkdtemp(prefix="socialeyes-export-"))
            fresh, _ = compile_study(study_dir, tmp / "package")
        return fresh

    try:
        sessions, items, studies = [], [], {}
        for n, folder in enumerate(folders, 1):
            progress(f"Session {n} of {len(folders)}: {folder.parent.name} ({folder.name})…")
            try:
                build = (build_for(folder) if build_for else None) or compiled()
                key = str(build)
                if key not in studies:
                    studies[key] = json.loads((build / "study.json").read_text(encoding="utf-8"))
                face = _face_summary(folder, analysis_dir, faces, progress) if analysis_dir else None
                fx = analysis_dir and Path(analysis_dir) / folder.parent.name / folder.name / "fixations.csv"
                fixations = pd.read_csv(fx) if fx and fx.is_file() else None
                srow, irows = _session_tables(folder, build, studies[key], reg, face, fixations, aoi_names(build))
            except Exception as e:  # one bad session never stops the export
                r.skipped.append((str(folder), str(e)))
                continue
            sessions.append(srow)
            items.extend(irows)
        # the columns come from the study as it compiles now (or the sessions' own build)
        try:
            manifest = json.loads((compiled() / "study.json").read_text(encoding="utf-8"))
            names = aoi_names(compiled())
        except Exception:
            if not studies:
                raise
            manifest = next(iter(studies.values()))
            names = sorted({k[len("gaze_"):-len("_ms")] for row in items for k in row
                            if k.startswith("gaze_") and k.endswith("_ms") and k != "gaze_image_ms"})
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        tables = _frames(manifest, sessions, items, names)
        for name, df in tables.items():
            path = out / f"{name}.csv"
            df.to_csv(path, index=False, encoding="utf-8-sig", lineterminator="\n")
            r.files.append(str(path))
        path = out / "codebook.csv"
        _write_codebook(path, manifest, tables)
        r.files.append(str(path))
        from .explore import write_exploration

        study = manifest["study"]
        r.exploration = str(write_exploration(
            out, tables, manifest, {"ratings": [c for c, _, _ in _rating_columns(study)],
                                    "questionnaire": [c for c, _, _ in _questionnaire_columns(study)]}, unblind))
        r.unblinded = unblind
        r.files.append(r.exploration)
        r.sessions = len(sessions)
        return r
    finally:
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- one session


def _face_summary(folder: Path, analysis_dir: Path | str, run: bool, progress: Callable[[str], None]) -> Optional[dict]:
    """The session's face_summary.json from `socialeyes face`; analysed now if missing and ``run``."""
    if not (folder / "camera_frames.csv").is_file():
        return None
    out = Path(analysis_dir) / folder.parent.name / folder.name
    path = out / "face_summary.json"
    if not path.is_file() and run:
        from ..face.analyze import analyze_faces, write_face

        progress(f"Analysing the face video of {folder.parent.name} ({folder.name}); this takes about as long as the video…")
        write_face(analyze_faces(folder), out)
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def _face_columns(study: dict, face: Optional[dict]) -> dict:
    """by_session's face columns, over the feed step (blank when the face video wasn't analysed)."""
    feed = next((st["id"] for st in study["procedure"] if st["type"] == "feed"), None)
    st = ((face or {}).get("steps") or {}).get(feed) or {}
    dist = st.get("distance_mm_median")
    return {
        "face_present": st.get("face_share"),
        "face_multiple": st.get("multi_face_share"),
        "looking_at_phone": st.get("looking_share"),
        "face_distance_cm": None if dist is None else round(dist / 10, 1),
        "face_warnings": "; ".join((face or {}).get("warnings", [])) if face else None,
    }


def _front_camera(study: dict) -> bool:
    return bool(((study.get("logging") or {}).get("front_camera") or {}).get("enabled"))


def aoi_names(build: Path) -> list[str]:
    """Every AOI name in the study's AOI files, in order of first appearance."""
    manifest = json.loads((build / "study.json").read_text(encoding="utf-8"))
    names: list[str] = []
    for img in manifest["images"].values():
        if img.get("aoi"):
            for a in json.loads((build / img["aoi"]).read_text(encoding="utf-8"))["aois"]:
                if a["name"] not in names:
                    names.append(a["name"])
    return names


def gaze_columns(names: list[str]) -> list[str]:
    return ["gaze_fixations", "gaze_image_ms"] + [c for n in names for c in (f"gaze_{n}_ms", f"gaze_{n}_first_s")]


def _gaze(fixations: Optional[pd.DataFrame], post_id: str, first_seen_ns, names: list[str]) -> dict:
    """A post's gaze columns from fixations.csv (blank when the session has none)."""
    if fixations is None:
        return {}
    f = fixations[(fixations["post_id"] == post_id) & (fixations["image_id"].fillna("") != "")]
    out = {"gaze_fixations": len(f), "gaze_image_ms": round(float(f["duration_ms"].sum()), 1)}
    for n in names:
        g = f[f["aoi"].fillna("") == n]
        out[f"gaze_{n}_ms"] = round(float(g["duration_ms"].sum()), 1)
        first = g["t_start_ns"].min() if len(g) else None
        out[f"gaze_{n}_first_s"] = (round((first - first_seen_ns) / 1e9, 3)
                                    if first is not None and first_seen_ns is not None and first_seen_ns == first_seen_ns
                                    else None)
    return out


def _session_tables(folder: Path, build: Path, manifest: dict, reg: dict,
                    face: Optional[dict] = None, fixations: Optional[pd.DataFrame] = None,
                    names: Optional[list[str]] = None) -> tuple[dict, list[dict]]:
    s = load_session(folder)
    plan = json.loads((build / "plans" / f"{s.participant_id}.json").read_text(encoding="utf-8"))
    res = analyze_session(folder, build)
    q = res["quality"]
    study = manifest["study"]
    feed_start, feed_end = s.feed_window()
    ids = _ids(s, plan, study)

    # exposure per post: the post card, its image, its comments sheet
    exp = res["exposure"]
    by = {(r.post_id, r.element): r for r in exp.itertuples()} if len(exp) else {}

    def e(pid, element, col):
        r = by.get((pid, element))
        v = getattr(r, col) if r is not None else None
        return 0.0 if v is None or v != v else float(v)

    ev = s.events
    inter = res["interactions"]
    resp = _responses(s)
    ratings = _ratings(resp, plan, study)
    recog = _recognition(resp, plan, study)

    items = []
    for p in plan["feed"]:
        pid = p["post_id"]
        mine = inter[inter["post_id"] == pid] if "post_id" in inter.columns else inter.iloc[0:0]

        def last_state(kind, col):
            g = mine[mine["type"] == kind]
            return int(bool(g[col].iloc[-1])) if len(g) else 0

        def count(kind, where=None):
            g = mine[mine["type"] == kind]
            if where is not None and len(g):
                g = g[where(g)]
            return int(len(g))

        likes = mine[mine["type"] == "like"]
        first = by.get((pid, "post"))
        first_ns = getattr(first, "first_visible_ns", None) if first is not None else None
        row = {
            **ids,
            "position": p["position"], "post_id": pid, "role": p["role"], "cell": p.get("cell") or "",
            **{factor_col(f): (p.get("conditions") or {}).get(f, "") for f in _within(study)},
            "image_id": p["image_id"], "account_id": p["account_id"], "label_shown": p.get("label") or "",
            "comment_variant": p.get("comment_variant") or "",
            "seen": int(e(pid, "post", "visible_s") > 0),
            "post_visible_s": round(e(pid, "post", "visible_s"), 3),
            "post_weighted_s": round(e(pid, "post", "weighted_s"), 3),
            "image_visible_s": round(e(pid, "image", "visible_s"), 3),
            "image_full_s": round(e(pid, "image", "full_s"), 3),
            "image_weighted_s": round(e(pid, "image", "weighted_s"), 3),
            "first_seen_s": round((first_ns - feed_start) / 1e9, 3) if first_ns is not None and first_ns == first_ns else None,
            "entries": int(e(pid, "post", "entries")),
            "comments_sheet_s": round(e(pid, "sheet", "visible_s"), 3),
            "liked": last_state("like", "liked"),
            "like_via": next((v for v, l in zip(likes.get("via", []), likes.get("liked", [])) if l), "") if len(likes) else "",
            "saved": last_state("save", "saved"),
            "shares": count("share"),
            "comments_opened": count("comments_open"),
            "comments_posted": count("comment_submit"),
            "comment_likes": count("comment_like", lambda g: g["liked"] == True),  # noqa: E712
            "caption_expanded": int(count("caption_expand") > 0),
            "label_tapped": int(count("label_tap") > 0),
            "profile_tapped": int(count("profile_tap") > 0),
            "image_taps": count("image_tap"),
        }
        row.update(ratings.get(pid, {}))
        row.update(recog["items"].get(pid, {}))
        row.update(_gaze(fixations, pid, first_ns, names or []))
        items.append(row)

    steps = s.step_windows()
    feed_end_reason = ""
    ends = s.events_of("step_end")
    feed_ids = steps.loc[steps["step_type"] == "feed", "step_id"].tolist()
    if feed_ids and len(ends):
        fe = ends[ends["step_id"] == feed_ids[0]]
        feed_end_reason = fe["reason"].iloc[0] if len(fe) else ""
    stories = s.events_of("story_end")
    reels = s.events_of("reel_end")
    reg_row = reg.get(s.meta.get("session_uid") or folder.name, {})
    srow = {
        **ids,
        "started": s.meta.get("started_wall", ""),
        "completed": int(bool(q["completed"])),
        "end_reason": q.get("end_reason") or "did not end",
        "duration_s": q["duration_s"],
        "feed_s": q["feed_duration_s"],
        "feed_end_reason": feed_end_reason,
        "posts_seen": sum(r["seen"] for r in items),
        "critical_seen": sum(r["seen"] for r in items if r["role"] == "critical"),
        "likes": sum(r["liked"] for r in items),
        "saves": sum(r["saved"] for r in items),
        "shares": sum(r["shares"] for r in items),
        "comments_opened": sum(r["comments_opened"] for r in items),
        "comments_posted": int((ev["type"] == "comment_submit").sum()),
        "stories_viewed": int(s.events_of("story_start")["story_id"].nunique()) if (ev["type"] == "story_start").any() else 0,
        "stories_s": round(float(stories["shown_ms"].sum()) / 1000, 3) if len(stories) and "shown_ms" in stories else 0.0,
        "reels_viewed": int(s.events_of("reel_start")["reel_id"].nunique()) if (ev["type"] == "reel_start").any() else 0,
        "reels_s": round(float(reels["watched_ms"].sum()) / 1000, 3) if len(reels) and "watched_ms" in reels else 0.0,
        "background_s": q["background_s"],
        "interruptions": int(sum((q.get("interruptions") or {}).values())),
        "dnd_at_start": q.get("dnd_at_start") or "",
        "n_warnings": len(q["warnings"]),
        "warnings": "; ".join(q["warnings"]),
        "duplicate_id": int(reg_row.get("duplicate_id", "") in ("yes", "1", "true", "True")),
        "notes": reg_row.get("notes", ""),
    }
    srow.update(_questionnaires(resp, study))
    srow.update(recog["session"])
    if _front_camera(study):
        srow.update(_face_columns(study, face))
    return srow, items


def _ids(s: Session, plan: dict, study: dict) -> dict:
    return {
        "participant_id": s.participant_id,
        "session_uid": s.meta.get("session_uid") or s.path.name,
        "group": plan.get("group"),
        "group_key": plan.get("group_key") or s.group_key or "",
        "list": plan.get("list"),
        **{factor_col(f["name"]): (plan.get("between") or {}).get(f["name"], "")
           for f in study["factors"] if f["design"] == "between"},
    }


def factor_col(name: str) -> str:
    """A factor's column: its name, or <name>_level if that is one of the fixed columns."""
    fixed = {c for c, _, _ in _ID + _SESSION + _ITEM + _CONDITION + _FACE}
    return f"{name}_level" if name in fixed else name


def _within(study: dict) -> list[str]:
    return [f["name"] for f in study["factors"] if f["design"] == "within"]


def _responses(s: Session) -> pd.DataFrame:
    """The final answers: step_id, item_id, value, rt_ms, trial (-1 outside trials)."""
    r = s.events_of("response")
    if not len(r):
        return pd.DataFrame(columns=["step_id", "item_id", "value", "rt_ms", "trial"])
    r = r.copy()
    r["trial"] = r["trial"].fillna(-1).astype(int) if "trial" in r else -1
    if "rt_ms" not in r:
        r["rt_ms"] = None
    return r[["step_id", "item_id", "value", "rt_ms", "trial"]].drop_duplicates(["step_id", "item_id", "trial"], keep="last")


def _steps_of(study: dict, kind: str) -> list[dict]:
    return [st for st in study["procedure"] if st["type"] == kind]


def _questionnaire_columns(study: dict) -> list[tuple[str, str, dict]]:
    """(column, step id, item) per questionnaire item; the item id alone unless two steps share it."""
    pairs = [(st["id"], it) for st in _steps_of(study, "questionnaire") for it in st.get("items", [])]
    clash = {it["id"] for _, it in pairs if sum(1 for _, o in pairs if o["id"] == it["id"]) > 1}
    return [((f"{sid}_{it['id']}" if it["id"] in clash else it["id"]), sid, it) for sid, it in pairs]


def _questionnaires(resp: pd.DataFrame, study: dict) -> dict:
    got = {(r.step_id, r.item_id): r.value for r in resp[resp["trial"] == -1].itertuples()}
    return {col: got.get((sid, it["id"])) for col, sid, it in _questionnaire_columns(study)}


def _rating_columns(study: dict) -> list[tuple[str, str, dict]]:
    """(column, step id, item) per image_rating item, prefixed with the step id if there are several steps."""
    steps = _steps_of(study, "image_rating")
    return [((f"{st['id']}_{it['id']}" if len(steps) > 1 else it["id"]), st["id"], it)
            for st in steps for it in st.get("items", [])]


def _ratings(resp: pd.DataFrame, plan: dict, study: dict) -> dict:
    """post_id -> {rating column: value, <column>_rt_ms: rt}."""
    out: dict[str, dict] = {}
    cols = _rating_columns(study)
    for col, sid, it in cols:
        trials = ((plan.get("steps") or {}).get(sid) or {}).get("trials", [])
        g = resp[(resp["step_id"] == sid) & (resp["item_id"] == it["id"])]
        for r in g.itertuples():
            if 0 <= r.trial < len(trials) and trials[r.trial].get("post_id"):
                d = out.setdefault(trials[r.trial]["post_id"], {})
                d[col], d[f"{col}_rt_ms"] = r.value, r.rt_ms
    return out


_RECOG_KINDS = {"old": "old", "alternate": "alt"}


def _recognition_prefix(study: dict, sid: str) -> str:
    return "recog" if len(_steps_of(study, "recognition")) == 1 else sid


def _recognition(resp: pd.DataFrame, plan: dict, study: dict) -> dict:
    """{"items": post_id -> columns, "session": columns}: each post's old and alternate image's
    answers, and per step the hit rate (old said old) and false alarm rates (alternates and foils
    said old)."""
    items: dict[str, dict] = {}
    session: dict = {}
    for st in _steps_of(study, "recognition"):
        sid, pre = st["id"], _recognition_prefix(study, st["id"])
        trials = ((plan.get("steps") or {}).get(sid) or {}).get("trials", [])
        g = resp[resp["step_id"] == sid]
        said = {r.trial: (r.value, r.rt_ms) for r in g[g["item_id"] == "old_new"].itertuples()}
        conf = {r.trial: r.value for r in g[g["item_id"] == "confidence"].itertuples()}
        old_by_kind: dict[str, list[int]] = {"old": [], "alternate": [], "foil": []}
        for i, t in enumerate(trials):
            answer, rt = said.get(i, (None, None))
            if answer is not None:
                old_by_kind.setdefault(t["kind"], []).append(int(answer == "old"))
            short = _RECOG_KINDS.get(t["kind"])
            if short and t.get("post_id"):
                d = items.setdefault(t["post_id"], {})
                d[f"{pre}_{short}_response"] = answer
                d[f"{pre}_{short}_correct"] = None if answer is None else int(answer == t["answer"])
                d[f"{pre}_{short}_confidence"] = conf.get(i)
                d[f"{pre}_{short}_rt_ms"] = rt

        def rate(xs):
            return round(sum(xs) / len(xs), 4) if xs else None

        session[f"{pre}_hit_rate"] = rate(old_by_kind["old"])
        session[f"{pre}_fa_alternate"] = rate(old_by_kind["alternate"])
        session[f"{pre}_fa_foil"] = rate(old_by_kind["foil"])
    return {"items": items, "session": session}


# ---------------------------------------------------------------- tables


def _columns(manifest: dict, names: Optional[list[str]] = None) -> dict[str, list[str]]:
    """Every table's columns in order, for this study."""
    study = manifest["study"]
    between = [factor_col(f["name"]) for f in study["factors"] if f["design"] == "between"]
    ids = [c for c, _, _ in _ID] + between
    within = [factor_col(f) for f in _within(study)]
    rating = [c for col, _, _ in _rating_columns(study) for c in (col, f"{col}_rt_ms")]
    recog_item, recog_session = [], []
    for st in _steps_of(study, "recognition"):
        pre = _recognition_prefix(study, st["id"])
        recog_item += [f"{pre}_{k}_{m}" for k in ("old", "alt") for m in ("response", "correct", "confidence", "rt_ms")]
        recog_session += [f"{pre}_hit_rate", f"{pre}_fa_alternate", f"{pre}_fa_foil"]
    item_cols = [c for c, _, _ in _ITEM]
    by_item = ids + item_cols[:4] + within + item_cols[4:] + rating + recog_item + gaze_columns(names or [])
    by_session = ids + [c for c, _, _ in _SESSION] + [c for c, _, _ in _questionnaire_columns(study)] + recog_session
    if _front_camera(study):
        by_session += [c for c, _, _ in _FACE]
    return {"by_session": by_session, "by_item": by_item, "between": between, "within": within, "ids": ids}


def _frames(manifest: dict, sessions: list[dict], items: list[dict],
            names: Optional[list[str]] = None) -> dict[str, pd.DataFrame]:
    cols = _columns(manifest, names)
    by_session = pd.DataFrame(sessions).reindex(columns=cols["by_session"])
    by_item = pd.DataFrame(items).reindex(columns=cols["by_item"])
    return {"by_session": by_session, "by_item": by_item, "by_condition": _by_condition(by_item, cols)}


# by_item columns that are labels, answers or positions rather than measures to average
_NOT_MEASURES = {"position", "group", "list"}


def _by_condition(items: pd.DataFrame, cols: dict) -> pd.DataFrame:
    """Means of by_item's numeric columns per session x cell (fillers as one cell, "filler")."""
    keys = cols["ids"] + ["cell"] + cols["within"]
    measures = [c for c in cols["by_item"] if c not in keys and c not in _NOT_MEASURES
                and not c.endswith("_response") and c not in {"post_id", "role", "image_id", "account_id", "label",
                                                               "comment_variant", "like_via", "label_shown"}]
    out_cols = keys + ["n_posts"] + measures
    if not len(items):
        return pd.DataFrame(columns=out_cols)
    d = items.copy()
    d.loc[d["role"] == "filler", "cell"] = "filler"
    for c in measures:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    for c in cols["within"]:
        d[c] = d[c].fillna("")
    g = d.groupby(["session_uid", "cell"], sort=False, dropna=False)
    first = g[[k for k in keys if k not in ("session_uid", "cell")]].first()
    agg = g[measures].mean().round(4)
    agg.insert(0, "n_posts", g.size())
    out = first.join(agg).reset_index()
    # cells in design order within each session: the critical cells, then fillers
    out["_filler"] = out["cell"] == "filler"
    out = out.sort_values(["participant_id", "session_uid", "_filler", "cell"], kind="stable").drop(columns="_filler")
    return out.reindex(columns=out_cols)


# ---------------------------------------------------------------- codebook


def _write_codebook(path: Path, manifest: dict, tables: dict[str, pd.DataFrame]) -> None:
    study = manifest["study"]
    desc: dict[str, tuple[str, str]] = {c: (d, v) for c, d, v in _ID + _SESSION + _ITEM + _CONDITION + _FACE}
    desc["gaze_fixations"] = ("Fixations on the post's image (from socialeyes gaze; blank: no eye tracking)", "count")
    desc["gaze_image_ms"] = ("Time fixating the post's image", "milliseconds")
    for c in tables["by_item"].columns:
        if c.startswith("gaze_") and c.endswith("_first_s"):
            n = c[len("gaze_"):-len("_first_s")]
            desc[c] = (f"Time from the post first coming on screen to the first fixation in AOI {n} "
                       "(blank: never fixated)", "seconds")
        elif c.startswith("gaze_") and c.endswith("_ms") and c not in desc:
            n = c[len("gaze_"):-len("_ms")]
            desc[c] = (f"Time fixating AOI {n} of the post's image", "milliseconds")
    for f in study["factors"]:
        desc[factor_col(f["name"])] = (f"{f['design'].capitalize()}-subjects factor {f['name']}",
                                       ", ".join(map(str, f["levels"])))
    for col, sid, it in _questionnaire_columns(study):
        desc[col] = (f"Questionnaire {sid}: {it.get('text', '')}", _item_values(it))
    for col, sid, it in _rating_columns(study):
        desc[col] = (f"Image rating ({sid}) of this post's image: {it.get('text', '')}", _item_values(it))
        desc[f"{col}_rt_ms"] = (f"Time to the last change of {col}, from the rating page appearing", "milliseconds")
    for st in _steps_of(study, "recognition"):
        pre = _recognition_prefix(study, st["id"])
        for short, what in (("old", "the version of this post's image the participant saw"),
                            ("alt", "the other version of this post's image (not seen)")):
            desc[f"{pre}_{short}_response"] = (f"Recognition ({st['id']}): answer to {what}", "old, new")
            desc[f"{pre}_{short}_correct"] = (f"Recognition ({st['id']}): the answer to {what} was right",
                                              "1 = yes, 0 = no")
            desc[f"{pre}_{short}_confidence"] = (f"Recognition ({st['id']}): confidence for {what}", "1-4")
            desc[f"{pre}_{short}_rt_ms"] = (f"Recognition ({st['id']}): time to answer for {what}", "milliseconds")
        desc[f"{pre}_hit_rate"] = (f"Recognition ({st['id']}): share of seen images called old", "0-1")
        desc[f"{pre}_fa_alternate"] = (f"Recognition ({st['id']}): share of unseen versions of seen posts called old",
                                       "0-1")
        desc[f"{pre}_fa_foil"] = (f"Recognition ({st['id']}): share of never-shown foil images called old", "0-1")
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["table", "column", "description", "values"])
        for name in TABLES:
            for c in tables[name].columns:
                d, v = desc.get(c, ("", ""))
                if name == "by_condition" and c not in {k for k, _, _ in _ID + _CONDITION} and c not in {
                        factor_col(f["name"]) for f in study["factors"]}:
                    if v.startswith("1 = yes"):
                        d, v = f"Share of the cell's posts with by_item {c} = 1", "0-1"
                    else:
                        d = f"Mean over the cell's posts of by_item {c}"
                w.writerow([name, c, d, v])


def _item_values(it: dict) -> str:
    kind = it.get("kind")
    if kind == "vas":
        return f"0-1 ({it.get('min_label') or 'left'} to {it.get('max_label') or 'right'})"
    if kind == "likert":
        labels = it.get("labels")
        return f"1-{it.get('points')}" + (f" ({labels[0]} to {labels[-1]})" if labels else "")
    if it.get("options"):
        return ", ".join(map(str, it["options"]))
    return kind or ""


def export(study_dir: Path | str, data_dir: Path | str | None = None, out_dir: Path | str | None = None,
           progress: Callable[[str], None] = lambda s: None, faces: bool = True, unblind: bool = False) -> ExportResult:
    """export_study with the study's folders from the settings (data folder, <data folder>/export)
    and each session's own build where it was kept at load time."""
    from .. import settings
    from ..phone.unload import study_id_of

    sid = study_id_of(study_dir)
    data = Path(data_dir) if data_dir else settings.data_dir(sid)
    out = Path(out_dir) if out_dir else (data / "export" if data_dir else settings.export_dir(sid))
    return export_study(study_dir, data, out, build_for=snapshot_or_none(sid), progress=progress,
                        analysis_dir=settings.analysis_dir(sid), faces=faces, unblind=unblind)


def snapshot_or_none(study_id: str) -> Callable[[Path], Optional[Path]]:
    """build_for for export_study: the exact build each session ran, when it was kept at load time."""
    from .. import settings

    def find(folder: Path) -> Optional[Path]:
        try:
            sha = json.loads((folder / "session.json").read_text(encoding="utf-8")).get("package_sha256")
        except (OSError, ValueError):
            return None
        snap = settings.build_snapshot(study_id, sha) if sha else None
        return snap if snap is not None and (snap / CHECKSUM_FILE).is_file() else None

    return find
