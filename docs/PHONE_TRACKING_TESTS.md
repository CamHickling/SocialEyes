# Phone tracking: test checklist (CAM-165)

Gaze from the Neon glasses lands in the scene camera's picture. To know *where on the phone
screen* someone looked, every scene frame needs the phone screen's position (a scene → screen
mapping). This page lists the tests that decide how SocialEyes gets that mapping, what each
result would mean, and what to do about it.

The options under test:

| # | Option | What it is | Status |
|---|---|---|---|
| 1 | Screen content | Use the feed's own images (their on-screen positions are logged) to place the phone when tags are missed | Offline test done on CAM-210 runs (C1) |
| 2 | Better maths | 3-D pose from the tags (PnP) + optical-flow bridging | Built: `socialeyes gaze` |
| 3 | Tags in the app's bars | Small tags inside the top bar and tab bar, size chosen by the tag ladder | Waiting on the ladder recording (CAM-220) |
| 4 | Clip-on frame | Rigid printed frame with large tags, clipped to the phone | Not built |
| 5 | Motion sensors | Glasses IMU (head) + phone gyroscope (hand) carry the pose through gaps | Offline test of the glasses' IMU done (S1) |

They combine: tags (3, or 4) give the pose; maths (2) gets the most from few tags; flow, content
(1) and sensors (5) fill the gaps between tag frames and catch bad frames.

**Accuracy budget.** Neon's own gaze error is about 1.3–1.8° ≈ 8–11 mm on a phone at 35 cm. The
tracking should add well under that: **≤ 1 mm typical, ≤ 3 mm p90** keeps it negligible;
3–5 mm is usable for post-level AOIs (a post image is ~70 × 90 mm) but not for small AOIs.

Each test below says whether it **needs the glasses** or can run **offline** on recordings we
have. Shared scripts: `scripts/tracking_pnp_test.py`, `scripts/content_tracking_test.py`,
`scripts/imu_tracking_test.py`, `python -m socialeyes.gaze.ladder` and `socialeyes gaze`.

---

## Next glasses session: run sheet

One session of about 20 minutes covers everything that needs the glasses right now. Phone and
laptop on the same Wi-Fi (or the laptop on the phone's hotspot).

- [ ] On the laptop: `. .\scripts\env.ps1`, then `socialeyes load studies/tag_ladder --update-app`
      (installs this build of Pictogram and the study; phone plugged in by USB).
- [ ] Glasses on, Companion open. Start a tag_ladder session: the **eye tracker check** screen
      should show the glasses, battery, storage, streams and scene camera settings (the first
      real test of the camera, template and calibration calls). Tick the checklist, Start.
- [ ] **Recording A (Companion's defaults)** — at the display calibration step, wait 10 s and
      tap *Skip calibration*. Run the rest of the study (≈ 3 min).
- [ ] **Recording B (calibrated)** — start a second session. At the display calibration step,
      on the laptop: `socialeyes calibrate-display <phone ip>` (the phone shows the address).
      `--check` first if you like: it only tests both connections. Keep looking at the screen for
      ~30 s; the laptop prints each setting's score and the one it chose. Run the rest.
- [ ] After each session, check in Companion that the scene camera is back on auto.
- [ ] Copy both Neon recordings and both session folders off the phone (never delete anyone
      else's recordings or `Documents/TouchTracking`).
- [ ] Run the analyses: X1, L1–L3, S2–S4, C2 (commands below), comparing A with B.

If the calibration can't connect: the phone and laptop must reach each other (try the phone's
hotspot), and port 8091 must be free on the phone. If it reads no tags at any setting, the phone
isn't in the scene camera's view: hold it as in the feed.

---

## X. Setup: scene camera exposure (affects every option)

**X1 — Is the phone screen blown out in the scene video, and does the display calibration fix it?**
*Needs the glasses (recordings A/B: defaults vs `display_calibration`).*

Found in C1: the scene camera exposes for the room, so the bright phone screen is mostly
saturated. In CAM-210 run 3, **half of the known screen content was pure white in the video**
(median 52%, up to 75%). The same glare washed out on-screen tags in CAM-210.

Run: `content_tracking_test.py` (its step 0 prints the share of content the video resolves) and
`python -m socialeyes.gaze.ladder` on recordings A and B.

| Result | Meaning | Action |
|---|---|---|
| B resolves ≥ 80% of content and its tag detection is at least A's | Exposure/brightness was hurting us | Put a `display_calibration` step in every study (or, if the chosen setting is the same every time, fix it with `neon.scene_exposure` + `display.brightness`) |
| B resolves more content but detects fewer tags (room/face too dark doesn't matter; tags do) | Trade-off | Keep the setting that gives better tag detection; content (option 1) gets less weight |
| No difference | The screen's own brightness is the problem | Try lower phone brightness in the app during sessions (one-line change), retest |

---

## 2. Better maths (built)

**M1 — PnP vs homography, fewer tags, flow.** *Offline, done* (`tracking_pnp_test.py`, CAM-210
runs 2–3). PnP halved the gaze error at the validation dots in run 3 (0.91° → 0.49°); one top +
one bottom tag ≈ 0.45 mm; frames with a mapping rose from 24–38% to 67–96%, ~100% with flow.

**M2 — Every new recording: coverage and accuracy.** *Needs recordings with on-screen tags.*
Run `socialeyes gaze NEON SESSION` and read the summary (share of frames mapped by tags / flow /
none) and, if the study has validation, the error at the dots.

| Result | Meaning | Action |
|---|---|---|
| Tags ≥ 85% of feed frames, unmapped < 2%, dots ≤ 0.6° after shift | Tracking is not the bottleneck | Nothing; carry on |
| Tags 50–85%, flow fills most of the rest | Workable, but gaps are bridged by flow | Check gap lengths; options 1/5 for gaps > 300 ms |
| Tags < 50% | Tags too small, washed out or covered | Revisit X1 and L1; consider option 4 |

---

## 3. Tags in the app's bars (choose size, inset, clearance)

All from the tag ladder recording. *Needs the glasses (recording A, and B for comparison).*
`python -m socialeyes.gaze.ladder NEON SESSION` prints detection rates by size, inset and gap,
for each hold, plus each tag's apparent width in scene pixels. Earlier data: detection is ≥ 90%
once a tag is ≥ 24 px wide in the scene, < 10% under 20 px.

**L1 — Tag size.** Sizes 8, 10, 12 and 14 mm, held normally, at arm's length, and low near the lap.

| Result | Meaning | Action |
|---|---|---|
| A size ≤ 10 mm reads ≥ 90% in all three holds | Bar tags fit (with a 6 mm inset, ~10 mm leaves room for the 5 tabs) | Build the bar layout at that size |
| 10 mm only fails at arm's length | Distance limit (~24 px) | Use 10 mm; instruct a normal holding distance; flow/sensors cover the rest |
| Only 12–14 mm read reliably | Bar tags won't fit beside the tabs | Taller bars (costs feed space), tags only in the top bar (+ bottom bar's ends), or option 4 |
| Nothing ≥ 90% even at 14 mm | Exposure or focus problem, not size | Fix X1 first, then repeat |

**L2 — Side inset** (3–6 mm from the curved screen edges, 12 mm tags).

| Result | Meaning | Action |
|---|---|---|
| 3–4 mm reads as well as 6 mm | The curved edge doesn't hurt | Use the smallest inset that reads: frees bar width |
| Only 5–6 mm reads | The curve distorts or hides the tags | Use 6 mm; size from L1 must fit with it |

**L3 — Top/bottom clearance** (1.5 vs 3.5 mm from the screen edge).

| Result | Meaning | Action |
|---|---|---|
| 1.5 mm reads as well as 3.5 mm | 2 mm clearance (current) is plenty | Keep it |
| 1.5 mm reads clearly worse | The bezel merges with the tag border (as in CAM-210 run 3) | Use ≥ 3.5 mm |

**L4 — After building the bar layout: a feed recording.** Run M2 on it, plus
`tracking_pnp_test.py` for one-top + one-bottom accuracy.

| Result | Meaning | Action |
|---|---|---|
| ≥ 85% of feed frames with a top and a bottom tag, ≤ 1 mm | Option 3 works | Make it the default `markers.on_screen` layout |
| Mostly only one bar's tags seen | Pose from one end only (top 2 tags alone ≈ 2 mm, p90 9 mm) | Content/sensors (1, 5) needed to steady the far end |

Note: stories, reels and the comment sheet cover the bars; the layout must keep the bars
visible over them (planned), or those screens go untracked.

---

## 1. Screen content

The app logs where every post image is on screen in every frame (`viewport.csv`) and the study
package holds the images, so we know what most of the screen showed. Starting from an estimate of
the phone's pose (the last tag pose, or flow), the scene frame is warped onto the screen and
aligned with the expected images.

**C1 — Offline on CAM-210 runs 2–3.** *Done* (`content_tracking_test.py`).

- **The content log is accurate.** Started from the tag pose, a shift-only alignment agrees with
  the tags to **0.4–0.5 mm** (median; p90 0.8–1.4 mm). That is the floor for this method here.
- **The screen shows a frame ~30 ms after the app logs it.** That delay fits best in both runs;
  the pipeline must apply it, or fast scrolling smears the match.
- **Only simple warps work.** A shift (or shift + rotation) of the starting estimate is stable;
  affine and full homography warps drift by tens of mm on the small patches of screen the video
  resolves.
- **Exposure is the limit.** Content was known in 87–99% of feed frames, but the video resolved
  only 42–45% of it (the rest was blown out). Alignments were accepted in ~40–60% of
  frames when bridging.
- **Bridging** (tags missed for N frames; median / p90 mm; content = shift-only, used where
  accepted, else the starting estimate):

  | Gap | Run 2: keep old | Run 2: flow | Run 2: content from flow | Run 3: keep old | Run 3: flow | Run 3: content from old pose |
  |---|---|---|---|---|---|---|
  | 267 ms | 2.4 / 6.5 | 0.21 / 1.3 | 0.44 / 1.7 | 1.5 / 4.7 | 1.7 / 4.6 | 1.3 / 3.4 |
  | 500 ms | 4.4 / 14 | 0.32 / 2.7 | 0.52 / 2.3 | 2.0 / 6.4 | 2.3 / 5.5 | 1.4 / 7.1 |
  | 1 s | 9.3 / 43 | 0.73 / 5.2 | 0.74 / 3.2 | 2.7 / 11 | 4.0 / 8.6 | 2.2 / 11 |
  | 2 s | 21 / 45 | 1.7 / 13 | 1.7 / 13 | 3.4 / 10 | 5.5 / 10 | 3.3 / 10 |

  Where content was accepted and the feed scrolled slowly (< 300 px/s), the error stayed at
  0.5–0.9 mm for gaps up to 1 s in both runs; fast scrolling (> 1500 px/s) roughly doubled it.

**What C1 means.** Content is not a better refiner than good flow: its floor (~0.45 mm) is worse
than flow over short gaps (run 2: 0.2 mm), so applying it all the time made run 2 slightly
worse. It pays off when the current estimate is likely off by more than ~1 mm: when flow is
struggling (run 3), after long gaps, and to **cap flow's p90** (run 2 at 1 s: 5.2 → 3.2 mm). The
rule for the pipeline is: flow first; content shift only after ~300 ms without tags or when flow
and content disagree by > 1 mm; reject shifts over 8 mm (mis-locks).

**C2 — Repeat on the new recordings (A and B).** *Needs the glasses.*
`python scripts/content_tracking_test.py NEON SESSION data/tag_ladder/builds/<hash> analysis_out/tag_ladder/<session>`

| Result | Meaning | Action |
|---|---|---|
| With B's exposure: content resolved ≥ 80%, shift accepted ≥ 70% when bridging 1 s at ≤ 1 mm | Content is a reliable gap filler | Add it to `socialeyes gaze` with the rule above (gaps > 300 ms or disagreement with flow) |
| Better acceptance but p90 still > 5 mm | Mis-locks on flat or repeating content | Use content only to *flag* frames where flow is doubtful |
| Acceptance stays < 40% even with B | Too little content resolves | Drop option 1 as a tracker (the logs still serve AOIs) |
| The best latency differs from 30 ms | Display delay depends on the phone/refresh rate | Measure it per phone model and store it with the device |

**C3 — Real photographs.** *Offline once a study with photographic images exists.* The test
images so far are flat cartoons (large single-colour areas), the hardest case for alignment;
real photos have texture everywhere. Rerun C1/C2 on a pilot with the real stimuli.

| Result | Meaning | Action |
|---|---|---|
| Clearly better than cartoons (acceptance up, errors down) | Option 1's value depends on stimuli | Keep content refinement on for photo studies |
| No better | The bottleneck is exposure/resolution, not texture | Decide on C2's numbers alone |

---

## 5. Motion sensors

The phone moves in the scene picture because the **head** turns (Neon's IMU sees this), the
**hand** turns the phone (the phone's gyroscope sees this) or either shifts sideways (neither
sensor measures this well).

**S1 — Neon IMU alone, offline on CAM-210 runs 2–3.** *Done* (`imu_tracking_test.py`).

- Units check: the gyro is in deg/s (integrated rotation matches Neon's own orientation within
  0–9%).
- Head rotation predicts the tags' image motion well in run 2's validation step (explains
  45–58%) but not while scrolling the feed (the hand moves the phone; the share explained is
  0 or below).
- Bridging a tag gap with the head gyro alone, vs keeping the last pose (median / p90 mm):

  | Gap | Run 2: hold | Run 2: head gyro | Run 2: flow | Run 3: hold | Run 3: head gyro | Run 3: flow |
  |---|---|---|---|---|---|---|
  | 267 ms | 2.0 / 5.7 | 1.2 / 3.6 | 0.16 / 0.45 | 1.1 / 2.2 | 0.9 / 2.1 | 1.6 / 5.2 |
  | 1 s | 6.2 / 19 | 3.1 / 9.0 | 0.40 / 1.5 | 2.3 / 8.1 | 1.7 / 9.0 | 4.9 / 15 |
  | 2 s | 11 / 37 | 5.2 / 11 | 0.71 / 2.1 | 4.1 / 17 | 3.5 / 16 | 8.7 / 20 |

  So: when flow works (run 2) it beats everything; when it doesn't (run 3, glare) the head gyro
  is the better bridge. The head alone never gets under ~1 mm beyond a few frames, because the
  hand moves the phone too.

**S2 — Head-only motion: check the IMU's axes and timing.** *Needs the glasses* (ladder hold 4:
phone flat on the table, head turning and nodding). `imu_tracking_test.py` on recording A.

| Result | Meaning | Action |
|---|---|---|
| Head explains ≥ 80% of tag motion in hold 4, fitted axes within ~5° of Pupil Labs', lag ≈ 0 | IMU → camera transform confirmed | Use the documented axes in the pipeline |
| Explains ≥ 80% only with fitted axes/lag | Our transform or the clocks are off | Use the fitted values; check against a second recording |
| Low even in hold 4 | Something is wrong with the IMU data or timing | Investigate before relying on option 5 |

**S3 — Phone-only motion: check the phone gyroscope.** *Needs the glasses* (ladder hold 5: head
still, phone tilted and turned). Same script; reads `sensors.csv`.

| Result | Meaning | Action |
|---|---|---|
| Phone gyro explains ≥ 80% of tag motion in hold 5 | Phone axes and clock are right | Go on to S4 |
| Explains much less | Axes, clock offset, or the pivot point (where the hand turns the phone) are off | Fit them from hold 5 before S4 |

**S4 — Bridging with both gyros, in normal use.** *Needs the glasses* (ladder holds 1–3 and the
feed of recording A). The gap table now has `head+phone`.

| Result | Meaning | Action |
|---|---|---|
| head+phone ≤ 1 mm at 1 s, better than flow where flow struggles | Sensors are a strong bridge | Add to `socialeyes gaze`: gyros predict, flow/content correct; allow bridging well past 300 ms |
| Better than hold but > 2 mm at 1 s | Sideways hand motion dominates | Use sensors only for short gaps and to flag implausible flow |
| No better than head alone | The phone gyro adds nothing | Leave phone sensors off in studies (saves battery and log size) |

---

## 4. Clip-on frame (not built)

A rigid printed frame clipped around the phone with larger tags (≥ 14 mm, never washed out by
the screen). Only worth building if L1 shows bar-sized tags don't read reliably, or as a
high-accuracy reference for validating the other options. Needs a 3D printer.

**K1 — Detection.** Record the ladder holds with the frame on. *Expect ≥ 98% in every hold.*
Below that, the frame's tags are too small or too far from the camera's focus range.

**K2 — Frame-to-screen offset.** Clip on and off five times, each time recording the on-screen
calibration tags too; compare the frame's pose with the screen's.

| Result | Meaning | Action |
|---|---|---|
| Offset varies ≤ 0.5 mm | Frame sits repeatably | A one-time calibration per phone is enough |
| Varies more | The clip moves | Calibrate every session (a 10 s on-screen tag step), or redesign the clip |

**K3 — Participant experience.** Ask pilot participants whether holding and scrolling felt
normal; check touch.csv for missed taps near the edges.

| Result | Meaning | Action |
|---|---|---|
| Feels normal, no edge taps missed | Acceptable | Option 4 can be the primary tracker if L1 fails |
| Blocks the thumb or feels odd | Ecological cost | Keep option 3 as primary; frame only for validation studies |

---

## How the results decide the setup

1. **X1** first: if a darker exposure helps, it helps everything.
2. **L1–L3** decide whether tags fit in the bars (option 3). If yes, that's the primary tracker;
   if not, **option 4** (frame) becomes the primary, or taller bars.
3. **M2/L4** say how often tags are missed in real scrolling, i.e. how much gap-filling is needed.
4. **S2–S4** and **C2/C3** decide what fills the gaps: flow alone, flow + sensors, flow +
   content, or all three (each checks the others).
