# Phone tracking: where things stand and what to do next (CAM-165, CAM-210, CAM-219)

Written 12 Oct 2026 after a session with the Neon glasses; updated 13 Oct. Read with
[PHONE_TRACKING_TESTS.md](PHONE_TRACKING_TESTS.md) (the test plan) and the Linear issues.

## 13 Oct: a frame-reading bug, smart detection, motion sensors

**Bug (fixed):** jumping to a frame in the scene video (`CAP_PROP_POS_FRAMES`) lands on the wrong
frame in Companion's videos, badly in tag_ladder B and tag_bars run 2 (variable frame rate), a
little early on in A and run 1. Every analysis read images that didn't match their timestamps. All
code now reads frames in order (`neon.SceneVideo`). Results below are re-analysed (`analysis_out/
tag_bars_v2`, `analysis_out/tag_ladder_v2`); the tag_ladder A/B size results and accuracy_check v4
have not been rerun yet.

**Smart detection (built):** the tracker predicts each tag's spot from the last known mapping and
looks closely there for tags the whole-frame search missed (crop, enlarge to ~8 px per cell,
sharpen, contrast-stretch, darken); a read with 1 bit wrong counts only at its predicted spot.
`python -m socialeyes.gaze.ladder ... --plain` turns it off for comparison; `socialeyes gaze` uses it.

**Motion sensors (fixed):** with frames in order, the Neon IMU explains ~91% of the tags' motion
when only the head turns (B); the camera tilt's sign in `CAMERA_FROM_IMU` was flipped (fixed:
fitted axes now 7° from it, were 23.5°). The phone's gyroscope predicts ~86% of the phone's
rotation, but the hand also shifts the phone a few mm sideways, which no gyroscope measures. Flow
bridges gaps ~10x better (0.06 vs 0.6 mm after 267 ms), so the sensors aren't used for tracking.

## 18 Oct: the older analyses rerun with frames in order

`analysis_out/rerun_18oct/` (ladder_A, ladder_B, accuracy_v4). No decision changes.

- **tag_ladder B was scrambled before**: frames had been matched to the wrong holds (the old
  "arm's length" hold measured 36 cm, the old "lap" hold 52 cm). Now each hold's distance fits its
  instruction (arm's length 50 cm, lap 41 cm), and B gives tag36h11 readable (>= 85%) from ~30 px
  wide: 10 mm to ~30 cm, 12 mm to ~35 cm, 14 mm to ~41 cm.
- **tag_ladder A reads better than reported**: e.g. 14 mm held normally 76% -> 99%, 12 mm while
  tilting the phone 29% -> 51%, and 5x more arm's-length frames with a pose (16 -> 88). Readable
  from ~32 px (10 mm to ~28 cm, 14 mm to ~39 cm).
- **accuracy_check v4**: gaze accuracy unchanged (PnP, all 4 tags: 1.68 deg raw, 0.38 deg after the
  per-session shift). Optical flow bridges gaps better than reported: the 90th-percentile drift
  after 60 frames (2 s) without tags is 4.2 mm, was 11.6 mm (after 15 frames 1.7, was 2.3 mm).
  One top + one bottom tag is a little worse at the 90th percentile (0.89 mm, was 0.67 mm).

These ladders used tag36h11. The chosen tag16h5 10 mm comes from tag_bars, which was already
re-analysed on 13 Oct.

## Results: tag_bars, share of frames with a top AND a bottom tag read (smart detection; plain in brackets)

| Variant | Feed lost | Run 1 normal 36 cm | Run 1 arm's 53 cm | Run 1 lap 37 cm | Run 2 normal 32 cm | Run 2 arm's 45 cm | Run 2 lap 35 cm |
|---|---|---|---|---|---|---|---|
| 36h11 14 mm | 10.7% | 100 (100) | 85 (74) | 99 (99) | 86 (86) | 100 (100) | 68 (68) |
| 25h9 12 mm | 7.6% | 83 (83) | 71 (58) | 93 (93) | 92 (92) | 90 (90) | 47 (47) |
| 36h11 12 mm | 7.2% | 100 (100) | 4 (0) | 100 (100) | 100 (100) | 97 (97) | 65 (65) |
| **16h5 10 mm** | **4.5%** | **98 (97)** | **77 (34)** | **100 (100)** | **100 (100)** | **95 (91)** | **61 (58)** |
| 16h5 10 mm grey 40% | 4.5% | 95 (34) | 0 (0) | 95 (63) | 99 (99) | 48 (45) | 69 (68) |
| 25h9 10 mm | 4.1% | 88 (81) | 1 (1) | 100 (90) | 97 (97) | 100 (100) | 42 (42) |
| 16h5 9 mm | 3.4% | 100 (91) | 24 (3) | 76 (73) | 100 (100) | 86 (86) | 88 (88) |
| 16h5 8 mm | 2.5% | 68 (21) | 0 (0) | 84 (25) | 92 (91) | 60 (57) | 96 (93) |

- Run 1: screen on the phone's own auto-brightness (0.22–0.30), scene camera on Companion's own
  setting (auto, Highlights), 30 fps.
- Run 2: screen 0.30 and scene camera manual 1000 µs (both chosen by the laptop calibration).
  **Usable after all** (the old "not usable" was the frame bug), and better at arm's length. Its lap
  hold was poor for every variant in the first round only (how it was held, not the tags). But its
  scene video ran at **10 fps** from the moment the calibration set a 2000 µs manual exposure, and
  stayed there after going back to auto; B went through the same settings at 30 fps.
- 16h5 10 mm stays the choice. Every frame with reads gave a pose within 2 px, smart or plain.

Test report (summary, method, charts plain vs smart, tables, Tests, screenshots; `notes.txt` holds the hand-written findings):
`analysis_out/ui_gallery/index.html`, rebuilt with

    python scripts/tag_bars_gallery.py analysis_out/ui_gallery/shots analysis_out/ui_gallery/layout_session \
      --notes analysis_out/ui_gallery/notes.txt \
      --test "Run 1" data/tag_bars/run1/neon data/tag_bars/run1/app/T01-20261012T233229 analysis_out/tag_bars_v2/run1_smart/bars_summary.csv \
      --plain "Run 1" analysis_out/tag_bars_v2/run1_plain/bars_summary.csv \
      --test "Run 2" data/tag_bars/run2/neon data/tag_bars/run2/app/T02-20261012T233744 analysis_out/tag_bars_v2/run2_smart/bars_summary.csv \
      --plain "Run 2" analysis_out/tag_bars_v2/run2_plain/bars_summary.csv

## Decided

- **On-screen tags: AprilTag 16h5, 10 mm, black**, in the corners of the top bar and the tab bar,
  black border 5 mm from the side edges and 2 mm from the top/bottom edges. The bars grow from
  84/50 dp to 86/86 dp (feed 4.5% shorter).
- **Sessions run on the phone and glasses alone.** The laptop only builds studies and loads/unloads
  data, so no laptop display calibration during sessions: screen brightness and scene camera
  exposure are fixed per study (`display.brightness`, `neon.scene_exposure`) and applied by the app
  through Companion's local API. Which values is still open (see Tests on the comparison page).
- **Gaze offset**: correct it from the study's own validation dots, not with Companion's offset
  correction (which didn't help: 1.7° uncorrected either way, 0.38° after the dots' shift).

## Next, in order

1. ~~**Rerun the older analyses**~~: done 18 Oct, see "18 Oct: the older analyses rerun" above.
2. **Real layout: 16h5 10 mm tags in the feed's own bars.** A `markers.on_screen` layout option
   (e.g. `layout: bars`, `family: tag16h5`, `size_mm: 10`) drawn by FeedScreen's top bar and tab bar,
   reusing `ui/TagBars.kt`'s geometry; keep the bars visible over stories, reels and the comment
   sheet. Make `socialeyes gaze` read the family from the `marker_layout` event.
3. **A phone-only settings test** (needs the glasses): a step that cycles screen brightness × scene
   camera setting itself (like tag_bars cycles variants), e.g. 0.30/0.45/0.60 × auto, auto biased
   darker, manual 1000/2000 µs, with the 16h5 10 mm bars; held normally and at arm's length. Logs
   each setting; the analysis reports reads, blown-out content and frame rate per setting. Also
   shows whether manual exposure drops the scene video to 10 fps.
4. **Pick the settings** from that and put them in the study defaults; then one real feed recording.
5. Retire the laptop display calibration (`socialeyes calibrate-display`, `display_calibration` step)
   once fixed settings are confirmed.

## Without the glasses (added 16 Oct)

The glasses are away for now, so work goes in this order (full descriptions in the README roadmap):

1. ~~**Tags in the real UI** (step 2 above) and a screenshot test~~: done 16 Oct.
   `markers.on_screen: {layout: bars, family: tag16h5, size_mm: 10}` draws the tags in the feed's
   bars; stories, reels and comments leave both bars uncovered; `socialeyes gaze` reads the
   family from `marker_layout`. Screenshots: `python scripts/tag_ui_shots.py` (studies/tag_ui) ->
   `analysis_out/tag_ui/index.html`. On a narrow phone the top bar drops its heart and messages
   icons while "I'm done" shows. Not yet in the experiment builder.
2. ~~**Clean data export**~~: done 16 Oct (`socialeyes export`, Data tab **Make tables**). Gaze
   columns join by_item once gaze is mapped to AOIs.
3. ~~**Front (face) camera features**~~: done 16 Oct (`socialeyes face`, MediaPipe 0.10.14
   installed with --no-deps; face columns in by_session). Checked on a recording of known
   actions (studies/face_test, data/face_test/F01). Not yet tested: looking up / down at the lap
   (pitch-only look-aways), other people in view, other phones' cameras. Installer not rebuilt
   with MediaPipe yet.
4. ~~**Image AOIs for face and body**~~: done 16 Oct (`socialeyes aois`, LabelMe files + review
   page). Tested on three openly licensed photos (bending, standing, face hidden) and a head and
   shoulders frame, not on a real study's images yet. Not in the desktop app yet.
5. ~~**Gaze heatmaps**~~: done 16 Oct (`socialeyes gaze` writes fixations.csv; `socialeyes
   heatmaps`; gaze columns in by_item). Checked on the 12 Oct accuracy_check session (90 feed
   fixations, 39 on images) and simulated fixations. Story and reel images aren't placed in
   image pixels yet. Needs a real multi-participant run with the glasses.
6. ~~**Desktop app review**~~: done 16–18 Oct (simpler layout, shorter Design pages).
7. Later: **facial expression analysis** of the front camera video.

Steps 3–5 above (settings test etc.) wait for the glasses; step 1 (rerun older analyses) can
be slotted in any time.

## Loose ends

- Linear caught up on 18 Oct: CAM-162, 163, 210, 220 Done; CAM-165 and CAM-219 In Progress.
- Companion's recording template has no "Participant"/"Study" fields (warning on every session).
- On the phone: screenshot sessions tag_bars/T08 and the scratch studies `shots_tags` and
  `shots_plain` (not in the repo) can be deleted; T01/T02 of tag_bars are the real runs (copied).
- Phone app is 0.3.0 (release build); tag_bars and accuracy_check v4 are loaded.
- Wireless debugging port changes whenever it is toggled: `adb connect <ip>:<port>` from
  Developer options > Wireless debugging.
