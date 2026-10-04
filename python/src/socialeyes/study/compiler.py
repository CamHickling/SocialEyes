"""Study compiler: load a study folder, cross-check it and build participant plans.

A study folder holds study.yaml plus the CSVs it names (column reference in
docs/STUDY_DESIGN.md):

* accounts.csv  account_id, handle, avatar [, display_name, verified]
* images.csv    image_id, file [, post_id, version, aoi_file]
* posts.csv     post_id, role, account_id [, default_version, caption, like_count, posted_ago]
* comments.csv  post_id, account_id, text [, variant, order, like_count]   (optional file)
* captions.csv  post_id, variant, text                                       (optional file)
* stories.csv   account_id, file [, story_id, order, duration_s, posted_ago, aoi_file]  (optional file)
* reels.csv     account_id, file [, reel_id, order, caption, like_count, audio, posted_ago]  (optional file)

``check_study`` collects every problem it can find instead of stopping at the
first one, so a researcher can fix a whole batch at once. ``compile_study``
writes the package the phone app loads::

    <out>/study.json        resolved study, lookup tables, sync code, ...
    <out>/plans/P001.json   one plan per participant (feed order, conditions, trials)
    <out>/plans.csv         one row per participant (group, list, between levels)
    <out>/media/...         images and avatars, same relative paths as the study folder
    <out>/aois/<image>.json AOIs normalised to the native format
    <out>/tags/...          screen AprilTags shown during marker_calibration
"""
from __future__ import annotations

import csv
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml
from PIL import Image as PILImage
from pydantic import ValidationError

from .. import __version__
from .aoi import AOISet, load_aoi_file
from .design import (
    Assignment,
    assignment_schedule,
    cell_for,
    cells,
    m_sequence,
    order_feed,
    participant_rng,
    validation_points,
)
from .schema import Factor, ImageRatingStep, RecognitionStep, Study, ValidationStep

FORMAT_VERSION = 1
ATTRIBUTES = ("image_version", "label", "comment_variant", "caption_variant", "like_count")

# (required columns, optional columns) per CSV.
COLUMNS: dict[str, tuple[list[str], list[str]]] = {
    "accounts": (["account_id", "handle", "avatar"], ["display_name", "verified"]),
    "images": (["image_id", "file"], ["post_id", "version", "aoi_file"]),
    "posts": (["post_id", "role", "account_id"], ["default_version", "caption", "like_count", "posted_ago"]),
    "comments": (["post_id", "account_id", "text"], ["variant", "order", "like_count"]),
    "captions": (["post_id", "variant", "text"], []),
    "stories": (["account_id", "file"], ["story_id", "order", "duration_s", "posted_ago", "aoi_file"]),
    "reels": (["account_id", "file"], ["reel_id", "order", "caption", "like_count", "audio", "posted_ago"]),
}


class StudyError(Exception):
    """The study folder has problems; ``errors`` lists every one that was found."""

    def __init__(self, errors: list[str], warnings: Optional[list[str]] = None):
        self.errors = errors
        self.warnings = warnings or []
        super().__init__(f"{len(errors)} problem(s) in the study:\n" + "\n".join(f"  - {e}" for e in errors))


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def dedupe(self) -> None:
        self.errors = list(dict.fromkeys(self.errors))
        self.warnings = list(dict.fromkeys(self.warnings))


@dataclass(frozen=True)
class Account:
    account_id: str
    handle: str
    display_name: str
    avatar: str
    verified: bool


@dataclass(frozen=True)
class Image:
    image_id: str
    file: str
    post_id: str  # "" for recognition foils
    version: str
    aoi_file: str  # "" = use aois/<file stem>.json if it exists


@dataclass(frozen=True)
class Post:
    post_id: str
    role: str  # critical | filler
    account_id: str
    default_version: Optional[str]
    caption: str
    like_count: int
    posted_ago: str


@dataclass(frozen=True)
class Comment:
    post_id: str
    variant: str  # "" = the default set
    order: int
    account_id: str
    text: str
    like_count: int


@dataclass
class StudyBundle:
    """A loaded study folder. Only produced by ``check_study`` when it has no errors."""

    root: Path
    study: Study
    accounts: dict[str, Account]
    images: dict[str, Image]
    posts: dict[str, Post]  # in posts.csv order
    comments: dict[tuple[str, str], list[Comment]]  # (post_id, variant) -> comments in display order
    captions: dict[tuple[str, str], str]  # (post_id, variant) -> caption
    image_sizes: dict[str, tuple[int, int]]
    aois: dict[str, AOISet]  # by image_id, and by story_id for stories with AOIs
    stories: list["Story"] = field(default_factory=list)  # grouped by account, in display order
    reels: list["Reel"] = field(default_factory=list)  # in display order

    @property
    def critical(self) -> list[Post]:
        return [p for p in self.posts.values() if p.role == "critical"]

    @property
    def fillers(self) -> list[Post]:
        return [p for p in self.posts.values() if p.role == "filler"]

    def versions(self, post_id: str) -> dict[str, Image]:
        return {i.version: i for i in self.images.values() if i.post_id == post_id}


# ---------------------------------------------------------------- loading


def _read_csv(path: Path, kind: str, rep: Report, required: bool = True) -> list[tuple[str, dict[str, str]]]:
    """Rows as (location, values). Rows with problems are reported and skipped."""
    req, opt = COLUMNS[kind]
    if not path.is_file():
        if required:
            rep.errors.append(f"{path.name}: file not found")
        return []
    rows: list[tuple[str, dict[str, str]]] = []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        header = [h.strip() for h in (reader.fieldnames or [])]
        reader.fieldnames = header
        missing = [c for c in req if c not in header]
        unknown = [c for c in header if c not in req + opt]
        if missing:
            rep.errors.append(f"{path.name}: missing column(s) {missing}")
        if unknown:
            rep.errors.append(f"{path.name}: unknown column(s) {unknown}; allowed: {req + opt}")
        if len(set(header)) != len(header):
            rep.errors.append(f"{path.name}: duplicate column names")
        if missing or len(set(header)) != len(header):
            return []
        for row in reader:
            where = f"{path.name} line {reader.line_num}"
            if None in row:
                rep.errors.append(f"{where}: more values than columns (unquoted comma?)")
                continue
            values = {c: (row.get(c) or "").strip() for c in req + opt}
            if not any(values.values()):
                continue
            empty = [c for c in req if not values[c]]
            if empty:
                rep.errors.append(f"{where}: {', '.join(empty)} must not be empty")
                continue
            rows.append((where, values))
    return rows


def _int(value: str, where: str, column: str, rep: Report, default: int = 0) -> int:
    if value == "":
        return default
    try:
        n = int(value)
    except ValueError:
        rep.errors.append(f"{where}: {column} must be a whole number, got {value!r}")
        return default
    if n < 0:
        rep.errors.append(f"{where}: {column} must not be negative")
    return n


def _bool(value: str, where: str, column: str, rep: Report) -> bool:
    v = value.lower()
    if v in ("", "false", "no", "0"):
        return False
    if v in ("true", "yes", "1"):
        return True
    rep.errors.append(f"{where}: {column} must be true/false, got {value!r}")
    return False


def _study_file(root: Path, rel: str, where: str, column: str, rep: Report) -> Optional[str]:
    """Normalised relative path of a file inside the study folder, or None if invalid."""
    rel = rel.replace("\\", "/")
    path = root / rel
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        rep.errors.append(f"{where}: {column} {rel!r} must be inside the study folder")
        return None
    if not path.is_file():
        rep.errors.append(f"{where}: {column} {rel!r} not found")
        return None
    return Path(rel).as_posix()


def _duplicate(seen: set, key, where: str, what: str, rep: Report) -> bool:
    if key in seen:
        rep.errors.append(f"{where}: duplicate {what} {key!r}")
        return True
    seen.add(key)
    return False


def load_study_yaml(path: Path, rep: Report) -> Optional[Study]:
    if not path.is_file():
        rep.errors.append(f"{path.name}: file not found ({path})")
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        rep.errors.append(f"{path.name}: not valid YAML: {e}")
        return None
    try:
        return Study.model_validate(data)
    except ValidationError as e:
        for err in e.errors():
            loc = ".".join(str(p) for p in err["loc"]) or "(top level)"
            rep.errors.append(f"{path.name}: {loc}: {err['msg']}")
        return None


# ---------------------------------------------------------------- resolution


class _Unresolvable(Exception):
    pass


def factors_for(study: Study, role: str) -> list[Factor]:
    """Factors that apply to a post with this role.

    Critical posts get every factor. Fillers only get between-subject factors
    with ``applies_to: all`` (they have no within-subject cell).
    """
    return [f for f in study.factors if role == "critical" or (f.design == "between" and f.applies_to == "all")]


def _resolve(b: StudyBundle, post: Post, attribute: str, value: Optional[str]):
    """Concrete content for one post attribute. ``value=None`` means the post's default."""
    pid = post.post_id
    if attribute == "image_version":
        version = post.default_version if value is None else value
        if version is None:
            raise _Unresolvable(f"post {pid} has several images and no default_version")
        image = b.versions(pid).get(version)
        if image is None:
            have = sorted(b.versions(pid)) or ["(none)"]
            raise _Unresolvable(f"post {pid} has no image with version {version!r} (has {have})")
        return image.image_id
    if attribute == "label":
        if value is not None and value not in b.study.labels:
            raise _Unresolvable(f"label {value!r} is not defined under labels: in study.yaml")
        return value
    if attribute == "comment_variant":
        variant = value or ""
        found = b.comments.get((pid, variant), [])
        if variant and not found:
            raise _Unresolvable(f"post {pid} has no comments with variant {variant!r}")
        return found
    if attribute == "caption_variant":
        if not value:
            return post.caption
        if (pid, value) not in b.captions:
            raise _Unresolvable(f"post {pid} has no caption with variant {value!r} in captions.csv")
        return b.captions[(pid, value)]
    if attribute == "like_count":
        if value is None:
            return post.like_count
        try:
            n = int(value)
        except ValueError:
            n = -1
        if n < 0:
            raise _Unresolvable(f"like_count {value!r} is not a whole number >= 0")
        return n
    raise ValueError(attribute)


def _attribute_values(study: Study, post: Post, levels: dict[str, str]) -> dict[str, Optional[str]]:
    values: dict[str, Optional[str]] = {a: None for a in ATTRIBUTES}
    for f in factors_for(study, post.role):
        for attribute in f.sets:
            values[attribute] = f.value_for(attribute, levels[f.name])
    return values


# ---------------------------------------------------------------- checking


def check_study(study_dir: Path | str) -> tuple[Optional[StudyBundle], Report]:
    """Load and cross-check a study folder (or a study.yaml path).

    Returns (bundle, report). ``bundle`` is None if there are errors.
    """
    path = Path(study_dir)
    yaml_path = path if path.suffix.lower() in (".yaml", ".yml") else path / "study.yaml"
    root = yaml_path.parent
    rep = Report()
    study = load_study_yaml(yaml_path, rep)
    if study is None:
        return None, rep

    # accounts
    accounts: dict[str, Account] = {}
    for where, r in _read_csv(root / study.accounts, "accounts", rep):
        if _duplicate(set(accounts), r["account_id"], where, "account_id", rep):
            continue
        avatar = _study_file(root, r["avatar"], where, "avatar", rep) or ""
        accounts[r["account_id"]] = Account(
            r["account_id"], r["handle"].lstrip("@"), r["display_name"], avatar,
            _bool(r["verified"], where, "verified", rep),
        )

    # posts
    post_rows: list[tuple[str, dict[str, str]]] = []
    for where, r in _read_csv(root / study.posts, "posts", rep):
        if _duplicate({p["post_id"] for _, p in post_rows}, r["post_id"], where, "post_id", rep):
            continue
        if r["role"] not in ("critical", "filler"):
            rep.errors.append(f"{where}: role must be critical or filler, got {r['role']!r}")
            continue
        if r["account_id"] not in accounts:
            rep.errors.append(f"{where}: account_id {r['account_id']!r} is not in {study.accounts}")
        post_rows.append((where, r))

    # images
    images: dict[str, Image] = {}
    image_sizes: dict[str, tuple[int, int]] = {}
    post_ids = {r["post_id"] for _, r in post_rows}
    seen_versions: set[tuple[str, str]] = set()
    for where, r in _read_csv(root / study.images, "images", rep):
        if _duplicate(set(images), r["image_id"], where, "image_id", rep):
            continue
        if r["post_id"] and r["post_id"] not in post_ids:
            rep.errors.append(f"{where}: post_id {r['post_id']!r} is not in {study.posts}")
        if r["post_id"] and _duplicate(seen_versions, (r["post_id"], r["version"]), where, "(post_id, version)", rep):
            continue
        file = _study_file(root, r["file"], where, "file", rep)
        if file:
            try:
                with PILImage.open(root / file) as im:
                    image_sizes[r["image_id"]] = im.size
            except OSError:
                rep.errors.append(f"{where}: {file!r} is not a readable image")
        images[r["image_id"]] = Image(r["image_id"], file or "", r["post_id"], r["version"], r["aoi_file"])

    posts: dict[str, Post] = {}
    for where, r in post_rows:
        versions = sorted(i.version for i in images.values() if i.post_id == r["post_id"])
        if not versions:
            rep.errors.append(f"{where}: post {r['post_id']} has no image in {study.images}")
        default = r["default_version"] if r["default_version"] else (versions[0] if len(versions) == 1 else None)
        posts[r["post_id"]] = Post(
            r["post_id"], r["role"], r["account_id"], default, r["caption"],
            _int(r["like_count"], where, "like_count", rep), r["posted_ago"],
        )

    # comments (optional file)
    comments: dict[tuple[str, str], list[Comment]] = {}
    for n, (where, r) in enumerate(_read_csv(root / study.comments, "comments", rep, required=False)):
        if r["post_id"] not in posts:
            rep.errors.append(f"{where}: post_id {r['post_id']!r} is not in {study.posts}")
        if r["account_id"] not in accounts:
            rep.errors.append(f"{where}: account_id {r['account_id']!r} is not in {study.accounts}")
        c = Comment(r["post_id"], r["variant"], _int(r["order"], where, "order", rep, default=n), r["account_id"],
                    r["text"], _int(r["like_count"], where, "like_count", rep))
        comments.setdefault((c.post_id, c.variant), []).append(c)
    for group in comments.values():
        group.sort(key=lambda c: c.order)

    # captions (optional file)
    captions: dict[tuple[str, str], str] = {}
    for where, r in _read_csv(root / study.captions, "captions", rep, required=False):
        if r["post_id"] not in posts:
            rep.errors.append(f"{where}: post_id {r['post_id']!r} is not in {study.posts}")
        if not _duplicate(set(captions), (r["post_id"], r["variant"]), where, "(post_id, variant)", rep):
            captions[(r["post_id"], r["variant"])] = r["text"]

    b = StudyBundle(root, study, accounts, images, posts, comments, captions, image_sizes, {})
    b.stories = _load_stories(b, rep)
    b.reels = _load_reels(b, rep)
    _check_aois(b, rep)
    _check_design(b, rep)
    if not rep.errors:
        try:
            build_plans(b)  # dry run: feed-order constraints can only be checked by trying
        except ValueError as e:
            rep.errors.append(str(e))
    rep.dedupe()
    return (None if rep.errors else b), rep


@dataclass(frozen=True)
class Story:
    story_id: str
    account_id: str
    file: str
    order: int
    duration_s: Optional[float]
    posted_ago: str
    width: int
    height: int


def _load_stories(b: StudyBundle, rep: Report) -> list[Story]:
    """stories.csv (optional): stories per account, shown from the story circles."""
    name = b.study.stories
    rows = _read_csv(b.root / name, "stories", rep, required=False)
    stories: list[Story] = []
    account_order: list[str] = []
    per_account: dict[str, int] = {}
    for n, (where, r) in enumerate(rows):
        acc = r["account_id"]
        if acc not in b.accounts:
            rep.errors.append(f"{where}: account_id {acc!r} is not in {b.study.accounts}")
            continue
        per_account[acc] = per_account.get(acc, 0) + 1
        sid = r["story_id"] or f"{acc}_{per_account[acc]}"
        if _duplicate({s.story_id for s in stories}, sid, where, "story_id", rep):
            continue
        if sid in b.images:
            rep.errors.append(f"{where}: story_id {sid!r} is also an image_id in {b.study.images}; use another id")
            continue
        duration = None
        if r["duration_s"]:
            try:
                duration = float(r["duration_s"])
                if not 0 < duration <= 60:
                    raise ValueError
            except ValueError:
                rep.errors.append(f"{where}: duration_s must be a number of seconds between 0 and 60")
        file = _study_file(b.root, r["file"], where, "file", rep)
        size = (0, 0)
        if file:
            try:
                with PILImage.open(b.root / file) as im:
                    size = im.size
            except OSError:
                rep.errors.append(f"{where}: {file!r} is not a readable image")
        if acc not in account_order:
            account_order.append(acc)
        stories.append(Story(sid, acc, file or "", _int(r["order"], where, "order", rep, default=n),
                             duration, r["posted_ago"], *size))
        # AOIs are optional for stories: an explicit aoi_file, or aois/<file name>.json if present
        rel = r["aoi_file"] or f"aois/{Path(r['file']).stem}.json"
        if file and (r["aoi_file"] or (b.root / rel).is_file()):
            path = _study_file(b.root, rel, where, "AOI file", rep)
            if path:
                try:
                    aois = load_aoi_file(b.root / path)
                    if (aois.width, aois.height) != size:
                        rep.errors.append(f"{where}: AOI file {path!r} is for a {aois.width}x{aois.height} image "
                                          f"but {file!r} is {size[0]}x{size[1]}")
                    else:
                        b.aois[sid] = aois
                except (ValueError, KeyError, TypeError, json.JSONDecodeError) as e:
                    rep.errors.append(f"{where}: cannot read AOI file {path!r}: {e}")
    stories.sort(key=lambda s: (account_order.index(s.account_id), s.order))
    return stories


@dataclass(frozen=True)
class Reel:
    reel_id: str
    account_id: str
    file: str
    order: int
    caption: str
    like_count: int
    audio: str
    posted_ago: str
    width: int
    height: int
    duration_s: float


VIDEO_SUFFIXES = (".mp4", ".m4v", ".mov", ".3gp", ".webm", ".mkv")


def _video_info(path: Path) -> Optional[tuple[int, int, float]]:
    """(width, height, duration in s) of a video file, or None if it can't be read."""
    import cv2  # needs OpenCV; imported here so studies without reels don't need it

    if path.suffix.lower() not in VIDEO_SUFFIXES:
        return None
    cap = cv2.VideoCapture(str(path), cv2.CAP_FFMPEG)  # FFmpeg only: other readers open images as "videos"
    try:
        if not cap.isOpened():
            return None
        w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps, frames = cap.get(cv2.CAP_PROP_FPS), cap.get(cv2.CAP_PROP_FRAME_COUNT)
        if w <= 0 or h <= 0 or fps <= 0 or frames < 2:  # a still image opens as a 1-frame "video"
            return None
        return w, h, round(frames / fps, 3)
    finally:
        cap.release()


def _load_reels(b: StudyBundle, rep: Report) -> list[Reel]:
    """reels.csv (optional): short videos shown in the Reels tab."""
    rows = _read_csv(b.root / b.study.reels, "reels", rep, required=False)
    reels: list[Reel] = []
    per_account: dict[str, int] = {}
    for n, (where, r) in enumerate(rows):
        acc = r["account_id"]
        if acc not in b.accounts:
            rep.errors.append(f"{where}: account_id {acc!r} is not in {b.study.accounts}")
            continue
        per_account[acc] = per_account.get(acc, 0) + 1
        rid = r["reel_id"] or f"{acc}_reel{per_account[acc]}"
        if _duplicate({x.reel_id for x in reels}, rid, where, "reel_id", rep):
            continue
        file = _study_file(b.root, r["file"], where, "file", rep)
        info = _video_info(b.root / file) if file else None
        if file and info is None:
            rep.errors.append(f"{where}: {file!r} is not a readable video (use MP4: H.264 or MPEG-4)")
        w, h, dur = info or (0, 0, 0.0)
        reels.append(Reel(rid, acc, file or "", _int(r["order"], where, "order", rep, default=n), r["caption"],
                          _int(r["like_count"], where, "like_count", rep), r["audio"], r["posted_ago"], w, h, dur))
    reels.sort(key=lambda x: x.order)
    return reels


def _check_aois(b: StudyBundle, rep: Report) -> None:
    critical = {p.post_id for p in b.critical}
    names_by_post: dict[str, dict[str, list[str]]] = {}
    for img in b.images.values():
        where = f"{b.study.images} image {img.image_id}"
        rel = img.aoi_file or f"aois/{Path(img.file).stem}.json"
        needed = img.post_id in critical
        if not img.aoi_file and not needed and not (b.root / rel).is_file():
            continue
        path = _study_file(b.root, rel, where, "AOI file", rep)
        if path is None:
            if needed:
                rep.errors.append(f"{where}: images of critical posts need an AOI file")
            continue
        try:
            aois = load_aoi_file(b.root / path)
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as e:
            rep.errors.append(f"{where}: cannot read AOI file {path!r}: {e}")
            continue
        size = b.image_sizes.get(img.image_id)
        if size and (aois.width, aois.height) != size:
            rep.errors.append(
                f"{where}: AOI file {path!r} is for a {aois.width}x{aois.height} image "
                f"but {img.file!r} is {size[0]}x{size[1]}"
            )
            continue
        b.aois[img.image_id] = aois
        if img.post_id:
            names_by_post.setdefault(img.post_id, {})[img.version] = sorted(aois.names())
    for pid, by_version in names_by_post.items():
        if len({tuple(v) for v in by_version.values()}) > 1:
            rep.warnings.append(f"post {pid}: AOI names differ between image versions {by_version}")


def _check_design(b: StudyBundle, rep: Report) -> None:
    study = b.study
    for f in study.factors:
        if f.design == "within" and f.applies_to == "all":
            rep.errors.append(f"factor {f.name}: within-subject factors can only apply to critical posts")
    if not b.posts:
        rep.errors.append(f"{study.posts}: no posts")
    if study.factors and not b.critical:
        rep.errors.append(f"{study.posts}: the study has factors but no critical posts")

    for post in b.posts.values():
        fs = factors_for(study, post.role)
        controlled = {a for f in fs for a in f.sets}
        for attribute in ATTRIBUTES:
            if attribute not in controlled:
                try:
                    _resolve(b, post, attribute, None)
                except _Unresolvable as e:
                    rep.errors.append(f"{study.posts}: {e}")
        for f in fs:
            for level in f.levels:
                for attribute in f.sets:
                    try:
                        _resolve(b, post, attribute, f.value_for(attribute, level))
                    except (ValueError, _Unresolvable) as e:
                        rep.errors.append(f"factor {f.name}={level}: {e}")

    n_cells = len(cells(study.within))
    if b.critical and len(b.critical) % n_cells:
        rep.warnings.append(
            f"{len(b.critical)} critical posts is not a multiple of {n_cells} within-subject cells; "
            "each participant will see some cells more often than others"
        )
    block = len(cells(study.between)) * n_cells
    if study.participants.n_plans % block:
        rep.warnings.append(
            f"participants.n_plans={study.participants.n_plans} is not a multiple of the "
            f"assignment block size {block}; the last block will be incomplete"
        )

    cam = study.logging.front_camera
    ids = [s.id for s in study.procedure]
    checks = [k for k, s in enumerate(study.procedure) if s.type == "camera_check"]
    if cam.enabled:
        recorded = [] if cam.steps == "all" else [k for k, s in enumerate(study.procedure) if s.id in cam.steps]
        if not checks:
            rep.warnings.append("logging.front_camera is enabled but the procedure has no camera_check step "
                                "to confirm the face is in view")
        elif recorded and checks[0] > recorded[0]:
            rep.warnings.append(f"the first camera_check comes after recorded step {ids[recorded[0]]!r}")
    elif checks:
        rep.warnings.append("the procedure has a camera_check step but logging.front_camera is not enabled")

    photos = [k for k, s in enumerate(study.procedure) if s.type == "profile_photo"]
    feed_at = next((k for k, s in enumerate(study.procedure) if s.type == "feed"), None)
    if photos and feed_at is not None and photos[0] > feed_at:
        rep.warnings.append("the profile_photo step comes after the feed, so the photo is never seen in the feed")
    if photos and cam.enabled and (cam.steps == "all" or any(ids[k] in cam.steps for k in photos)):
        rep.warnings.append("logging.front_camera records during the profile_photo step, but the camera can only "
                            "do one at a time; leave that step out of logging.front_camera.steps")

    for step in study.procedure:
        if isinstance(step, RecognitionStep):
            if step.lures in ("foils", "both"):
                for image_id in step.foils:
                    img = b.images.get(image_id)
                    if img is None:
                        rep.errors.append(f"procedure step {step.id}: foil {image_id!r} is not in {study.images}")
                    elif img.post_id:
                        rep.errors.append(
                            f"procedure step {step.id}: foil {image_id!r} belongs to post {img.post_id}; "
                            "foils must be images that never appear in the feed"
                        )
                if not step.foils:
                    rep.warnings.append(f"procedure step {step.id}: lures include foils but no foils are listed")
            elif step.foils:
                rep.warnings.append(f"procedure step {step.id}: foils are listed but lures is {step.lures!r}")
            if step.lures in ("alternate_version", "both"):
                for post in b.critical:
                    if len(b.versions(post.post_id)) < 2:
                        rep.warnings.append(
                            f"procedure step {step.id}: post {post.post_id} has only one image version, "
                            "so it gets no alternate-version lure"
                        )


# ---------------------------------------------------------------- plans


def participant_id(study: Study, index: int) -> str:
    p = study.participants
    return f"{p.id_prefix}{index + 1:0{p.id_digits}d}"


def build_plans(b: StudyBundle) -> list[dict]:
    schedule = assignment_schedule(b.study, b.study.participants.n_plans)
    plans = []
    for a in schedule:
        try:
            plans.append(build_plan(b, a))
        except ValueError as e:
            raise ValueError(f"cannot build the plan for {participant_id(b.study, a.participant_index)}: {e}") from e
    return plans


def _post_entry(b: StudyBundle, post: Post, levels: dict[str, str], cell: Optional[str]) -> dict:
    values = _attribute_values(b.study, post, levels)
    comments = _resolve(b, post, "comment_variant", values["comment_variant"])
    return {
        "post_id": post.post_id,
        "role": post.role,
        "cell": cell,
        "conditions": levels,
        "account_id": post.account_id,
        "image_id": _resolve(b, post, "image_version", values["image_version"]),
        "label": _resolve(b, post, "label", values["label"]),
        "caption": _resolve(b, post, "caption_variant", values["caption_variant"]),
        "like_count": _resolve(b, post, "like_count", values["like_count"]),
        "posted_ago": post.posted_ago,
        "comment_variant": values["comment_variant"] or "",
        "comments": [{"account_id": c.account_id, "text": c.text, "like_count": c.like_count} for c in comments],
    }


def build_plan(b: StudyBundle, a: Assignment) -> dict:
    study = b.study
    pid = participant_id(study, a.participant_index)
    within = cells(study.within)
    groups = cells(study.between)

    entries: dict[str, dict] = {}
    critical_cells: list[tuple[str, str]] = []
    for i, post in enumerate(b.critical):
        cell = within[cell_for(i, a.list, len(within))]
        entries[post.post_id] = _post_entry(b, post, {**cell.as_dict(), **a.between}, cell.key)
        critical_cells.append((post.post_id, cell.key))
    for post in b.fillers:
        levels = {f.name: a.between[f.name] for f in factors_for(study, "filler")}
        entries[post.post_id] = _post_entry(b, post, levels, None)

    if study.feed.order == "fixed":
        order = list(b.posts)
    else:
        order = order_feed(critical_cells, [p.post_id for p in b.fillers], study.feed,
                           participant_rng(study, pid, "feed"))
    feed = [{"position": k, **entries[post_id]} for k, post_id in enumerate(order)]

    steps: dict[str, dict] = {}
    for step in study.procedure:
        if isinstance(step, ImageRatingStep):
            trials = [{"post_id": e["post_id"], "image_id": e["image_id"]}
                      for e in feed if step.posts == "all" or e["role"] == "critical"]
            participant_rng(study, pid, step.id).shuffle(trials)
            steps[step.id] = {"type": step.type, "trials": trials}
        elif isinstance(step, RecognitionStep):
            steps[step.id] = {"type": step.type, "trials": _recognition_trials(b, step, feed, pid)}

    return {
        "format_version": FORMAT_VERSION,
        "study_id": study.id,
        "study_version": study.version,
        "participant_id": pid,
        "participant_index": a.participant_index,
        "group": a.group,
        "group_key": groups[a.group].key,
        "list": a.list,
        "between": a.between,
        "feed": feed,
        "steps": steps,
    }


def _recognition_trials(b: StudyBundle, step: RecognitionStep, feed: list[dict], pid: str) -> list[dict]:
    rng = participant_rng(b.study, pid, step.id)
    trials = []
    for e in feed:
        if e["role"] != "critical":
            continue
        trials.append({"image_id": e["image_id"], "post_id": e["post_id"], "kind": "old", "answer": "old"})
        if step.lures in ("alternate_version", "both"):
            others = sorted(i.image_id for i in b.versions(e["post_id"]).values() if i.image_id != e["image_id"])
            if others:
                trials.append({"image_id": rng.choice(others), "post_id": e["post_id"],
                               "kind": "alternate", "answer": "new"})
    if step.lures in ("foils", "both"):
        trials += [{"image_id": f, "post_id": None, "kind": "foil", "answer": "new"} for f in step.foils]
    rng.shuffle(trials)
    return trials


# ---------------------------------------------------------------- writing


def load_study(study_dir: Path | str) -> StudyBundle:
    """Like check_study, but raises StudyError instead of returning a report."""
    b, rep = check_study(study_dir)
    if b is None:
        raise StudyError(rep.errors, rep.warnings)
    return b


def compile_study(study_dir: Path | str, out_dir: Path | str | None = None, clean: bool = False) -> tuple[Path, Report]:
    """Check a study and write its package. Raises StudyError if the study has errors.

    ``out_dir`` defaults to build/<study id> in the current directory. An
    existing non-empty output folder is only replaced when ``clean`` is set and
    it looks like an earlier build (contains study.json).
    """
    b, rep = check_study(study_dir)
    if b is None:
        raise StudyError(rep.errors, rep.warnings)
    out = Path(out_dir) if out_dir is not None else Path("build") / b.study.id
    if out.exists() and any(out.iterdir()):
        if not clean:
            raise FileExistsError(f"{out} already exists and is not empty (use clean=True / --clean to replace it)")
        if not (out / "study.json").is_file():
            raise FileExistsError(f"refusing to replace {out}: it does not look like a SocialEyes build")
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)

    plans = build_plans(b)
    _write_json(out / "study.json", _study_manifest(b))
    for plan in plans:
        _write_json(out / "plans" / f"{plan['participant_id']}.json", plan)
    _write_plans_csv(out / "plans.csv", b, plans)

    media = ({a.avatar for a in b.accounts.values()} | {i.file for i in b.images.values()}
             | {s.file for s in b.stories} | {r.file for r in b.reels})
    for rel in sorted(media):
        dest = out / "media" / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(b.root / rel, dest)
    for image_id, aois in b.aois.items():
        _write_json(out / "aois" / f"{image_id}.json", aois.to_json())

    from ..markers import write_tag_png  # needs OpenCV; imported here so checking works without it

    for tag_id in b.study.markers.screen_tag_ids:
        write_tag_png(tag_id, out / "tags" / f"tag36h11_{tag_id}.png")
    return out, rep


def _study_manifest(b: StudyBundle) -> dict:
    study = b.study
    sync = study.display.sync_patch
    return {
        "format": "socialeyes-study",
        "format_version": FORMAT_VERSION,
        "socialeyes_version": __version__,
        "study": study.model_dump(mode="json"),
        "cells": [c.key for c in cells(study.within)],
        "groups": [g.key for g in cells(study.between)],
        "accounts": {
            a.account_id: {"handle": a.handle, "display_name": a.display_name,
                           "avatar": f"media/{a.avatar}", "verified": a.verified}
            for a in b.accounts.values()
        },
        "posts": {p.post_id: {"role": p.role, "account_id": p.account_id} for p in b.posts.values()},
        "images": {
            i.image_id: {
                "file": f"media/{i.file}",
                "post_id": i.post_id or None,
                "version": i.version,
                "width": b.image_sizes[i.image_id][0],
                "height": b.image_sizes[i.image_id][1],
                "aoi": f"aois/{i.image_id}.json" if i.image_id in b.aois else None,
            }
            for i in b.images.values()
        },
        "stories": [
            {
                "story_id": s.story_id,
                "account_id": s.account_id,
                "file": f"media/{s.file}",
                "width": s.width,
                "height": s.height,
                "duration_s": s.duration_s if s.duration_s is not None else study.feed.story_duration_s,
                "posted_ago": s.posted_ago or None,
                "aoi": f"aois/{s.story_id}.json" if s.story_id in b.aois else None,
            }
            for s in b.stories
        ],
        "reels": [
            {
                "reel_id": r.reel_id,
                "account_id": r.account_id,
                "file": f"media/{r.file}",
                "width": r.width,
                "height": r.height,
                "duration_s": r.duration_s,
                "caption": r.caption,
                "like_count": r.like_count,
                "audio": r.audio or None,
                "posted_ago": r.posted_ago or None,
            }
            for r in b.reels
        ],
        "sync_code": {"bits": m_sequence(), "bit_ms": sync.bit_ms},
        "validation_points": {
            s.id: [list(p) for p in validation_points(s.points)]
            for s in study.procedure if isinstance(s, ValidationStep)
        },
        "screen_tags": {str(t): f"tags/tag36h11_{t}.png" for t in study.markers.screen_tag_ids},
    }


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_plans_csv(path: Path, b: StudyBundle, plans: list[dict]) -> None:
    between = [f.name for f in b.study.between]
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["participant_id", "group", "list", *between, "n_posts"])
        for p in plans:
            w.writerow([p["participant_id"], p["group"], p["list"], *[p["between"][f] for f in between], len(p["feed"])])
