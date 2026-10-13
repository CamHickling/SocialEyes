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
    participant_handle: str = Field("you", min_length=1, max_length=30)
    """Name the participant's own comments and replies appear under."""


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
    brightness: Optional[float] = Field(None, ge=0.05, le=1.0)
    """Screen brightness for the whole session (0-1, the app's window brightness; the phone's
    own setting is left alone). Unset: the phone's setting. A display_calibration step
    overrides it for the rest of the session."""


class OnScreenTags(_Strict):
    """Screen tags kept on screen during whole steps (e.g. the feed), for when nothing can be
    fixed around the phone. Two tags in a band above the step and two below it; the step's own
    content gets the space in between. Their positions are logged in a `marker_layout` event."""

    steps: list[str] = []
    """Procedure step ids that show them. Empty = off."""
    size_mm: float = Field(12.0, ge=4, le=20)
    """Black-border edge length on the screen. 9 mm was at the Neon scene camera's detection limit
    with the phone held low (CAM-210), so 12 mm by default."""


class Markers(_Strict):
    family: Literal["tag36h11"] = "tag36h11"
    screen_tag_ids: list[int] = [0, 1, 2, 3]
    """Tags shown on screen during marker_calibration steps (TL, TR, BR, BL)."""
    case_tag_ids: list[int] = [10, 11, 12, 13, 14, 15]
    """Tags printed on the phone case. Must differ from screen_tag_ids."""
    case_tag_size_mm: float = Field(15.0, gt=3, lt=60)
    on_screen: OnScreenTags = OnScreenTags()

    @model_validator(mode="after")
    def _disjoint(self):
        if len(self.screen_tag_ids) != 4:
            raise ValueError("markers.screen_tag_ids must list exactly 4 ids (TL, TR, BR, BL)")
        if set(self.screen_tag_ids) & set(self.case_tag_ids):
            raise ValueError("markers.screen_tag_ids and markers.case_tag_ids must not overlap")
        if len(set(self.case_tag_ids)) != len(self.case_tag_ids):
            raise ValueError("markers.case_tag_ids contains duplicates")
        return self


class SceneExposure(_Strict):
    """Neon scene camera exposure, set through Companion's real-time API at session start and put
    back as it was at the end (the phone and glasses are shared). The default auto exposure
    meters the room, which blows out the bright phone screen (CAM-165)."""

    mode: Literal["auto", "manual"] = "manual"
    exposure_us: Optional[int] = Field(None, ge=1, le=1_000_000)
    """Manual exposure time in microseconds (manual only; Companion reports the allowed range)."""
    gain: Optional[int] = Field(None, ge=0)
    brightness: Optional[int] = None
    """In auto mode, shifts the auto exposure's target brightness (lower = darker)."""

    @model_validator(mode="after")
    def _check(self):
        if self.mode == "manual" and self.exposure_us is None:
            raise ValueError("neon.scene_exposure: mode manual needs exposure_us")
        if self.mode == "auto" and (self.exposure_us is not None or self.gain is not None):
            raise ValueError("neon.scene_exposure: exposure_us and gain only apply to mode manual")
        return self


NEON_TEMPLATE_FIELDS = ("participant_id", "study_id", "study_version")

DEFAULT_NEON_CHECKLIST = [
    "Companion's wearer is the SocialEyes profile (no gaze offset correction)",
    "The glasses sit snugly and the participant can see the whole phone screen",
    "The phone screen is clean, at the study's brightness, and not facing a window or lamp",
    "Companion's scene camera auto exposure is set to Highlights (the API can't set it)",
]


class Neon(_Strict):
    required: bool = False
    """If true, the app refuses to start a session without a Neon connection."""
    auto_record: bool = True
    """Start/stop the Neon recording from the app so the two recordings always pair up. The
    settings below are applied at that point, so they need auto_record."""
    sync_interval_s: float = Field(2.0, ge=0.5, le=30)
    scene_exposure: Optional[SceneExposure] = None
    """Scene camera exposure for the session; unset leaves Companion's setting alone."""
    template: dict[str, str] = Field(default_factory=dict)
    """Companion recording template fields to fill, by the field's title (case-insensitive), e.g.
    {Participant: "{participant_id}"}. Values may use {participant_id}, {study_id}, {study_version}."""
    checklist: list[str] = Field(default_factory=lambda: list(DEFAULT_NEON_CHECKLIST))
    """What the researcher confirms before the recording starts (things the API can't set). The
    answers are logged; [] skips the checklist."""

    @field_validator("template")
    @classmethod
    def _template_fields(cls, v: dict[str, str]) -> dict[str, str]:
        import string
        for title, value in v.items():
            for _, name, _, _ in string.Formatter().parse(value):
                if name is not None and name not in NEON_TEMPLATE_FIELDS:
                    raise ValueError(f"neon.template.{title}: unknown field {{{name}}} "
                                     f"(use {', '.join('{' + f + '}' for f in NEON_TEMPLATE_FIELDS)})")
        return v

    @model_validator(mode="after")
    def _needs_auto_record(self):
        if not self.auto_record and (self.scene_exposure or self.template):
            raise ValueError("neon.scene_exposure and neon.template are applied when the app starts the "
                             "recording, so they need neon.auto_record")
        return self


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
    """Participants can write comments and replies. The final text and every edit
    of the draft are logged (comment_submit / comment_edit); keystrokes are not."""
    allow_likes: bool = True
    allow_saves: bool = True
    """Bookmark button saves/unsaves the post."""
    allow_shares: bool = True
    """Send button shows "Sent" (nothing is actually sent)."""
    allow_comment_likes: bool = True
    """Comments can be liked in the comments sheet."""
    story_duration_s: float = Field(5.0, gt=0, le=60)
    """How long each story shows before moving on; stories.csv can override it per story."""


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


class TagLadderStep(_Step):
    """Which on-screen tag size and edge clearances the Neon scene camera can read (CAM-165).

    For each hold (a way of holding the phone, given as an instruction) the screen shows, for
    `hold_s` seconds on white: four tags of `sizes_mm` down the middle; `reference_mm` tags at
    the left and right edges, their black border `side_insets_mm` from the edge; and two
    `reference_mm` tags at the top and at the bottom edge, `edge_gaps_mm` from it. The order
    flips every `flip_every_s` so that no size or inset always sits at the same height. Every
    arrangement is logged in a `marker_layout` event (with `ladder`: what each tag tests);
    socialeyes.gaze.ladder gives the detection rate of each.
    """

    type: Literal["tag_ladder"]
    holds: list[str] = Field(default_factory=lambda: [
        "Hold the phone the way you normally would.",
        "Hold the phone a little further away, near arm's length.",
        "Rest the phone low, near your lap, and look down at it.",
    ], min_length=1, max_length=8)
    hold_s: float = Field(20.0, ge=5, le=120)
    flip_every_s: float = Field(5.0, ge=1, le=60)
    sizes_mm: list[float] = Field([8.0, 10.0, 12.0, 14.0], min_length=4, max_length=4)
    side_insets_mm: list[float] = Field([3.0, 4.0, 5.0, 6.0], min_length=4, max_length=4)
    edge_gaps_mm: list[float] = Field([1.5, 3.5], min_length=2, max_length=2)
    reference_mm: float = Field(12.0, ge=6, le=14)
    """Size of the edge tags."""
    first_tag_id: int = Field(20, ge=0, le=571)
    """The step uses 16 tag ids from here: sizes, left insets, right insets, top gaps, bottom gaps."""

    @model_validator(mode="after")
    def _ranges(self):
        if not all(4 <= s <= 16 for s in self.sizes_mm):
            raise ValueError(f"step {self.id}: sizes_mm must be 4-16 mm")
        if not all(0 <= s <= 12 for s in self.side_insets_mm + self.edge_gaps_mm):
            raise ValueError(f"step {self.id}: side_insets_mm and edge_gaps_mm must be 0-12 mm")
        return self

    @property
    def tag_ids(self) -> list[int]:
        return list(range(self.first_tag_id, self.first_tag_id + 16))


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


class ProfilePhotoStep(_Step):
    """The participant may take a selfie with the front camera as their profile picture.

    It replaces the default avatar wherever the participant appears (their story,
    the profile tab, their comments). The photo is kept only in the app's memory
    and deleted when the session ends; the log records only whether one was taken.
    Note that seeing one's own face can itself affect body-image measures.
    """

    type: Literal["profile_photo"]
    text: str = "Take a photo for your profile picture. It is only used during this session and is deleted afterwards."
    allow_skip: bool = True


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


class DisplayCalibrationStep(_Step):
    """Finds the screen brightness and Neon scene camera exposure at which the scene camera
    reads the on-screen tags best without blowing out the screen (CAM-165). The phone shows the
    session's on-screen tags around a post image; a laptop running `socialeyes calibrate-display`
    watches Companion's scene video, steps through brightness x exposure via a small server the
    app runs on `port` during this step, and sends back the best setting, which the app keeps for
    the rest of the session (the scene camera is put back at the end). Needs the Neon recording
    (neon.auto_record). Without a laptop within `wait_s`, the researcher can skip it."""

    type: Literal["display_calibration"]
    text: str = "Hold the phone as you normally would and keep looking at the screen. This takes about half a minute."
    port: int = Field(8091, ge=1024, le=65535)
    wait_s: float = Field(60.0, ge=5, le=600)
    """How long to wait for the laptop before offering Skip."""


class EndStep(_Step):
    type: Literal["end"]
    text: str = "Thank you! Please hand the phone back to the researcher."


Step = Annotated[
    Union[
        InstructionsStep,
        MarkerCalibrationStep,
        TagLadderStep,
        DisplayCalibrationStep,
        CameraCheckStep,
        ProfilePhotoStep,
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
    stories: str = "stories.csv"
    reels: str = "reels.csv"
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
        unknown = [s for s in self.markers.on_screen.steps if s not in ids]
        if unknown:
            raise ValueError(f"markers.on_screen.steps: unknown procedure step id(s) {unknown}")
        taken = set(self.markers.screen_tag_ids) | set(self.markers.case_tag_ids)
        for s in self.procedure:
            if isinstance(s, TagLadderStep) and taken & set(s.tag_ids):
                raise ValueError(f"step {s.id}: tag ids {s.tag_ids[0]}-{s.tag_ids[-1]} overlap the screen or case "
                                 f"tags; set first_tag_id")
            if isinstance(s, DisplayCalibrationStep) and not self.neon.auto_record:
                raise ValueError(f"step {s.id}: display_calibration sets the Neon scene camera, so it needs "
                                 "neon.auto_record")
        return self

    @property
    def ladder_tag_ids(self) -> list[int]:
        return sorted({t for s in self.procedure if isinstance(s, TagLadderStep) for t in s.tag_ids})

    @property
    def within(self) -> list[Factor]:
        return [f for f in self.factors if f.design == "within"]

    @property
    def between(self) -> list[Factor]:
        return [f for f in self.factors if f.design == "between"]
