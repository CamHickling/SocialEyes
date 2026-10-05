<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/readme-banner-dark.png">
  <source media="(prefers-color-scheme: light)" srcset="docs/assets/readme-banner-light.png">
  <img alt="SocialEyes: gaze and attention in social media" src="docs/assets/readme-banner-light.png" width="100%">
</picture>

**A controllable mock social media feed + eye tracking, for body-image research.**

![status](https://img.shields.io/badge/status-work%20in%20progress-6750A4?style=flat-square)
![version](https://img.shields.io/badge/version-0.1-21005D?style=flat-square)
![python](https://img.shields.io/badge/python-3.10%2B-21005D?style=flat-square&logo=python&logoColor=white)
![platform](https://img.shields.io/badge/app-Android-21005D?style=flat-square&logo=android&logoColor=white)
![eye tracker](https://img.shields.io/badge/eye%20tracker-Pupil%20Labs%20Neon-21005D?style=flat-square)
![stats](https://img.shields.io/badge/stats-R%20%C2%B7%20lme4-21005D?style=flat-square&logo=r&logoColor=white)

[How it works](#how-it-works) ·
[Status](#feature-status) ·
[Install](#installation) ·
[Design a study](#designing-a-study) ·
[AOIs](#defining-areas-of-interest-aois) ·
[Hardware](#eye-tracking-hardware-setup) ·
[Roadmap](#roadmap)

</div>

<br>

> [!WARNING]
> **Work in progress (v0.1).** The study format (v1), the session log format (v1),
> the study compiler and command-line tool, the experiment builder and the phone
> app work. Neon control in the app and the gaze analysis pipeline are **not built
> yet**. Each part below is marked ✅ working, 🟡 partial or ⏳ planned, so you know
> what you can rely on today. Feedback from other labs is very welcome.

## <img src="docs/assets/socialeyes-mark.svg" height="28" align="top"> What is SocialEyes?

SocialEyes is an open toolkit for running **experiments on social media and
body image** in a controlled but realistic setting. Participants scroll an
Instagram-style feed on a real phone. The researcher decides exactly what is in
that feed: which images are edited, which carry a disclaimer label, what the
comments and like counts say, and in what order everything appears. While they
scroll, participants wear **Pupil Labs Neon** eye-tracking glasses, and
SocialEyes maps their gaze onto the regions of each image (face, waist, legs,
...).

<table>
<tr>
<td width="33%" valign="top">

### 🎛️ Manipulate
Swap image versions, add "edited" labels, change comments, captions and like
counts, all from one `study.yaml`.

</td>
<td width="33%" valign="top">

### ⚖️ Counterbalance
Latin-square rotation, blocked randomisation and constrained feed shuffling,
seeded so every plan is reproducible.

</td>
<td width="33%" valign="top">

### 👁️ Measure
AprilTags + an on-screen sync code map Neon gaze onto exact image regions, ready
for mixed models in R.

</td>
</tr>
</table>

**Typical questions it is built to answer:**

- Do people look longer at bodies in retouched images than in unedited ones?
- Does a "this image has been edited" label change where people look, how they
  rate the image, or their own body satisfaction afterwards?
- Do appearance-focused comments pull attention towards specific body regions?
- Can people later tell whether they saw the edited or the original version?

---

## How it works

```
 study.yaml + CSVs + images            (you write these)
          │
          ▼
 ┌─────────────────────┐   per-participant plans (feed order, conditions)
 │  study compiler     │──────────────────────────────────────────────┐
 │  (Python)           │                                              ▼
 └─────────────────────┘                                   ┌────────────────────┐
                                                           │ SocialEyes app     │
   Neon glasses ◄──── starts/stops recording, syncs ──────►│ (Android phone)    │
        │                                                  └────────────────────┘
        │ scene video + gaze                                         │ event log
        ▼                                                            ▼
 ┌──────────────────────────────────────────────────────────────────────────────┐
 │ analysis (Python): detect AprilTags → map gaze to screen → map to post/image │
 │ → label AOIs → fixations/dwell per AOI per condition                         │
 └──────────────────────────────────────────────────────────────────────────────┘
        │ tidy CSVs
        ▼
 mixed-effects models in R (lme4 / lmerTest / emmeans / ordinal)
```

1. **You describe the study** in a `study.yaml` file next to CSVs listing the
   fake accounts, images, posts and comments.
2. **The compiler** validates it, builds the counterbalancing and writes a
   reproducible plan for every participant: which condition each critical post
   is in, and the feed order.
3. **The phone app** (SocialEyes; inside the study its feed is branded with a
   neutral platform name, "Pictogram" by default, so we don't use any real
   platform's trademark) runs the procedure: instructions, calibration,
   questionnaires, the feed, ratings and a recognition test. It logs every
   scroll, dwell, like and tap with timestamps.
4. **Neon glasses** record the scene camera and gaze. AprilTag markers on the
   phone case and a small flickering **sync patch** on screen let us map gaze
   onto exact screen pixels and line up the two clocks to within one video
   frame.
5. **Analysis** turns gaze into per-post, per-AOI measures (dwell time,
   fixation count, time to first fixation) and exports tidy tables for R.

---

## Feature status

| Component | Status | Where |
|---|---|---|
| Study definition schema (`study.yaml`) with validation | ✅ | `python/src/socialeyes/study/schema.py` |
| Counterbalancing (Latin square), blocked randomisation, constrained feed shuffling | ✅ | `python/src/socialeyes/study/design.py` |
| AOI loading (native JSON and LabelMe), point-in-AOI labelling | ✅ | `python/src/socialeyes/study/aoi.py` |
| AprilTag generation/detection, printable phone-case marker sheet | ✅ | `python/src/socialeyes/markers.py` |
| Sync code (m-sequence) and validation dot layouts | ✅ | `design.py` |
| Toolchain setup script (Windows) | ✅ | `scripts/setup-toolchain.ps1` |
| `socialeyes` command-line tool (`validate`, `compile`, `case-sheet`, `phone-check`, `load`, `unload`, `folders`) | ✅ | `python/src/socialeyes/cli.py` |
| Study compiler (CSV loading, cross-checks, plan export) | ✅ | `python/src/socialeyes/study/compiler.py` |
| Example study (placeholder images) and tests | ✅ | `studies/example/`, `python/tests/` |
| Session log format (touches, scrolling, interactions, quality events) | ✅ | `docs/EVENT_LOG.md` (version 1) |
| Session analysis: gestures, time on screen, touch→AOI, finger occlusion, quality checks | ✅ | `python/src/socialeyes/session/` (tested on simulated sessions) |
| Experiment builder: guided form that writes study.yaml and CSV skeletons | ✅ | `builder/index.html` (open in a browser) |
| Desktop app (Windows): Design tab edits study folders in place and runs the compiler's checks; Phone tab loads studies onto the phone; Data tab unloads sessions with a register; Studies tab lists studies with their status; Content tab lists the files each study still needs; edits that would break collected data need a new version; Windows installer (`packaging/build.py`; release build waits for the signing key) | 🟡 | `socialeyes app` (`python/src/socialeyes/desktop/`) |
| CSV format reference | ✅ | `docs/STUDY_DESIGN.md` (version 1) |
| Android SocialEyes app: Instagram-style feed (stories row, comments sheet), sync patch, touch / scroll / viewport / quality logging, instructions, marker calibration, validation, questionnaires, image ratings, recognition test, camera check, front camera video, motion sensors, interruption detection | 🟡 | `android/` (tested on a Pixel 3) |
| App: screen recording, Neon control | ⏳ | see [What the app doesn't do yet](#what-the-app-doesnt-do-yet) |
| Neon integration (auto start/stop, clock sync) | ⏳ | |
| Gaze-to-screen mapping and AOI analysis | ⏳ | |
| R analysis templates | ⏳ | |
| macOS/Linux setup script | ⏳ | the conda environment already works cross-platform |

---

## Installation

Everything installs into a **project-local `.toolchain\` folder**. Nothing is
installed system-wide, and deleting that folder removes it all.

### Requirements

- Windows 10/11 (macOS/Linux: see below)
- [Miniforge](https://github.com/conda-forge/miniforge) or Anaconda (`conda` on your PATH)
- About 6 GB of free disk space
- Git

### Steps (Windows, PowerShell)

```powershell
git clone <this repository> SocialEyes
cd SocialEyes

# One-off: creates .toolchain\env (Python 3.12, JDK 17, R 4.4 + lme4 etc.)
# and .toolchain\android-sdk. Takes 10-30 minutes. Safe to re-run.
.\scripts\setup-toolchain.ps1

# In every new PowerShell window where you work on the project:
. .\scripts\env.ps1
```

Options:

- `-SkipAndroid`: only the analysis tools (Python + R), no Android SDK. Use this
  if you only analyse data, or if you prefer Android Studio.
- `-SkipConda`: only the Android SDK.

> [!NOTE]
> The setup script accepts the Android SDK licences for you. They are printed
> to the console if you want to read them.

If PowerShell refuses to run the script, allow local scripts for your user once:
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

### macOS / Linux

There is no shell script yet, but the environment file is cross-platform:

```bash
conda env create -p ./.toolchain/env -f environment.yml
conda activate ./.toolchain/env
```

### Check that it worked

```powershell
. .\scripts\env.ps1
python -c "import socialeyes, cv2; print('socialeyes', socialeyes.__version__, '| opencv', cv2.__version__)"
socialeyes validate studies/example
Rscript -e "library(lme4); cat('lme4 OK\n')"
java -version
```

---

## Designing a study

> [!NOTE]
> **Study format version 1.** The CSV columns are documented in
> [`docs/STUDY_DESIGN.md`](docs/STUDY_DESIGN.md). Studies written for v1 keep
> working: later versions only add optional columns and settings.
> [`studies/example/`](studies/example) is a complete working study to copy from.

A study is a folder:

```
studies/my_study/
  study.yaml       # design, procedure, settings
  accounts.csv     # fake poster accounts (name, avatar, ...)
  images.csv       # every image file, including all edited/unedited versions
  posts.csv        # which posts exist; which are critical vs. filler
  comments.csv     # comment sets that can be attached to posts (optional)
  captions.csv     # caption variants (optional)
  stories.csv      # stories behind the story circles (optional)
  reels.csv        # short videos for the Reels tab (optional)
  images/          # the image files
  aois/            # one AOI file per image (see below)
```

The CSV columns are described in [`docs/STUDY_DESIGN.md`](docs/STUDY_DESIGN.md).

### Experiment builder

Open [`builder/index.html`](builder/index.html) in a browser (double-click it; it
works offline and nothing is uploaded). It walks you through the decisions
(factors, content, feed, procedure, recording, participants), explains each choice,
and checks the design as you go: balance of posts and participants, factor
mappings, procedure rules and recording conflicts. It downloads a zip with
`study.yaml`, CSV files with one row for every piece of content the design needs
(every image version, comment set and caption variant), and a `NEXT_STEPS.txt`
listing what is still to add (images, avatars, AOIs, texts). It can also open an
existing `study.yaml` to edit it; comments in the file are not kept, and the CSV
files are only written if you ask for them.

### Desktop app (Windows)

The same builder also runs as a desktop app that works on study folders directly:

```powershell
. .\scripts\env.ps1
socialeyes app
```

Its **Design** tab opens a study folder (or starts a new one and saves it to
`studies/<study id>`), and **Save to study folder** writes `study.yaml` there. The
previous `study.yaml` is kept as `study.yaml.bak`. CSV files and `NEXT_STEPS.txt`
are created only if they don't exist yet, so your filled-in CSVs are never
overwritten. Each save (and the **Check study** button) also runs the compiler's
checks, the same as `socialeyes validate`: missing images, AOI sizes and mistakes
in the CSVs. They appear next to the design checks. The **Phone** tab loads the
study onto the phone and the **Data** tab copies sessions back off it (see [Running the
app](#running-the-app)). **Studies** lists every study in `studies/` as designing
(with its number of problems), ready, or collecting data (with its number of sessions),
and starts new ones, blank or as a copy of the example. **Content** lists every image,
avatar, story image, video and AOI file the study's CSVs point to, found or missing
("54 of 61 files ready").

**Studies with data are protected.** Once a study has sessions, saving an edit that would
change what participants get, or what the analysis relies on, is refused until you save it
as a new version (one click: **Save as version N+1**). That covers the seed, post order and
conditions, which comments a post has and their order, rating and recognition trials,
replaced or renamed images, story images and videos, procedure step and question ids, the
study id, and fewer participant plans. Changing text (instructions, captions, comment or
question wording) and looks saves as usual, and so does adding plans. The comparison is
against the exact build the sessions ran: `socialeyes load` keeps a copy of every build it
puts on a phone in `<data folder>/builds/`, and `socialeyes unload` analyses each session
with the build it ran. Loading (`socialeyes load`, the Phone tab) runs the same comparison,
so a breaking edit made outside the app, such as reordered rows in a CSV, is stopped
before it reaches the phone. The app
needs `pywebview`, which `setup-toolchain.ps1` installs; in an older toolchain run
`pip install pywebview`.

#### Building the installer

Researchers who don't use a terminal get a normal Windows installer
(`SocialEyes-Setup-<version>.exe`). It installs per user (no administrator rights needed)
and bundles Python, the `socialeyes` package, adb, the phone app and the example study.
The installed app keeps studies and data in `Documents\SocialEyes` (`studies\`, `data\`,
`analysis_out\`); uninstalling removes the program only, never those folders. It needs the
Microsoft Edge WebView2 Runtime, which comes with Windows 11 and up-to-date Windows 10.

```powershell
. .\scripts\env.ps1
python packaging\build.py          # release: needs the signing key (see Release signing key)
python packaging\build.py --dev    # test build with this computer's debug-signed phone app
```

The installer is written to `packaging\out\`. A `--dev` installer is for testing on your
own machines only: its phone app is signed with this computer's debug key, so phones that
get it can't take the release app later without uninstalling it, which deletes its data.
`SocialEyes.exe --selftest report.json` checks the bundled parts (builder page, adb, phone
app, example study, window toolkit) without opening a window. `setup-toolchain.ps1`
installs PyInstaller and a portable Inno Setup (no registry entries) into `.toolchain\`.

### Key ideas

- **Critical posts** carry your manipulation. **Filler posts** make the feed
  feel like a normal feed and hide the purpose of the study.
- A **factor** is something you manipulate. Each factor:
  - is **within**-subject (each participant sees every level, on different
    posts) or **between**-subject (each participant gets one level);
  - **sets** one or more post attributes: `image_version`, `label`,
    `comment_variant`, `caption_variant` or `like_count`. Each attribute can be
    set by only one factor.
- **Within-subject counterbalancing** is automatic. The levels of all within
  factors are crossed into *cells* (e.g. 2 edit levels × 2 label levels = 4
  cells). Critical posts rotate through the cells across *lists*, Latin-square
  style. Every participant sees every critical post exactly once, and across
  lists every post appears in every cell equally often. So "this particular
  photo" is never confounded with a condition.
- **Assignment** uses blocked randomisation over (between-group × list). If you
  recruit a multiple of the block size, the design is perfectly balanced. With
  2 between levels and 4 lists the block size is 8, so recruit 8, 16, 24, ...
- **Everything is seeded.** The same `seed` + participant number always gives
  the same plan, so the design can be audited and reproduced.

### Example `study.yaml`

A 2 (image: original vs. retouched, within) × 2 (label: none vs. "edited"
disclaimer, within) × 2 (comments: neutral vs. appearance, between) design:

```yaml
id: edit_label_2025
title: Retouching labels and visual attention
version: 1
seed: 20251001                 # change it and every plan changes; never change it mid-study

platform:
  name: Pictogram              # never use a real platform's name or logo
  theme: light
  participant_handle: you      # name the participant's own comments appear under

labels:
  edited:
    text: "This image has been digitally altered"
    style: banner              # banner | caption

factors:
  - name: edit
    design: within
    levels: [original, retouched]
    sets:
      image_version: "{level}"         # picks the image version called original/retouched
  - name: label
    design: within
    levels: [none, edited]
    sets:
      label: {none: null, edited: edited}   # null = no label
  - name: comments
    design: between
    levels: [neutral, appearance]
    applies_to: critical       # 'all' also switches filler comments
    sets:
      comment_variant: "{level}"

feed:
  order: shuffle
  lead_in_fillers: 2           # warm-up posts at the top
  max_run_same_cell: 2         # at most 2 critical posts in a row from the same condition
  min_fillers_between_critical: 1
  done_button_after_s: 60      # "I'm done" button appears after 60 s
  time_limit_s: null
  allow_likes: true
  allow_saves: true            # bookmark button
  allow_shares: true           # send button (only shows "Sent")
  allow_comment_likes: true    # liking comments in the comments sheet

logging:                       # what the app records besides gaze
  touches: true
  sensors: false
  screen_recording: false

procedure:
  - {id: welcome, type: instructions, title: Welcome,
     text: "Please browse the feed as you normally would."}
  - {id: cal1, type: marker_calibration, duration_s: 4}
  - {id: val1, type: validation, points: 9}
  - id: pre
    type: questionnaire
    title: Right now...
    items:
      - {id: body_sat_pre, kind: vas, text: "How satisfied are you with your body right now?",
         min_label: "Not at all", max_label: "Extremely"}
  - {id: feed, type: feed}
  - {id: cal2, type: marker_calibration}
  - id: post
    type: questionnaire
    items:
      - {id: body_sat_post, kind: vas, text: "How satisfied are you with your body right now?",
         min_label: "Not at all", max_label: "Extremely"}
  - id: ratings
    type: image_rating
    posts: critical
    items:
      - {id: attractive, kind: likert, points: 7, text: "How attractive is this person?"}
      - {id: realistic, kind: likert, points: 7, text: "How realistic is this image?"}
  - {id: recog, type: recognition, lures: both, foils: [foil01, foil02], confidence: true}
  - {id: end, type: end}

participants:
  n_plans: 120                 # plans generated up front: P001 ... P120
  id_prefix: P
  id_digits: 3
```

**Procedure step types:** `instructions`, `marker_calibration` (on-screen tags
and sync flash; do one before and after the feed), `camera_check` (researcher
framing check for the optional front camera; never shows the video),
`profile_photo` (optional selfie as the participant's profile picture, with `text`
and `allow_skip`; see below),
`validation` (look-and-tap
dots, 5/9/13 points, used to measure gaze accuracy), `questionnaire` (items of
kind `vas`, `likert`, `choice`, `text`, `number`), `feed` (exactly one),
`image_rating`, `recognition` (old/new test with `foils` and/or the
`alternate_version` of a seen image as lures) and `end` (must be last).

**Profile photo.** A `profile_photo` step lets the participant take a selfie with the
front camera; it replaces the default avatar in their story, the profile tab and their
comments. The photo is kept only in the app's memory and deleted when the session ends
(it is never saved to the phone or the session data); the log records only whether a
photo was taken, skipped or the camera was unavailable. Seeing one's own face can itself
affect body-image measures, so keep the step the same across conditions or pilot it.
If the study has this step, the setup screen offers **Allow camera** so the researcher
grants camera access once and participants never see Android's permission prompt.

The schema rejects typos and impossible designs with a clear error. Unknown
keys, a factor without two levels, two factors setting the same attribute, and
a missing feed step are all errors. The compiler then cross-checks the CSVs
against the design: missing image versions or comment variants, unknown
accounts, missing files or AOIs, feed constraints that can't be met.

```powershell
socialeyes validate studies/my_study     # lists every problem, with file and line
socialeyes compile studies/my_study      # writes build/my_study/ for the phone app
```

`compile` writes one plan per participant (`plans/P001.json`, ...) with their
conditions, feed order and trial orders, plus `study.json`, the media, the
normalised AOIs and the screen AprilTags. Plans depend only on `seed`, so
compiling again gives the same plans.

---

## What gets recorded

Besides Neon's gaze and scene video, the app writes a session folder
(format: [`docs/EVENT_LOG.md`](docs/EVENT_LOG.md)):

| stream | contents | why |
|---|---|---|
| viewport | where every post, image, label, caption and comment block is on screen, each frame it moves | maps gaze and touches to content; exact time on screen per post |
| touches | every finger down / move / up | scrolling behaviour, taps, double-tap likes, a finger covering an AOI |
| events | procedure steps, likes, comment opens, profile taps, label taps, answers (incl. changes and response times) | engagement measures, ratings, recognition |
| quality | app sent to background, interruptions (notification sounds, calls, alarms, notification shade), Do Not Disturb, dropped frames, rotation, brightness, battery, Neon status | flag or exclude bad sessions |
| optional | motion sensors; screen recording (pilots); **front camera** video of the face (facial expressions) | switched on per study under `logging:` |

All timestamps share one clock with the sync patch, so everything lines up with
gaze. Analyse a session with:

```powershell
socialeyes session data/my_study/P001/<session> --build build/my_study
```

This writes per-session tables: `strokes.csv` (tap, double tap, long press,
scroll, fling, pinch), `exposure.csv` (seconds each post and image was on
screen), `touch_targets.csv` (every touch mapped to post, image pixel and AOI),
`occlusion.csv` (when a finger probably covered an AOI), `interactions.csv`
and `quality.json`.

Until the app exists, `socialeyes simulate build/my_study P001 <folder>` writes
a realistic fake session to try the analysis on.

> [!NOTE]
> **Front camera:** Android shows a camera indicator while recording, and a
> camera pointed at you may make you more aware of your appearance, which is
> close to what body-image studies measure. Pilot with and without the camera
> before using it. Details: [`docs/EVENT_LOG.md#front-camera`](docs/EVENT_LOG.md#front-camera).

---

## Defining areas of interest (AOIs)

AOIs are polygons or rectangles in the **image's own pixel coordinates**, so
they don't depend on screen size or scroll position. Draw them once per image
version.

**Option A: LabelMe (recommended).** [LabelMe](https://github.com/wkentaro/labelme)
is a free annotation tool (`pip install labelme`). Open each image, draw
polygons or rectangles, and give each one a name such as `face`, `waist` or
`legs`. Save the `.json` next to the image. SocialEyes reads it directly.

**Option B: hand-written JSON.**

```json
{"width": 1080, "height": 1350,
 "aois": [{"name": "face",  "rect": [400, 80, 680, 380]},
          {"name": "waist", "polygon": [[380, 700], [700, 700], [720, 860], [360, 860]]}]}
```

> [!IMPORTANT]
> **Overlapping AOIs:** a gaze point gets the *first* AOI in the file that
> contains it. List small AOIs (face) before larger ones that enclose them
> (whole body).

> [!TIP]
> Use the **same AOI names** on the original and edited versions of an image,
> so they can be compared directly.

---

## Eye-tracking hardware setup

Designed for **Pupil Labs Neon**. Other head-mounted trackers with a scene
camera should work once the analysis pipeline exists, but we haven't tested any.

### Phone-case markers

Glasses-based gaze lives in the coordinates of the scene camera. To know
*where on the screen* someone looked, we put
[AprilTag](https://april.eecs.umich.edu/software/apriltag) markers (family
`tag36h11`, the same family Pupil Labs' Marker Mapper uses) around the phone:

- **Case tags** (default ids 10-15) are printed on a frame around the phone
  and are visible all the time.
- **Screen tags** (default ids 0-3) are shown on screen during
  `marker_calibration` steps. The analysis uses them to learn exactly where the
  case tags sit relative to the screen pixels, so you don't need to stick the
  frame on with millimetre precision.

Generate a printable frame at 1:1 scale (measure your phone's screen first):

```powershell
socialeyes case-sheet --width-mm 70 --height-mm 152 --study studies/my_study -o case_sheet.svg
```

Print it at **100% scale** (no "fit to page"), check that a tag's black border
measures `case_tag_size_mm`, and mount it flush with the screen.

### Clock synchronisation

A small patch in the top corner of the screen (16 dp by default, a barely
visible dark-grey flicker) shows a pseudorandom binary code. The app logs when
each bit happens and the scene camera films it. Matching the two signals gives
a sub-frame offset between the phone clock and the glasses clock, with no
reliance on network time. Settings live under `display.sync_patch` in
`study.yaml`.

---

## Running the app

The app is a work in progress (see [Feature status](#feature-status)). To build it and
try the example study on an Android phone (Android 10 or newer, USB debugging on):

```powershell
. .\scripts\env.ps1
cd android; .\gradlew assembleDebug; cd ..          # first build downloads Gradle and libraries
socialeyes phone-check studies/example              # is the phone ready? (changes nothing)
socialeyes load studies/example                     # check, compile and copy the study to the phone
```

`socialeyes load` (and the desktop app's **Phone** tab, which does the same) checks the
study and the phone, installs the SocialEyes app if it is missing, compiles the study and
copies it to the phone, then checks every file's SHA-256 on the phone before it replaces
the old copy. It stops (**BLOCK**) when the study has errors, there is not enough storage,
or the phone still holds sessions of a *changed* version of the study (unload them first).
It only warns (**WARN**, load with `--anyway`) about a battery under 50%, Do Not Disturb
being off, or a display or font size changed from the phone's default. A newer app is
installed only with `--update-app`; the app is never uninstalled, because that deletes
its data. With several phones connected, pick one with `--serial` (see `adb devices`).
If the study records the front camera, loading also gives the app camera permission.

#### Release signing key

Phones can only update the app if every version is signed with the same key. Debug
builds use this computer's debug key, which is fine for development. For releases
(the desktop app's installer), create the project key **once**, keep it out of git
(`.gitignore` covers it) and back it up with its passwords somewhere safe. If it is
lost, phones can't install updates without uninstalling the app, which deletes its data.

```powershell
. .\scripts\env.ps1
keytool -genkeypair -v -keystore android\socialeyes-release.jks -alias socialeyes `
  -keyalg RSA -keysize 4096 -validity 10000
```

Then create `android\keystore.properties`:

```
storeFile=socialeyes-release.jks
storePassword=<the keystore password>
keyAlias=socialeyes
keyPassword=<the key password>
```

and build with `.\gradlew assembleRelease`. A phone that has a debug build can't be
updated to a release build in place (different keys): unload its sessions, uninstall
SocialEyes on the phone, then load again.

Open **SocialEyes** (the app drawer, or tap **Add to home screen** on its setup screen once
for a home-screen shortcut), pick the study and a participant, and start. Press Back to stop a
session. The first time the app goes full screen, Android shows a "Viewing full screen"
notice; tap **Got it** during a test run so participants never see it.

To unlock a test phone from the computer, put its PIN in `phone-pin.local` in the project
root (git-ignored; never commit it) and run `.\scripts\unlock-phone.ps1`.

Sessions are saved on the phone. Copy them off with `socialeyes unload` (or the desktop
app's **Data** tab, which does the same):

```powershell
socialeyes unload studies/example
```

For every session of the study on the phone it reads each file's SHA-256 on the phone,
copies the session into the study's data folder and checks every file, makes the second
copy if one is set (and checks it), runs the session analysis (`analysis_out/<study>/…`)
and records the session in `sessions.csv` in the data folder. **Only then** is the session
deleted from the phone; if anything fails, it stays there. A session that hasn't ended
while SocialEyes is open on the phone may still be recording, so it is copied but left on
the phone until you close the app and unload again.

The data folder is `data/<study id>` unless you choose another one, for example an
encrypted or university drive. That choice, and the optional second copy, belong to
this computer, not the study:

```powershell
socialeyes folders studies/example --data E:\secure\example --second-copy \\server\lab\example
socialeyes folders studies/example --second-copy none      # stop making a second copy
```

`sessions.csv` has one row per session: participant, start time, phone, app version,
completed or not, duration, group, the study build it ran (`package_sha256`), quality
warnings, a flag when a participant ID was used twice, and a `notes` column. Notes and any
columns you add in Excel are kept when the app updates the file (close it in Excel first).

To analyse a single session by hand:

```powershell
socialeyes session data\example\P001\<session folder> --build build\example
```

### What the app doesn't do yet

The setup screen lists the parts of a study the app can't run yet. Steps it can't show
appear as a "not available yet" screen with a Skip button and are still logged, so the
rest of the session works.

| Missing | What happens now |
|---|---|
| `logging.screen_recording` | not recorded |
| Neon control (start/stop recording, `neon` events, `neon.required`) | sessions run without the glasses being controlled; start the Neon recording by hand |
| Silent notifications | only notifications that make a sound are logged as interruptions; turn on Do Not Disturb for sessions (the setup screen reminds you when it is off) |
| Testing on more phones | tested on a Pixel 3 (Android 12): a full session runs and `socialeyes session` reads it; other screen sizes and Android versions are untested |

**How the feed differs from the real app.** It copies the look of a photo-sharing feed
(stories row, post header, thin-line icons, likes, captions with "… more", comments,
"2 days ago", tab bar) under the neutral name Pictogram and a free script font, with no
real logos. Liking, saving (bookmark), sending (shows "Sent"), captions and comments work, and the
Home tab scrolls back to the top. With a `stories.csv`, tapping a story circle opens the
account's stories full screen (progress bars, tap right/left to skip/go back, hold to
pause, swipe sideways to turn, cube-style, to the next/previous account or drag part way
to peek, swipe down to close, 5 s each by default via `feed.story_duration_s`). The
story's reply bar works too: typing a reply pauses the story and sends it (logged, with
every draft edit, under `feed.allow_comment_typing`), the heart likes the story and the
paper plane shows "Sent"; watched
accounts get a grey ring.
With a `reels.csv`, the Reels tab opens full-screen vertical videos (swipe up/down, loop,
muted until tapped, hold to pause, double-tap or heart to like, send shows "Sent"), with
the playback position logged on every frame so gaze can be mapped to video frames. The
top-bar icons and the other tabs are for the look only. Each post shows its first 2 comments; with more, "View all N comments"
opens the comments sheet, so use the `order` column in `comments.csv` to choose which
comments are visible without a tap. The sheet opens at half height and can be pulled up
over the whole screen; comments in it can be liked, and their positions are logged so
gaze can be mapped to single comments. With `feed.allow_comment_typing: true`
participants can also write comments and reply ("Replying to …", shown indented under the
comment); their comments appear under `platform.participant_handle` with a default
avatar, in the sheet and under the post. The posted text and every change of the draft
are logged (`comment_submit`, `comment_edit`). `feed.allow_likes`, `allow_saves`,
`allow_shares`, `allow_comment_likes` and `allow_comment_typing` switch the actions on
or off per study.
The "I'm done" button sits in the top bar so it never covers a post.

`session.json` records only what was actually recorded: screen recording is always
`false` there for now.

---

## Using the Python package today

With the toolchain active (`. .\scripts\env.ps1`), these pieces work:

```python
import yaml
from socialeyes.study.schema import Study
from socialeyes.study.design import cells, assignment_schedule

study = Study.model_validate(yaml.safe_load(open("study.yaml", encoding="utf-8")))

print([c.key for c in cells(study.within)])
# ['edit=original|label=none', 'edit=original|label=edited', ...]

for a in assignment_schedule(study, 8):        # first balanced block
    print(a.participant_index, a.between, "list", a.list)
```

```python
from socialeyes.study.aoi import load_aoi_file
aois = load_aoi_file("images/post07_retouched.json")
print(aois.label_points([500, 540], [200, 780]))   # ['face' 'waist']
```

---

## Repository layout

```
environment.yml          conda env: Python stack, JDK 17, R + lme4
scripts/
  setup-toolchain.ps1    installs .toolchain\ (conda env + Android SDK)
  env.ps1                dot-source to activate the toolchain
python/
  pyproject.toml         the `socialeyes` Python package
  src/socialeyes/
    markers.py           AprilTags, printable case sheet
    study/schema.py      study.yaml format
    study/design.py      counterbalancing, assignment, feed ordering, sync code
    study/aoi.py         areas of interest
    study/compiler.py    loads + cross-checks a study folder, writes plans
    session/             reads session logs: gestures, exposure, touch->AOI,
                         occlusion, quality; simulate.py writes fake sessions
    desktop/             the desktop app (`socialeyes app`): window, study folders, study list,
                         content checklist
    phone/               adb, phone readiness checks, loading studies (`socialeyes load`),
                         unloading sessions (`socialeyes unload`)
    settings.py          this computer's data / second-copy folders per study
    cli.py               the `socialeyes` command
  tests/                 pytest suite (runs against studies/example)
android/                 the SocialEyes Android app (Kotlin, Jetpack Compose)
builder/
  index.html             the experiment builder (open in a browser; built file)
  src/                   its source: core.js (logic), ui.js (form), page.html
  build.py               stitches src/ and vendor/js-yaml into index.html
studies/example/         a complete worked example with placeholder images
docs/
  STUDY_DESIGN.md        CSV reference, balance rules, compiler output
  EVENT_LOG.md           session log format (app <-> analysis contract)
  assets/                logos, banners, avatar, favicons (PNG + SVG); lavender palette:
                         #6750A4 primary, #21005D deep purple, #A28BE0 on dark backgrounds
```

---

## Ethics and data handling

> [!CAUTION]
> **Participant data must never be committed.** `data/`, `build/` and
> `analysis_out/` are git-ignored on purpose. Store data according to your
> ethics approval.

- **Consent and anonymisation are the researcher's responsibility.** SocialEyes
  assumes participants have already given consent for everything a study
  enables (eye tracking, touch logging, front camera video), and that the
  researcher anonymises the data as their ethics approval requires. The app
  does not ask for or check consent itself.
- The app uses a **fictional platform name and branding**. Don't add real
  logos or trademarks.
- Use only images you have the rights to use for research. Make sure your
  consent and debriefing cover image manipulation, deception about the study's
  purpose (if any), and eye tracking.
- Studies on body image can affect vulnerable participants. Consider screening,
  a debrief that explains the image editing, and signposting to support
  resources.

---

## Roadmap

Roughly in order:

- [x] Study schema, counterbalancing, AOIs, AprilTag markers, sync code
- [x] Project-local toolchain setup (Windows)
- [x] **Study compiler** + `socialeyes` CLI (`validate`, `compile`, `case-sheet`)
- [x] A complete **example study** with placeholder images
- [x] Finalise the CSV formats: version 1 (`docs/STUDY_DESIGN.md`)
- [x] Session **log format** (version 1, `docs/EVENT_LOG.md`) and touch / scrolling / quality analysis
      (tested on simulated sessions)
- [ ] The **Android app**: feed rendering, procedure steps, event logging
      (per `docs/EVENT_LOG.md`), sync patch, Neon real-time API control
      (in progress: the feed, logging, sync patch, calibration, validation, questionnaires,
      ratings and recognition are built)
- [ ] **Analysis pipeline**: tag detection → screen homography → scroll-aware
      mapping of gaze to post and image pixels → AOI fixation metrics
- [ ] **R templates** for the standard mixed models
      (`dwell ~ edit * label + (1|participant) + (1|post)`)
- [ ] More tests and docs, macOS/Linux setup
- [x] **Experiment builder**: a form that walks you through the study's decisions
      (factors, procedure, feed, logging) and writes `study.yaml` and CSV skeletons for you
- [x] Commenting and replying in the comments sheet
- [x] Stories (`stories.csv`, story viewer, story events and gaze-mappable story images)
- [x] Reels (`reels.csv`, Reels tab with video playback, reel events, `video.csv`)
- [ ] **Next: SocialEyes desktop app (Windows)**: one window that takes a study from design
      to data, for researchers who don't use a terminal. Python + a small built-in browser
      window (pywebview) showing the existing builder pages, calling the `socialeyes` package
      directly; packaged as one installer / `.exe` that includes adb, so no Python, Android
      Studio or toolchain is needed. Tabs:
  - [x] **Studies**: a list of your study folders with their status (designing, ready,
        collecting data, number of sessions); new study from blank or from the example
  - [x] **Design**: the experiment builder, editing the study folder in place (no zip); the
        compiler's own checks (missing images, AOI sizes, CSV mistakes) shown next to the
        design checks. The standalone `builder/index.html` keeps working in a browser
  - [x] **Content**: checklist of every image, avatar, video and AOI the design needs, found
        or missing ("14 of 38 files ready"); later, drop files onto their slot
  - [x] **Phone (experiment loader)**: pick a study → validate, compile and copy it to the
        phone in one step; install or update the app if needed; check the phone is ready
        (storage, battery, Do Not Disturb, camera permission). Load only unlocks when the
        study validates
  - [x] **Data (data unloader)**: copy every new session off the phone, check each file
        arrived intact (checksums), then delete it from the phone so participant data never
        stays on the device; run the quality checks and show a summary; keep a session
        register per study (participant, date, phone, completed, warnings; flags participant
        IDs used twice); optionally make a second copy (e.g. a network or encrypted drive);
        once Neon is integrated, also collect the matching Neon recording
  - [x] **Protection once data exists**: when a study has sessions, warn about or lock
        changes that would break it (seed, post order, image file names, comment order) and
        bump the study version when it is edited
  - [ ] Order: Design in the app and saving to the folder → Phone → Data → Studies list →
        Content checklist → protections
- [ ] **Easier for non-technical users** (extra features, mostly in the desktop app):
  - [ ] **AOI drawing tool**: open each critical image and draw rectangles or polygons
        over the regions (face, waist, ...), name them, and the app writes the AOI file
        with the right image size. Optional **Segment Anything (SAM)** assist: click on a
        region and SAM proposes its outline, which becomes an editable polygon. SAM is an
        optional download that runs locally (no images leave the computer); without it,
        drawing by hand still works. To decide: which SAM version (SAM 2 or a small, fast
        variant for CPU-only laptops), how it is installed, and how masks are simplified
        into polygons
  - [ ] **Match dropped images automatically**: drag a folder of images onto the app; it
        matches files to the slots the design needs by name (`crit01_retouched.jpg` -> the
        retouched version of post crit01), copies them into the study folder, lists what is
        still missing and which files matched nothing (to assign by hand), and offers to
        resize images that are far too large or the wrong shape
  - [ ] **Phone setup wizard**: a one-time guide with pictures for turning on developer
        mode and USB debugging, installing the app and allowing the camera; it detects the
        phone's state and shows the next step
  - [ ] **Feed preview**: see posts, labels, comments and stories as the participant will,
        in the app or sent to the phone, before running anyone
  - [ ] **"Fix it" buttons** on the checks that can be fixed automatically ("Use 12 plans",
        "Add a camera check step", "Add a marker calibration before the feed")
  - [ ] **Session-day mode**: a "Next participant" button with the next unused ID from the
        session register; a pre-flight checklist (battery, storage, Do Not Disturb, glasses
        connected); locks the phone into the app (Android screen pinning) during a session;
        unload at the end of the day
  - [ ] **Plain language everywhere**: hover explanations for terms (within-subjects, AOI,
        seed, filler, ...), rarely used settings behind an "Advanced" switch, YAML never
        shown unless asked for, error messages that say what to do
  - [ ] **Safety nets**: undo, autosave, and a saved copy of the study each time it is
        loaded onto a phone, so you can always see and restore what participants ran
  - [ ] **One-click tidy data export**: combine every session of a study into tables ready
        for Excel, SPSS or R: one row per participant x post (group, the post's conditions,
        time on screen, likes, comment opens, ratings, recognition answers, and later gaze
        dwell per AOI and time to first fixation) and one row per participant
        (questionnaire answers, group, session length, quality flags for exclusions); the
        R templates read these files
  - [ ] **Short guides**: a printable "running a session" sheet and short screen
        recordings of the main tasks (design a study, add content, load a phone, unload data)
- [ ] **Different phones and screen sizes**: run and test on other Android phones (Samsung,
      Pixel, Motorola, ...), Android 10-15, and small to large screens (about 5.5" to 6.9",
      tall and short aspect ratios, notches and camera cutouts, gesture and button
      navigation, 60-120 Hz). Includes: a test matrix and a short device report the loader
      writes for each phone; layouts checked at the phone's display size and font size
      settings (logged in session.json, with a warning when they are not the default);
      on-screen AprilTag and sync patch sizes checked on each screen; phone-case marker
      sheets per phone model (`socialeyes case-sheet` for its dimensions); front-camera
      fallbacks for other camera drivers (the Pixel 3 needed a hidden preview stream);
      manufacturer battery savers that stop apps (Samsung, Xiaomi) handled by the loader's
      readiness check. Tablets and foldables are out of scope at first
- [ ] *Stretch:* **generated content**: draft comments and account usernames automatically,
      optionally based on what each post's image shows, written into `comments.csv` /
      `accounts.csv` for the researcher to review and edit before compiling

---

## Contributing and contact

This is an early-stage research tool. Issues, suggestions and pull requests are
welcome, especially from labs planning similar studies. Please open an issue
before large changes so we can agree on the design.

Maintainer: [Cam Hickling](https://github.com/CamHickling).

*License: to be decided. Please ask before reusing this code in published work.*

<br>

<div align="center">
  <img src="docs/assets/socialeyes-mark.svg" width="56" alt="SocialEyes mark">
  <br>
  <sub><b>SocialEyes</b> · gaze &amp; attention in social media</sub>
</div>
