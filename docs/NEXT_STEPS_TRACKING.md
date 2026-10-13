# Phone tracking: where things stand and what to do next (CAM-165, CAM-210, CAM-219)

Written 12 Oct 2026 after a session with the Neon glasses. Read with
[PHONE_TRACKING_TESTS.md](PHONE_TRACKING_TESTS.md) (the test plan) and the Linear issues.

## Decided

- **On-screen tags: AprilTag 16h5, 10 mm, black**, in the corners of the top bar and the tab bar,
  black border 5 mm from the side edges and 2 mm from the top/bottom edges. The bars grow from
  84/50 dp to 86/86 dp (feed 4.5% shorter). Grey tags and tags of 9 mm or less read clearly worse.
- **Screen brightness about 0.30** indoors, set once per session and kept fixed (never changing
  while the participant scrolls). Scene camera on **auto exposure, Companion's Highlights mode**.
- **Gaze offset**: correct it from the study's own validation dots, not with Companion's offset
  correction (which didn't help: 1.7° uncorrected either way, 0.38° after the dots' shift).

## Results from 12 Oct (data is local only: `data/` and `analysis_out/` are git-ignored)

| Recording | Data | What it showed |
|---|---|---|
| tag_ladder A (no calibration) / B (calibrated) | `data/tag_ladder/A`, `B`; `analysis_out/tag_ladder/A`, `B` | Lower screen brightness is what makes tags readable; 36h11 needs ~28 px (14 mm) to read reliably. "Arm's length" in B was only 36 cm |
| accuracy_check v4 (wearer "Cam", offset-corrected, brightness 0.30) | `data/accuracy_check_v4`; `analysis_out/tracking_pnp/v4` | Tags read in 90–100% of frames; 26/26 dots; 0.38° after a per-session shift |
| tag_bars run 1 (T01; phone already at 0.29, auto exposure) | `data/tag_bars/run1`; `analysis_out/tag_bars/run1` | The tag decision above (table below) |
| tag_bars run 2 (T02; calibration chose 1000 µs fixed exposure) | `data/tag_bars/run2`; `analysis_out/tag_bars/run2` | **Not usable**: every variant read the same 40–70% in each time window, so something else (probably the fixed exposure) limited it |

tag_bars run 1, share of frames with a top AND a bottom tag read:

| Variant | Feed lost | Normal 36 cm | Arm's length 53 cm | Lap 37 cm |
|---|---|---|---|---|
| 36h11 14 mm | 10.7% | 100% | 74% | 99% |
| 36h11 12 mm | 7.2% | 100% | 0% | 100% |
| 25h9 12 mm | 7.6% | 82% | 58% | 93% |
| **16h5 10 mm** | **4.5%** | **98%** | **34%** | **100%** |
| 16h5 9 mm | 3.4% | 91% | 3% | 73% |
| 25h9 10 mm | 4.1% | 80% | 1% | 90% |
| 16h5 10 mm grey 40% | 4.5% | 34% | 0% | 63% |
| 16h5 8 mm | 2.5% | 20% | 0% | 25% |

Arm's length was poor for all in the first round of that hold and ~97–100% for 16h5 10 mm,
25h9 12 mm and 36h11 14 mm in the second (all have ~1.7 mm cells).

Comparison page (screenshots of every layout, feed space, read rates):
`analysis_out/ui_gallery/index.html`, rebuilt with

    python scripts/tag_bars_gallery.py analysis_out/ui_gallery/shots analysis_out/ui_gallery/layout_session --results analysis_out/tag_bars/run1/bars_summary.csv

Other findings: optical flow bridges tag gaps very well (0.12 mm median after 1 s in B); content
matching was almost never accepted (screen too blown out) so drop it as a tracker; the motion
sensors explained none of the tags' motion in A or B (fitted axes 156° from Pupil Labs': almost
certainly an axis/timing bug in `scripts/imu_tracking_test.py`, not useless sensors).

## Next, in order (none of 1–4 needs the glasses)

1. **Smart detection in the analysis** (`python/src/socialeyes/gaze/`). Predict where each tag
   should be from the last pose / optical flow; accept a detection only if it has an expected id,
   lies within a few px of its predicted spot and fits the pose (guards tag16h5's false reads);
   then search harder there: crop around each predicted tag, upscale 2–3x, sharpen, darken if blown
   out, and allow 1 bit error at the expected spot only. Test: rerun tag_bars run 1 and compare
   read rates per variant (`python -m socialeyes.gaze.ladder data/tag_bars/run1/neon
   data/tag_bars/run1/app/T01-20261012T233229`), especially arm's length and 16h5 9 mm.
2. **Display calibration: auto exposure only.** Drop the manual exposures from the default
   `--exposures` in `socialeyes calibrate-display` (`python/src/socialeyes/gaze/display_calibration.py`);
   consider simply `display.brightness: 0.30` in studies if calibration keeps choosing ~0.30.
3. **Real layout: 16h5 10 mm tags in the feed's own bars.** A `markers.on_screen` layout option
   (e.g. `layout: bars`, `family: tag16h5`, `size_mm: 10`) drawn by FeedScreen's top bar and tab bar,
   reusing `ui/TagBars.kt`'s geometry; keep the bars visible over stories, reels and the comment
   sheet (they cover them now). Make `socialeyes gaze` read the family from the `marker_layout`
   event. Python tests + a Kotlin unit test, bump the app version.
4. **Fix the sensor analysis** (`scripts/imu_tracking_test.py`): axes/sign/lag of the Neon IMU and
   the phone gyro against tag motion (ladder holds 3–4 in `data/tag_ladder/A`, `B`).
5. **With the glasses:** one feed recording with the real layout (L4 in PHONE_TRACKING_TESTS.md),
   held at normal distance and at arm's length; then CAM-219 (in-app calibration without the
   laptop) only if a fixed brightness turns out not to be enough.

## Loose ends

- Not yet posted to Linear: these results (CAM-165, CAM-210).
- Companion's recording template has no "Participant"/"Study" fields (warning on every session).
- On the phone: screenshot sessions tag_bars/T08 and the scratch studies `shots_tags` and
  `shots_plain` (not in the repo) can be deleted; T01/T02 of tag_bars are the real runs (copied).
- Phone app is 0.3.0 (release build); tag_bars and accuracy_check v4 are loaded.
- Wireless debugging port changes whenever it is toggled: `adb connect <ip>:<port>` from
  Developer options > Wireless debugging.
