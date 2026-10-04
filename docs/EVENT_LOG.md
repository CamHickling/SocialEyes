# Session log format

> [!NOTE]
> **Draft (format version 1).** This is the contract between the Pictogram app
> (which writes these files) and the Python analysis (`socialeyes.session`,
> which reads them). The app (`android/`) writes session.json, events.jsonl,
> viewport.csv, touch.csv, video.csv, sensors.csv and the front camera files;
> screen recording is not built yet. `socialeyes.session.simulate` writes realistic fake
> sessions in this format.

One folder per session:

```
data/<study id>/<participant id>/<session uid>/
  session.json     device, clocks, settings; written at start, completed at end
  events.jsonl     everything that happens: steps, interactions, responses, app state
  viewport.csv     where each post (and its parts) is on screen, per drawn frame
  touch.csv        raw touch points                    (logging.touches)
  sensors.csv      accelerometer / gyroscope / rotation (logging.sensors)
  screen.mp4       screen recording                    (logging.screen_recording)
  camera/front_000.mp4, front_001.mp4, ...   front camera video   (logging.front_camera)
  camera_frames.csv   one timestamp per front camera frame      (logging.front_camera)
```

The app writes all files **while the session runs** and flushes at least once
per second, so a crash loses at most a second of data. A `session.json` without
`end` means the session did not finish normally.

## Clocks and timestamps

Every row has `t_ns`: Android's `SystemClock.elapsedRealtimeNanos()`. This
clock is monotonic and keeps counting during deep sleep.

Android uses other time bases internally, and the app must convert them before
writing:

- `MotionEvent` times and `Choreographer` frame times are on the
  `uptimeMillis` / `System.nanoTime()` base, which **stops during deep sleep**.
  Convert with `t_ns = t_uptime_ns + (elapsedRealtimeNanos() - nanoTime())`,
  sampling the offset when the event is handled.
- Write each historical sample in a batched `MotionEvent` as its own row,
  each with its own time.

`session.json` holds a `clock` snapshot (all bases read back-to-back) at the
start and at the end. If the offset between `elapsed_ns` and `uptime_ns`
changes between the two, the phone slept during the session, which the
quality check flags.

## Coordinates

All x/y values are **physical screen pixels**, origin top-left of the display
in its current rotation (`MotionEvent.getRawX/Y`, `View.getLocationOnScreen`).
Rectangles are `left, top, right, bottom` and are **not clipped** to the
screen. A post half scrolled off the top has a negative `top`. This is what lets
the analysis map a screen point to exact image pixels.

## session.json

```json
{
  "format": "socialeyes-session",
  "format_version": 1,
  "study_id": "example",
  "study_version": 1,
  "participant_id": "P001",
  "session_uid": "P001-20261002T101500",
  "app_version": "0.1.0",
  "started_wall": "2026-10-02T10:15:00.123+02:00",
  "clock": {"elapsed_ns": 81234567890123, "uptime_ns": 80234567890123, "wall_ms": 1790000000123},
  "device": {
    "manufacturer": "Google", "model": "Pixel 8", "android_sdk": 34,
    "screen_width_px": 1080, "screen_height_px": 2400,
    "density_dpi": 420, "xdpi": 428.6, "ydpi": 427.3, "refresh_hz": 60.0, "font_scale": 1.0
  },
  "feed_area": [0, 210, 1080, 2400],
  "logging": {"touches": true, "sensors": false, "sensor_hz": 50,
              "screen_recording": false, "screen_recording_fps": 30,
              "front_camera": {"enabled": false}},
  "camera": {"lens": "front", "width": 1024, "height": 768, "fps": 30, "timestamp_source": "realtime", "orientation": 270},
  "end": {"reason": "completed", "clock": {"elapsed_ns": 0, "uptime_ns": 0, "wall_ms": 0}}
}
```

`logging` is a copy of the study's `logging:` section. `camera` (only when
recording the front camera) gives the resolution
and frame rate actually achieved, which can differ from what was requested, the
camera's timestamp source (see Front camera) and the sensor orientation in degrees
(the MP4s carry it as a rotation flag, so players show them upright).

`sync_patch` is the sync patch's screen rectangle `[left, top, right, bottom]`
(absent when the patch is disabled).

`feed_area` is the screen rectangle the feed scrolls in (below the status and
app bars), used to decide how much of a post is visible. `end.reason` is
`completed` or `aborted` (the researcher stopped the session).

## events.jsonl

One JSON object per line. Each has `t_ns` and `type`; the other fields depend on
the type. Unknown types must be ignored by readers, so the app can add new ones.

**Procedure**

| type | fields | when |
|---|---|---|
| `step_start` | `step_id`, `step_type` | a procedure step is shown |
| `step_end` | `step_id`, `reason` (`continue`, `done_button`, `time_limit`) | it is left |
| `trial_start` | `step_id`, `trial` (0-based), `image_id` | image_rating / recognition trial shown |
| `items_shown` | `step_id`, `item_ids` (in display order), optional `trial` | a page of questionnaire / rating items appears |
| `response` | `step_id`, `item_id`, `value`, `rt_ms`, optional `trial` | final answer when the participant moves on; `rt_ms` = page shown to the item's last change |
| `response_change` | `step_id`, `item_id`, `value`, optional `trial` | every change before that: taps, and the end of each VAS drag (the drag path is in touch.csv). Typing in text and number items is not logged |
| | | recognition trials use the item ids `old_new` (`old` / `new`, compare with the plan's `answer`) and `confidence` (1-4) |
| `validation_target` | `step_id`, `index`, `x_px`, `y_px` | validation dot shown |
| `validation_tap` | `step_id`, `index`, `x_px`, `y_px`, `on_target` | every tap while a dot is shown; only an `on_target` tap (within 1.5 dot diameters) moves to the next dot |
| `done_button_shown` | | the feed's "I'm done" button appears |
| `feed_start` | | the feed is shown, after the feed step's `instructions` (only when it has instructions) |
| `marker_layout` | `step_id`, `tags` (`{"<tag id>": [left, top, right, bottom]}`) | end of a marker_calibration step: where each screen tag was |

**Feed interactions**

| type | fields |
|---|---|
| `like` | `post_id`, `liked` (true/false), `via` (`button` or `double_tap`) |
| `comments_open` / `comments_close` | `post_id` (the comments sheet; posts show their first 2 comments inline) |
| `comments_sheet` | `post_id`, `state` (`half` or `full`): the sheet came to rest at half height or full screen |
| `comment_like` | `post_id`, `comment` (0-based position in the post's comments, or `p1`, `p2`, … for the participant's own), `liked` (true/false) |
| `save` | `post_id`, `saved` (true/false): the bookmark button (`feed.allow_saves`) |
| `share` | `post_id`: the send button; the app only shows "Sent" (`feed.allow_shares`) |
| `home_tap` | the Home tab was tapped; the feed scrolls back to the top (with Reels open, it closes Reels) |
| `story_open` | `account_id`: a story circle was tapped |
| `story_start` | `story_id`, `account_id`: a story appears |
| `story_end` | `story_id`, `account_id`, `reason` (`auto`, `tap_forward`, `tap_back`, `swipe_next`, `swipe_back`, `swipe_down`, `close_button`, `back`), `shown_ms`, `paused_ms` (time held down or dragging) |
| `story_swipe` | `story_id`, `direction` (`next` or `previous` account), `max_fraction` (how far it was dragged, 0-1 of the screen width), `completed` (false: a "peek" that snapped back) |
| `story_close` | `reason`: the story viewer closed (after the last story, or as in `story_end`) |
| `story_like` | `story_id`, `liked` (true/false): the heart in the story's reply bar (`feed.allow_likes`) |
| `story_share` | `story_id`: the paper plane; the app only shows "Sent" (`feed.allow_shares`) |
| `story_reply` | `story_id`, `text`, `typing_ms`: a message sent from the reply box (`feed.allow_comment_typing`); the story is paused while typing |
| `story_reply_edit` | `story_id`, `text` (the whole draft after the change): every change of the reply draft, like `comment_edit` |
| `reels_open` / `reels_close` | the Reels tab was opened / left (`reason`: `home_tab`, `back`) |
| `reel_start` | `reel_id`, `account_id`: a reel starts playing |
| `reel_end` | `reel_id`, `reason` (`swipe`, `closed`, `back`), `watched_ms`, `loops` (times it restarted) |
| `reel_like` | `reel_id`, `liked`, `via` (`button` or `double_tap`) (`feed.allow_likes`) |
| `reel_share` | `reel_id`: the send button; the app only shows "Sent" (`feed.allow_shares`) |
| `reel_mute` | `reel_id`, `muted` (true/false): reels start muted, a tap toggles the sound |
| `reel_pause` / `reel_resume` | `reel_id`, `position_ms`: the participant held the reel to pause it |
| `caption_expand` | `post_id` |
| `profile_tap` | `post_id`, `target` (`handle` or `avatar`) |
| `label_tap` | `post_id` |
| `image_tap` | `post_id` (a single tap on the image that did nothing else) |
| `comment_submit` | `post_id`, `comment_id` (`p1`, `p2`, … numbered across the session), `text`, `reply_to` (the comment answered: a position, a `p` id, or null for a new comment), `typing_ms` (first change of the draft to posting). Only with `feed.allow_comment_typing` |
| `comment_edit` | `post_id`, `text` (the whole draft after the change), `reply_to`: every change of the comment draft. Android keyboards report each typed character as a change, so this is close to a keystroke record of the text (key presses themselves, on the keyboard, are not logged) |

**Sync and eye tracker**

| type | fields |
|---|---|
| `sync_patch` | `level` (0/1): every change of the sync patch |
| `neon` | `status` (`connected`, `disconnected`, `recording_start`, `recording_stop`), optional `recording_id` |

**Session quality**

| type | fields |
|---|---|
| `app_state` | `state` (`background` or `foreground`) |
| `interruption` | `kind`, `phase` (`start` or `end`). Kinds: `notification` (a notification sound played; silent ones can't be seen), `call` (ringing or in a call), `alarm` (an alarm or timer sounding), `focus_lost` (something covered the app while it stayed on screen: notification shade, system dialog, power menu). Leaving the app is logged as `app_state` instead |
| `dnd` | `filter`: Do Not Disturb, `off`, `priority`, `alarms` or `total_silence`; at start and on every change |
| `orientation` | `rotation` (0, 90, 180, 270) |
| `brightness` | `value` (0-1); at start and on every change |
| `jank` | `frames_dropped`, `longest_frame_ms`: at most once per second, only when frames were dropped |
| `battery` | `level` (0-1), `temp_c`: once per minute |
| `screen_recording` | `status` (`started`, `stopped`), `file` |
| `thermal` | `status` (`none`, `light`, `moderate`, `severe`, `critical`, `emergency`, `shutdown`; Android's `PowerManager` thermal status): at start and on every change |
| `camera` | `status` (`started`, `segment`, `stopped`, `error`), `file` (on `started`/`segment`), `message` (on `error`) |
| `camera_check` | `step_id`, `result` (`ok` or `failed`), `face_s` (seconds until a face was held in view) |
| `profile_photo` | `step_id`, `result` (`taken`, `skipped` or `camera_unavailable`), `retakes`: end of a profile_photo step. The photo itself is never stored |

## viewport.csv

Written for every frame in which the feed layout **changed** (scrolling,
comments opening, ...). Readers carry the last frame forward until the next one.
Each logged frame is one `frame` row followed by one row per visible element.

| column | meaning |
|---|---|
| `t_ns` | frame time (converted, see Clocks) |
| `frame` | frame counter |
| `scroll_y` | feed scroll offset in px (on `frame` rows) |
| `post_id` | blank on `frame` rows |
| `element` | `frame`, `post` (the whole card), `header`, `image`, `label`, `actions`, `caption`, `comments`; while the comments sheet is open also `sheet`, `sheet_input` (the comment box, with `feed.allow_comment_typing`) and `sheet_comment_<n>` (comment n of the post, 0-based) or `sheet_comment_p<k>` (the participant's own comment or reply pK); while a story is open also `story` (the story image; `post_id` holds the `story_id`); while Reels is open also `reel` (the video; `post_id` holds the `reel_id`; two while swiping between reels) |
| `left`, `top`, `right`, `bottom` | element rectangle, screen px, unclipped (blank on `frame` rows) |

When the feed step ends, the app writes one final `frame` row with no elements.

While the comments sheet is open, its rows carry the `post_id` of the post whose
comments it shows. The sheet lies on top of the feed: the analysis maps a point on
it to the sheet (or the comment under it) rather than to the post below, and counts
feed elements as visible only above the sheet's top edge. `sheet_comment_<n>` rows
are written only while that comment is in the sheet's visible area. An open story
covers the whole screen: while a `story` row is present, feed elements do not count
as visible. While a story is swiped sideways two `story` rows can be present (the
current and the peeked story). During the swipe the stories turn like the faces of a
cube, so their rectangles (and gaze mapped onto them) are approximate until the
`story_swipe` event; exclude those moments if exact image positions matter.
A post is "visible" if any part of its `post` rectangle is on screen.

## touch.csv

| column | meaning |
|---|---|
| `t_ns` | sample time |
| `action` | `down`, `move`, `up`, `cancel` (`down`/`up` for every finger, including second fingers) |
| `pointer_id` | finger id, stable from down to up |
| `x_px`, `y_px` | position, screen px |
| `pressure`, `size` | as reported by Android (device-specific; blank if unavailable) |
| `major_px`, `minor_px` | contact ellipse axes (blank if unavailable) |
| `step_id` | procedure step on screen |

## video.csv

Written only when reels are watched: one row per drawn frame while a reel is on
screen. With the `reel` rectangle in viewport.csv, this maps gaze to a video frame.
The Reels screen covers the feed: while a `reel` row is present, feed elements do
not count as visible.

| column | meaning |
|---|---|
| `t_ns` | frame time (see Clocks) |
| `reel_id` | the reel playing |
| `position_ms` | playback position in the video |
| `playing` | 1 if playing, 0 if paused or still loading |

## sensors.csv

| column | meaning |
|---|---|
| `t_ns` | sample time (`SensorEvent.timestamp`, on the elapsed clock; converted on the few phones that use the `nanoTime` base) |
| `sensor` | `accel` (m/s², incl. gravity), `gyro` (rad/s), `rotation` (unit quaternion from the game rotation vector: no magnetometer, so heading drifts slowly instead of jumping) |
| `x`, `y`, `z` | values in device axes |
| `w` | quaternion w (`rotation` only) |

Only with `logging.sensors`, at `logging.sensor_hz` (Android may deliver slightly
faster). session.json `sensors` lists the sensors the phone has (`hz` and each
sensor's hardware name); a sensor the phone lacks is left out. Android may stop
delivering samples while the app is in the background.

## Front camera

Optional (`logging.front_camera`), meant for facial-expression analysis. The
camera records only during the steps listed in `logging.front_camera.steps`
(default: the feed). Consent and anonymisation of the video are handled by the
researcher under their ethics approval; the app records whenever the study
enables the camera.

**Recording.** The app uses Camera2 feeding a hardware `MediaCodec` encoder:
H.264, the configured frame rate and bitrate, no audio. No preview is shown to the
participant at any time. `resolution` picks the size whose short side is closest,
among sizes with the sensor's own aspect ratio (usually 4:3), so the whole field of
view is kept: `720p` gives 1024x768 on the Pixel 3. Next to the encoder the camera
also fills a small hidden preview-type stream that is thrown away; some drivers
(the Pixel 3's) drop every video frame without one.

**Segments.** A new file starts every `segment_s` seconds and at every
recording start: `camera/front_000.mp4`, `front_001.mp4`, ..., numbered across
the whole session. An MP4 is unreadable if the app dies before closing it, so
segments limit what a crash can destroy. A `camera` event marks each start,
new segment and stop. When the app goes to the background, Android takes the
camera away: the file is closed (`stopped`), and recording resumes in a new
segment when the app returns.

**Timing.** The front camera cannot see the sync patch, so video timing comes
from the camera's own per-frame timestamps. For every encoded frame the app
writes one row to `camera_frames.csv`:

| column | meaning |
|---|---|
| `segment` | segment number (matches the file name) |
| `frame` | frame index within the segment file (0-based, matches the video's frame order) |
| `t_ns` | `CaptureResult.SENSOR_TIMESTAMP`, start of exposure, on the elapsed clock |
| `exposure_ns` | `CaptureResult.SENSOR_EXPOSURE_TIME` (blank if unavailable) |

If the camera reports `SENSOR_INFO_TIMESTAMP_SOURCE = REALTIME`, its timestamps
are already on the elapsed clock. If it reports `UNKNOWN`, they are on the
`nanoTime` base and are converted like touch times (see Clocks). The source is
written to `camera.timestamp_source` (`realtime` or `unknown`). Android shifts the
timestamps the encoder sees onto the monotonic clock, so the app matches every
encoded frame to its capture result (within 1 ms) and writes that result's exact
timestamp and exposure.

**Framing check.** The `camera_check` procedure step is run by the researcher.
The screen shows a framing guide and a face-detected indicator, **never the
video itself**: seeing your own image right before a body-image task would be a
manipulation in its own right. Continue unlocks after a face has been detected
continuously for `min_face_s` seconds; after 15 s "Continue without face" lets the
session go on anyway, and the `camera_check` event records `failed`.

**Performance.** The app logs `thermal` events whatever the settings. Expect
the phone to warm up over long sessions; pilot sessions should check the
`jank` and `thermal` events. Front camera and screen recording cannot both be
enabled.

**Checks.** `socialeyes session` reports, under `camera` in `quality.json`:
every segment's frame count against `camera_frames.csv`, dropped frames
(timestamp gaps), the frame rate achieved, and how much of each recorded step
was covered.

## What the analysis derives

`socialeyes session <folder> --build build/<study>` writes:

| file | contents |
|---|---|
| `quality.json` | duration, completed?, time in background, interruptions (count and seconds per kind), Do Not Disturb at start, dropped frames, phone slept?, Neon disconnects, thermal status, front camera checks, motion sensor rate and gaps |
| `strokes.csv` | one row per finger stroke: duration, distance, speed, `gesture` = `tap`, `double_tap`, `long_press`, `scroll`, `fling`, `pinch` |
| `exposure.csv` | per post and element: seconds on screen (any part / fully / area-weighted), first time seen, times scrolled into view |
| `touch_targets.csv` | every touch sample mapped to post, element, image pixel and AOI |
| `occlusion.csv` | periods when a finger rested on an image, and which AOIs it probably covered |
| `interactions.csv` | the feed interaction events, one row each |

Finger occlusion is an estimate. The app knows the touch point, not the finger's
outline, so an AOI counts as covered if it lies within `finger_radius_mm`
(default 8 mm) of the touch point.
