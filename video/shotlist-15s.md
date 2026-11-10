# SocialEyes: 15-second silent demo (shot list)

Silent, captions only, same format as the Iris clip: `video/socialeyes-15s.mp4` (LinkedIn, 1080p),
`video/socialeyes-15s.gif` (README, 960 px, 12 fps) and `video/socialeyes-thumb.png` (cover).
Each shot is a small label + headline over a framed window (the phone as a phone frame, the
desktop app as a window) on the SocialEyes brand background (deep purple `#21005D` to
`#6750A4`). Fixed framing, no zooms, short fade-and-rise between shots. The SocialEyes logo
sits in a corner, and is large on the last screen.

| # | Time | Label · headline (≤ 8 words) | On screen | Action |
|---|---|---|---|---|
| 1 | 0.0–3.0 s | THE PROBLEM · **Body-image studies: control or realism, pick one** | Phone frame with the Pictogram feed (stories row, a filler post). | The feed scrolls slowly, as a participant would. |
| 2 | 3.0–7.0 s | THE FIX · **Researchers control every post, label and comment** | The guided experiment builder (`builder/index.html`), filled in with the example study: posts, image versions, "edited" labels, comments. | A critical post is set to show the retouched version with the "edited" label (exact clicks depend on the builder's form). |
| 3a | 7.0–9.5 s | ON THE PHONE · **A realistic feed, synced with Neon eye tracking** | Phone frame: a critical post with "This image has been digitally altered". | Scroll onto the post, then double-tap: the heart and the like count update. |
| 3b | 9.5–11.0 s | (same) | The same placeholder image with a gaze heatmap over it. A clear tag on the image: **Simulated data · Experimental feature**. | The heatmap fades in over the image. |
| 4 | 11.0–15.0 s | THE RESULT · **Built in 2 months, not 2 years** | Stats rise in: **8** UBC researchers · **2 months** to build, to spec · **3 pilots** running soon. Then the SocialEyes logo and "Built for UBC researchers studying attention on social media". | Hold. |

## Facts used (from the README and your answers, 2026-11-09)

- Built for a team of **8 researchers at UBC** who study attention and gaze on social media.
- **3 pilots** are running on it soon (updated 2026-11-09; the README says a pilot is underway).
- **Built to spec in 2 months instead of 2 years** (your answer; not in the README).
- Researchers set the feed's images, "edited" labels, comments, captions and like counts.
- The phone app starts and stops the **Pupil Labs Neon** recording and shows a sync patch to
  line up the clocks.
- Heatmaps are **Experimental** and the gaze-to-screen mapping isn't built yet, so the heatmap
  shot uses simulated fixations and says so on screen.

## Hard rules

- **No pilot data.** Nothing from `data/`, `analysis_out/`, `studies/pilot_neon` or any session.
- **Only the example study's placeholder images** (the stylised figures from
  `studies/example/make_placeholders.py`). No real stimuli, faces or photos.
- The feed shows its own "Pictogram" branding; captions don't name Instagram or Meta.

## How it would be recorded (Step 3 preview)

- **Phone:** the Pixel 3 emulator (`.toolchain/avd/se_pixel3`) running the app with the example
  study, recorded at the phone's own resolution with `adb shell screenrecord`, so no other window
  can end up in the frame. Taps and scrolls are scripted with `adb shell input`.
- **Builder:** `builder/index.html` in a separate, clean browser window (no tabs, bookmarks or profile), recorded with the same check as Iris that
  only that window is on screen.
- **Heatmap:** made from simulated fixations on the placeholder image, using the project's own
  heatmap code if it accepts them, otherwise drawn in the edit.
