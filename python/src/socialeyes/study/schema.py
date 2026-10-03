"""Schema for a researcher-authored study definition (study.yaml).

The study.yaml file sits next to the CSV/media files it references. See
docs/STUDY_DESIGN.md for an annotated walkthrough and studies/example/ for a
working example.
"""
from __future__ import annotations

from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class _Strict(BaseModel):
    # Typos in study.yaml should fail loudly instead of being silently ignored.
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------- platform / display


class Platform(_Strict):
    name: str = "Pictogram"
    """App name drawn in the feed's top bar. Do not use a real platform's trademark."""
    theme: Literal["light", "dark"] = "light"


class SyncPatch(_Strict):
    """A small patch whose grey level follows a pseudorandom code.

    The scene camera sees it, so its logged on/off times can be cross-correlated
    with the scene video to sync clocks to well under one video frame.
    """

    enabled: bool = True
    size_dp: int = Field(16, ge=6, le=64)
    corner: Literal["top_left", "top_right"] = "top_left"
    low: int = Field(20, ge=0, le=255)
    high: int = Field(44, ge=0, le=255)
    bit_ms: int = Field(100, ge=34, le=1000)
    """Duration of one code bit. Keep >= 3 scene-camera frames (100 ms at 30 Hz)."""

    @model_validator(mode="after")
    def _levels(self):
        if self.high <= self.low:
            raise ValueError("sync_patch.high must be greater than sync_patch.low")
        return self


class Display(_Strict):
    viewing_distance_cm: float = Field(35.0, gt=5, lt=200)
    """Nominal distance, used only when it cannot be estimated from the markers."""
    sync_patch: SyncPatch = SyncPatch()


class Markers(_Strict):
    family: Literal["tag36h11"] = "tag36h11"
    screen_tag_ids: list[int] = [0, 1, 2, 3]
    """Tags shown on screen during marker_calibration steps (TL, TR, BR, BL)."""
    case_tag_ids: list[int] = [10, 11, 12, 13, 14, 15]
    """Tags printed on the phone case. Must differ from screen_tag_ids."""
    case_tag_size_mm: float = Field(15.0, gt=3, lt=60)

    @model_validator(mode="after")
    def _disjoint(self):
        if len(self.screen_tag_ids) != 4:
            raise ValueError("markers.screen_tag_ids must list exactly 4 ids (TL, TR, BR, BL)")
        if set(self.screen_tag_ids) & set(self.case_tag_ids):
            raise ValueError("markers.screen_tag_ids and markers.case_tag_ids must not overlap")
        if len(set(self.case_tag_ids)) != len(self.case_tag_ids):
            raise ValueError("markers.case_tag_ids contains duplicates")
        return self


class Neon(_Strict):
    required: bool = False
    """If true, the app refuses to start a session without a Neon connection."""
    auto_record: bool = True
    """Start/stop the Neon recording from the app so the two recordings always pair up."""
    sync_interval_s: float = Field(2.0, ge=0.5, le=30)


# ---------------------------------------------------------------- content


class Label(_Strict):
    text: str
    style: Literal["banner", "caption"] = "banner"


class Factor(_Strict):
    name: str
    design: Literal["within", "between"]
    levels: list[str]
    applies_to: Literal["critical", "all"] = "critical"
    sets: dict[str, Union[str, dict[str, Optional[str]]]]
    """Which post attribute(s) this factor controls.

    Each value is either a template string ("{level}" is replaced by the level) or
    a mapping from level to value (null = attribute unset, e.g. no label).
    """

    @field_validator("name")
    @classmethod
    def _ident(cls, v: str) -> str:
        if not v.isidentifier():
            raise ValueError(f"factor name {v!r} must be a simple identifier (letters, digits, _)")
        return v

    @field_validator("levels")
    @classmethod
    def _levels(cls, v: list[str]) -> list[str]:
        if len(v) < 2:
            raise ValueError("a factor needs at least 2 levels")
        if len(set(v)) != len(v):
            raise ValueError("factor levels must be unique")
        return v

    @field_validator("sets")
    @classmethod
    def _sets(cls, v):
        allowed = {"image_version", "comment_variant", "label", "like_count", "caption_variant"}
        bad = set(v) - allowed
        if bad:
            raise ValueError(f"factor can only set {sorted(allowed)}; got {sorted(bad)}")
        if not v:
            raise ValueError("factor.sets must not be empty")
        return v

    def value_for(self, attribute: str, level: str) -> Optional[str]:
        spec = self.sets[attribute]
        if isinstance(spec, str):
            return spec.replace("{level}", level)
        if level not in spec:
            raise ValueError(f"factor {self.name}: sets.{attribute} has no entry for level {level!r}")
        return spec[level]


class Feed(_Strict):
    order: Literal["shuffle", "fixed"] = "shuffle"
    lead_in_fillers: int = Field(2, ge=0)
    """Number of filler posts forced to the top of the feed (warm-up)."""
    max_run_same_cell: int = Field(2, ge=1)
    """Max consecutive critical posts sharing a within-subject cell."""
    min_fillers_between_critical: int = Field(0, ge=0)
    time_limit_s: Optional[float] = Field(None, gt=0)
    done_button_after_s: Optional[float] = Field(60, ge=0)
    """Show an 'I'm done' button after this many seconds (null = never)."""
    allow_comment_typing: bool = False
    allow_likes: bool = True
    allow_saves: bool = True
    """Bookmark button saves/unsaves the post."""
    allow_shares: bool = True
    """Send button shows "Sent" (nothing is actually sent)."""
    allow_comment_likes: bool = True
    """Comments can be liked in the comments sheet."""


# ---------------------------------------------------------------- procedure steps


class QItem(_Strict):
    id: str
    kind: Literal["vas", "likert", "choice", "text", "number"]
    text: str
    required: bool = True
    min_label: Optional[str] = None
    max_label: Optional[str] = None
    points: Optional[int] = Field(None, ge=2, le=11)
    labels: Optional[list[str]] = None
    options: Optional[list[str]] = None

    @model_validator(mode="after")
    def _kind(self):
        if self.kind == "likert" and not self.points:
            raise ValueError(f"item {self.id}: likert needs 'points'")
        if self.kind == "likert" and self.labels and len(self.labels) != self.points:
            raise ValueError(f"item {self.id}: likert labels must have length == points")
        if self.kind == "choice" and not self.options:
            raise ValueError(f"item {self.id}: choice needs 'options'")
        return self


class _Step(_Strict):
    id: str


class InstructionsStep(_Step):
    type: Literal["instructions"]
    title: str = ""
    text: str
    button: str = "Continue"
    min_time_s: float = 0


class MarkerCalibrationStep(_Step):
    type: Literal["marker_calibration"]
    duration_s: float = Field(4.0, ge=1.0, le=30)
    """Show on-screen tags + a full-screen sync flash code for this long."""


class CameraCheckStep(_Step):
    """Researcher-run framing check for the front camera.

    The participant never sees their own video (seeing yourself before a
    body-image task is itself a manipulation): the screen only shows a framing
    guide and whether a face is detected.
    """

    type: Literal["camera_check"]
    min_face_s: float = Field(3.0, ge=0.5, le=30)
    """Continue unlocks once a face has been detected continuously this long."""
    instructions: str = "Hold the phone as you normally would and look at the screen."


class ValidationStep(_Step):
    type: Literal["validation"]
    points: Literal[5, 9, 13] = 9
    target_dp: int = Field(28, ge=12, le=80)
    instructions: str = "Look at each dot and tap it."


class QuestionnaireStep(_Step):
    type: Literal["questionnaire"]
    title: str = ""
    items: list[QItem]
    randomize: bool = False


class FeedStep(_Step):
    type: Literal["feed"]
    instructions: str = ""


class ImageRatingStep(_Step):
    type: Literal["image_rating"]
    title: str = ""
    posts: Literal["critical", "all"] = "critical"
    items: list[QItem]


class RecognitionStep(_Step):
    type: Literal["recognition"]
    question: str = "Did you see exactly this image in the feed?"
    lures: Literal["foils", "alternate_version", "both"] = "both"
    foils: list[str] = []
    """image_ids of never-shown images used as 'new' trials."""
    confidence: bool = True


class EndStep(_Step):
    type: Literal["end"]
    text: str = "Thank you! Please hand the phone back to the researcher."


Step = Annotated[
    Union[
        InstructionsStep,
        MarkerCalibrationStep,
        CameraCheckStep,
        ValidationStep,
        QuestionnaireStep,
        FeedStep,
        ImageRatingStep,
        RecognitionStep,
        EndStep,
    ],
    Field(discriminator="type"),
]


class FrontCamera(_Strict):
    """Video of the participant's face from the phone's front camera.

    Consent and anonymisation are handled by the researcher; the app records
    whenever this is enabled. Android shows a camera indicator while recording,
    which may make participants more self-aware; pilot with and without it.
    """

    enabled: bool = False
    resolution: Literal["480p", "720p", "1080p"] = "720p"
    """720p is the practical minimum for facial-expression analysis."""
    fps: Literal[15, 24, 30] = 30
    bitrate_mbps: float = Field(3.0, ge=0.5, le=20)
    steps: Union[Literal["all"], list[str]] = ["feed"]
    """Procedure step ids to record, or "all"."""
    segment_s: int = Field(60, ge=10, le=600)
    """Video is cut into files of this length so a crash loses at most one segment."""


class Logging(_Strict):
    """What the app records besides gaze. See docs/EVENT_LOG.md for the file format.

    The viewport log (where each post is on screen), UI interactions, responses
    and session-quality events are always recorded: gaze mapping and data
    quality checks depend on them.
    """

    touches: bool = True
    """Raw touch points (down/move/up). Needed for gesture and finger-occlusion
    analysis."""
    sensors: bool = False
    """Phone accelerometer, gyroscope and rotation vector."""
    sensor_hz: int = Field(50, ge=5, le=200)
    screen_recording: bool = False
    """Record the phone screen (pilots / validating the gaze mapping). Android asks
    for permission every session and it costs performance; keep off for real data."""
    screen_recording_fps: int = Field(30, ge=5, le=60)
    front_camera: FrontCamera = FrontCamera()

    @model_validator(mode="after")
    def _one_encoder(self):
        if self.front_camera.enabled and self.screen_recording:
            raise ValueError("logging: front_camera and screen_recording cannot both be enabled "
                             "(two video encoders at once make the feed stutter on most phones)")
        return self


class Participants(_Strict):
    n_plans: int = Field(120, ge=1, le=5000)
    id_prefix: str = "P"
    id_digits: int = Field(3, ge=1, le=6)


class Study(_Strict):
    id: str
    title: str = ""
    version: int = 1
    seed: int = 1
    platform: Platform = Platform()
    display: Display = Display()
    markers: Markers = Markers()
    neon: Neon = Neon()
    logging: Logging = Logging()

    accounts: str = "accounts.csv"
    images: str = "images.csv"
    posts: str = "posts.csv"
    comments: str = "comments.csv"
    """Optional: a missing file means no post has comments."""
    captions: str = "captions.csv"
    """Optional: only needed when a factor sets caption_variant."""
    labels: dict[str, Label] = {}
    factors: list[Factor] = []
    feed: Feed = Feed()
    procedure: list[Step]
    participants: Participants = Participants()

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not v.replace("-", "_").isidentifier():
            raise ValueError("study id must contain only letters, digits, '-' and '_'")
        return v

    @model_validator(mode="after")
    def _checks(self):
        names = [f.name for f in self.factors]
        if len(set(names)) != len(names):
            raise ValueError("factor names must be unique")
        owner: dict[str, str] = {}
        for f in self.factors:
            for attr in f.sets:
                if attr in owner:
                    raise ValueError(f"post attribute {attr!r} is set by both {owner[attr]!r} and {f.name!r}")
                owner[attr] = f.name
        ids = [s.id for s in self.procedure]
        if len(set(ids)) != len(ids):
            raise ValueError("procedure step ids must be unique")
        if sum(s.type == "feed" for s in self.procedure) != 1:
            raise ValueError("procedure must contain exactly one feed step")
        if self.procedure[-1].type != "end":
            raise ValueError("the last procedure step must be type: end")
        cam = self.logging.front_camera
        if isinstance(cam.steps, list):
            unknown = [s for s in cam.steps if s not in ids]
            if unknown:
                raise ValueError(f"logging.front_camera.steps: unknown procedure step id(s) {unknown}")
        return self

    @property
    def within(self) -> list[Factor]:
        return [f for f in self.factors if f.design == "within"]

    @property
    def between(self) -> list[Factor]:
        return [f for f in self.factors if f.design == "between"]
