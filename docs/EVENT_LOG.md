# Session log format

> [!NOTE]
> **Draft (format version 1).** This is the contract between the Pictogram app
> (which writes these files) and the Python analysis (`socialeyes.session`,
> which reads them). The app (`android/`) writes session.json, events.jsonl,
> viewport.csv and touch.csv; sensors, screen recording and the front camera
> are not built yet. `socialeyes.session.simulate` writes realistic fake
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
  "camera": {"lens": "front", "width": 1280, "height": 720, "fps": 30, "timestamp_source": "realtime"},
  "end": {"reason": "completed", "clock": {"elapsed_ns": 0, "uptime_ns": 0, "wall_ms": 0}}
}
```

`logging` is a copy of the study's `logging:` section. `camera` (only when
recording the front camera) gives the resolution
and frame rate actually achieved, which can differ from what was requested, and
the camera's timestamp source (see Front camera).

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
| `caption_expand` | `post_id` |
| `profile_tap` | `post_id`, `target` (`handle` or `avatar`) |
| `label_tap` | `post_id` |
| `image_tap` | `post_id` (a single tap on the image that did nothing else) |
| `comment_submit` | `post_id`, `text`, `typing_ms` (only with `feed.allow_comment_typing`; individual keystrokes are never logged) |

**Sync and eye tracker**

| type | fields |
|---|---|
| `sync_patch` | `level` (0/1): every change of the sync patch |
| `neon` | `status` (`connected`, `disconnected`, `recording_start`, `recording_stop`), optional `recording_id` |

**Session quality**

| type | fields |
|---|---|
| `app_state` | `state` (`background` or `foreground`) |
| `interruption` | `kind` (`notification`, `call`, `dialog`, `other`) |
| `orientation` | `rotation` (0, 90, 180, 270) |
| `brightness` | `value` (0-1); at start and on every change |
| `jank` | `frames_dropped`, `longest_frame_ms`: at most once per second, only when frames were dropped |
| `battery` | `level` (0-1), `temp_c`: once per minute |
| `screen_recording` | `status` (`started`, `stopped`), `file` |
| `thermal` | `status` (`none`, `light`, `moderate`, `severe`, `critical`, `emergency`, `shutdown`; Android's `PowerManager` thermal status): at start and on every change |
| `camera` | `status` (`started`, `segment`, `stopped`, `error`), `file` (on `started`/`segment`), `message` (on `error`) |
| `camera_check` | `step_id`, `result` (`ok` or `failed`), `face_s` (seconds until a face was held in view) |

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
| `element` | `frame`, `post` (the whole card), `header`, `image`, `label`, `actions`, `caption`, `comments` |
| `left`, `top`, `right`, `bottom` | element rectangle, screen px, unclipped (blank on `frame` rows) |

When the feed step ends, the app writes one final `frame` row with no elements.
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

## sensors.csv

| column | meaning |
|---|---|
| `t_ns` | sample time (`SensorEvent.timestamp` is already on the elapsed base) |
| `sensor` | `accel` (m/s², incl. gravity), `gyro` (rad/s), `rotation` (unit quaternion) |
| `x`, `y`, `z` | values in device axes |
| `w` | quaternion w (`rotation` only) |

## Front camera

Optional (`logging.front_camera`), meant for facial-expression analysis. The
camera records only during the steps listed in `logging.front_camera.steps`
(default: the feed). Consent and anonymisation of the video are handled by the
researcher under their ethics approval; the app records whenever the study
enables the camera.

**Recording.** The app uses Camera2 (or CameraX with Camera2 interop) feeding a
hardware `MediaCodec` encoder: H.264, the configured resolution, frame rate and
bitrate, no audio. No preview is shown to the participant at any time.

**Segments.** A new file starts every `segment_s` seconds and at every
recording start: `camera/front_000.mp4`, `front_001.mp4`, ..., numbered across
the whole session. An MP4 is unreadable if the app dies before closing it, so
segments limit what a crash can destroy. A `camera` event marks each start,
new segment and stop.

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
`nanoTime` base and the app must convert them like touch times (see Clocks).
Either way, write the source to `camera.timestamp_source` (`realtime` or
`unknown`).

**Framing check.** The `camera_check` procedure step is run by the researcher.
The screen shows a framing guide and a face-detected indicator, **never the
video itself**: seeing your own image right before a body-image task would be a
manipulation in its own right. Continue unlocks after a face has been detected
continuously for `min_face_s` seconds.

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
| `quality.json` | duration, completed?, time in background, interruptions, dropped frames, phone slept?, Neon disconnects, thermal status, front camera checks |
| `strokes.csv` | one row per finger stroke: duration, distance, speed, `gesture` = `tap`, `double_tap`, `long_press`, `scroll`, `fling`, `pinch` |
| `exposure.csv` | per post and element: seconds on screen (any part / fully / area-weighted), first time seen, times scrolled into view |
| `touch_targets.csv` | every touch sample mapped to post, element, image pixel and AOI |
| `occlusion.csv` | periods when a finger rested on an image, and which AOIs it probably covered |
| `interactions.csv` | the feed interaction events, one row each |

Finger occlusion is an estimate. The app knows the touch point, not the finger's
outline, so an AOI counts as covered if it lies within `finger_radius_mm`
(default 8 mm) of the touch point.
