# Saturday 21 Nov 2026: test day (installer 0.1.0 with app 0.3.13, glasses, blinding)

Paste into Linear as a new issue (milestone M10 Pilot; links: CAM-228, CAM-227, CAM-219, CAM-187,
CAM-211). Tick each box as you go and write what you saw next to any box that fails. Anything that
fails: screenshot it, note the time, carry on with the next part unless the part says stop.

**Goal:** know whether this installer and phone app can go to the colleagues running the pilots.

**Takes:** about 3 to 3.5 hours with breaks. Parts A–C need no glasses, so do them first.

## What to have ready

- [ ] Laptop on mains power. The installer `packaging/out/SocialEyes-Setup-0.1.0.exe` (208 MB, built 19 Nov)
- [ ] Motorola Edge 40 Pro charged above 80 %, its USB cable, PIN at hand
- [ ] Neon glasses + their cable; Neon Companion open on the Motorola, wearer profile **SocialEyes**
- [ ] A ruler with mm marks
- [ ] A timer (phone or kitchen timer, not the Motorola)
- [ ] A second person to wear the glasses for part F (optional; skip F3 without one)
- [ ] This sheet printed or open on another screen, and a pen
- [ ] A test sheet for notes: one line per session with time, participant id and anything odd

**Never uninstall the SocialEyes app from the phone:** it deletes the data folder. Updates go over
the top (the installer and Phone setup already do this).

---

## Part A: install the new desktop app (15 min)

1. [ ] Close SocialEyes if it is open. Note the version in **Settings > Apps > Installed apps >
       SocialEyes** (expected: 0.1.0, built 22 Oct).
2. [ ] Note how many studies the **Studies** page lists and the session counts for `pilot_neon`
       (expected: 2 sessions) and `example` (3). Write them here: ________
3. [ ] Run `SocialEyes-Setup-0.1.0.exe`, accept the defaults, finish with **Launch SocialEyes** ticked.
4. [ ] **Studies** lists the same studies with the same session counts as in step 2 (installing
       over the top must not touch studies or data).
5. [ ] The three guide links at the bottom of **Studies** open: *Your first study*, *Running a
       session (printable checklist)*, *Study files*.
6. [ ] Self-test of the installed copy. In PowerShell:
       ```powershell
       & "$env:LOCALAPPDATA\Programs\SocialEyes\SocialEyes.exe" --selftest "$env:USERPROFILE\Desktop\selftest.json"
       ```
       (if it isn't there, right-click the Start menu shortcut > **Open file location** for the path).
       Open `selftest.json`: every check says `"ok": true` and `apk` says `"version": "0.3.13"`.

## Part B: phone app update and Phone setup (20 min)

1. [ ] Plug the Motorola in by USB and unlock it. Allow USB debugging if it asks.
2. [ ] In SocialEyes: **Studies > pilot_neon > Open**, then the **Phone** tab.
3. [ ] **Phone setup** finds the phone (the first line goes green). Write down each line that is
       not green and what it says: ________
4. [ ] If it offers **Install/Update the SocialEyes app**, do it. Afterwards the phone app shows
       version **0.3.13** (study list screen, bottom).
5. [ ] On the phone, the sessions copied earlier are still there (the app was updated, not
       reinstalled): open SocialEyes; `pilot_neon` shows its earlier sessions as used ids.
6. [ ] **Check screen size** (CAM-227) on the phone: measure both lines with the ruler, type the
       lengths in mm, save. Write the two lengths: ________ / ________
7. [ ] Back on the laptop: **Check again**. The ruler line in Phone setup is now green.
8. [ ] **Load onto phone**. Expected: no red lines. Note any yellow warnings (corners, cut-out,
       bar row room): ________
9. [ ] On the phone, the study list shows **pilot_neon** at the top / selected (the one loaded last).

## Part C: Android golden session (20 min, no glasses)

Checks the release phone app end to end before anyone else uses it. It uses a throwaway copy
(`android_golden`) and doesn't touch real studies or data.

1. [ ] Phone unlocked, screen timeout at 10 min (Settings > Display), Do Not Disturb on.
2. [ ] In PowerShell, from the SocialEyes folder:
       ```powershell
       . .\scripts\env.ps1
       adb devices        # note the Motorola's serial
       python scripts\android_golden.py --serial <serial>
       ```
3. [ ] Don't touch the phone while it runs. It ends with a pass line and exit code 0.
       If it fails: copy the last 30 lines of output into the issue. Don't run `--update`.
4. [ ] On the phone, go back to the study list. `pilot_neon` is still there next to `android_golden`.

## Part D: the glasses run (CAM-228 step 1, about 45 min)

The first full run of `pilot_neon` at the chosen settings with tags during validation. It answers:
gaze accuracy and offset at brightness 0.30 / auto exposure -32, and whether the phone-side
features (live validation check, ruler correction, per-model settings) work with the real glasses.

**Set up**

1. [ ] Glasses plugged into the Motorola, Companion open, wearer **SocialEyes** chosen,
       Companion's own *offset correction* left at none (SocialEyes corrects offset itself).
2. [ ] Room: no window or bright lamp behind or reflected in the phone. Write the room: ________
3. [ ] Phone: Do Not Disturb on, screen clean, battery above 70 %. Note the battery %: ____ and
       glasses' phone temperature if Companion shows it.

**Run** (you are the participant; the ids follow on from the last used, probably P003)

4. [ ] SocialEyes > **pilot_neon** > **Start the next participant**. Write the id: ____
5. [ ] **Eye tracker check**: every line ticks green (glasses, battery, storage, streams). Tick the
       checklist, **Start recording**. In Companion, a recording starts within ~3 s.
6. [ ] Per-model settings (CAM-227): the screen brightness looks dimmer than usual (0.30). In
       Companion, while recording, the scene camera is on auto exposure with brightness -32.
       (If Companion's settings can't be opened during the recording, check them in step 12.)
7. [ ] **Marker calibration** (4 s): hold the phone normally, look at the screen.
8. [ ] **Validation, 9 dots (val1)**: look at the centre of each dot until it moves. The tags show
       in the top and bottom bars during the dots (new since 21 Oct).
9. [ ] Live validation check (CAM-219): after the dots, the app shows a gaze accuracy line. Write it:
       ________. If it says it couldn't reach the gaze stream, note that (this is still a pass of
       the rest).
10. [ ] Questionnaire (any answers), then the **feed**: scroll it naturally for at least 3 min. Open
        the comments on 2 posts, like 2 posts, write one comment, open a story. Hold the phone
        the way you would normally, not posed.
11. [ ] **Validation again (val2)**, the rest of the steps, **Thank you!**. The recording stops in
        Companion by itself within ~5 s.
12. [ ] Companion: the recording is there, its length matches (note it: ____ min). The scene camera
        exposure settings went back to what they were before (step 6's note says how it was).

**Copy and analyse on the laptop**

13. [ ] Plug the phone in. **Data > Copy from the phone**. The new session says *copied and
        checked*, and a line says its **Neon recording** was copied (CAM-164; it can take a few
        minutes). Write what the Neon line says: ________
14. [ ] **Analyse eye tracking** (a few minutes). For the new session note:
        - tracked share of the feed: ____ % (21 Oct: 97.6 %)
        - validation accuracy val1: ____ ° / val2: ____ ° (target: under 1°)
        - offset applied: ____
        - number of fixations: ____
15. [ ] Pass if: tracked share ≥ 90 %, accuracy ≤ 1° after offset correction in both validations,
        and val2 isn't more than 0.5° worse than val1 (drift). Otherwise: note it, carry on, we
        look at the recording together.

## Part E: what a researcher can see before unblinding (30 min)

Everything here is done **without ticking Unblind**, on `pilot_neon` (its data is your own test
data, so seeing real conditions here does no harm: we are checking what *would* be seen).
For each item write **hidden** (codes / nothing) or **visible** (real condition names, image
versions, or anything that tells you which condition is which).

1. [ ] **Data > Make tables** (Unblind not ticked). Open the `export` folder (link under the button).
   - [ ] `BLINDED.txt` exists.
   - [ ] `by_session.csv`: group column shows codes (X, Y), not `neutral` / `appearance`.
   - [ ] `by_item.csv`: `edit`, `label`, `comments` columns show codes (P, Q…); `cell` shows
         a, b, …; `image_id`, `label_shown`, `comment_variant` are empty.
   - [ ] `by_condition.csv`: conditions are A, B, …
   - [ ] `by_comment.csv`: `comment_variant`, `comment_id`, `reply_to` empty.
   - [ ] `codebook.csv` says the coded columns are coded.
   - [ ] `exploration.html`: conditions are *condition A, B, …*, groups *X, Y*; nowhere on the
         page does an image, image name, label text or comment text appear.
2. [ ] Search the export folder for the giveaway words. In PowerShell:
       ```powershell
       Select-String -Path "<export folder>\*" -Pattern "retouched","original","appearance","neutral","edited" -List
       ```
       Expected: no matches except in `BLINDED.txt` / codebook explanations. Write any other: ________
3. [ ] Blinded heatmaps. The button says **Make heatmaps (blinded)** and there is no *by* menu.
       Make them, then **Open heatmaps (blinded)**:
   - [ ] The yellow disclaimer is at the top ("for checking the eye tracking, not for results").
   - [ ] One map per **post** (headings "Post crit01", …), captions say "all conditions together".
   - [ ] No condition names, no "minus" / difference maps, no image names anywhere on the page.
   - [ ] The folder (`analysis\heatmaps_blinded`) holds `<post>.png`, `index.html`, `BLINDED.txt`
         and **no** `aoi_dwell.csv`.
   - [ ] Run the PowerShell search from step 2 on this folder too: no matches.
4. [ ] The analysis folder per session (`analysis\<participant>\<session>\`): `fixations.csv`
       has `image_id` (e.g. `crit03_retouched`). Visible by design, listed here so we decide
       whether that's acceptable (see the blinding discussion).
5. [ ] The Data page's blinding card says **Blinded** and **Never unblinded** (for pilot_neon).
6. [ ] **Unblind…** opens the form with the yellow disclaimer. **I understand, unblind** stays
       greyed out:
   - [ ] with the name empty and the phrase typed right
   - [ ] with a name and the phrase mistyped (try `unblind pilot-neon` and `Unblind pilot_neon`)
   - [ ] it turns red only with a name **and** `unblind pilot_neon` exactly.
   **Cancel**: the form closes, nothing changes, and no `unblinding.csv` appears in the data folder.
7. [ ] Unblind for real with your name. Expected: the tables are made again at once with real
       names (`BLINDED.txt` gone), the card says **Unblinded by <your name>**, and it lists the record.
8. [ ] Open `unblinding.csv` in the data folder: one row with the date and time, your name, your
       Windows user, the computer's name, `pilot_neon`, version 1, "tables and exploration page" and the
       number of sessions.
9. [ ] **Make heatmaps** now has the *by* menu. Make them by condition: real names and difference
       maps, `aoi_dwell.csv` written in `analysis\heatmaps`, and a second row in `unblinding.csv`
       ("heatmaps by cell").
10. [ ] **Back to blinded**, **Make tables**: blinded again (`BLINDED.txt` back). The card still
        says when it was first unblinded and by whom.
11. [ ] Close and reopen SocialEyes, open pilot_neon's Data tab: it starts **Blinded** (unblinding
        is asked for again each time), and the record of earlier unblinding is still shown.

## Part F: endurance and failure checks (CAM-228, about 50 min)

1. [ ] **Long session (heat, frame rate):** one more pilot_neon session, feed scrolled for
       **15–20 min** (set the timer; the Done button shows after 60 s, ignore it until the timer
       goes). Note the battery before/after: ____ / ____, and whether the phone or glasses got
       hot (Companion warning?). After **Copy** + **Analyse eye tracking**, note the tracked share
       for the first and last 5 minutes if the summary gives it, and the scene video's frame rate
       (Companion's recording info, or ask Claude to read it from the recording): ____ fps.
2. [ ] **Unplug the glasses mid-session:** start another session, at about 1 min into the feed
       unplug the glasses for ~10 s, plug them back in, carry on to the end. Expected: the app
       carries on, the session records the disconnect (Data tab: a warning on that session; hover
       to read it), the recording is still saved in Companion (possibly as two parts). Note what
       Companion and the app did: ________
3. [ ] **Second wearer or another room** (optional): one short session (3 min feed) with someone
       else wearing the glasses, or you in a different room/light. Note accuracy after offset and
       tracked share: ____ / ____
4. [ ] **Continue without eye tracking:** start a session with the glasses unplugged. At the eye
       tracker check choose **Continue without eye tracking**. Expected: calibration and
       validation dots are left out, the feed runs normally, Copy from the phone marks it as
       without eye tracking.

## Part G: wrap up (10 min)

1. [ ] **Data > Copy from the phone** once more: every session says *copied and checked*. Don't
       clear the phone.
2. [ ] Charge the phone and glasses.
3. [ ] Post the filled-in sheet (or photos of it) on the Linear issue; mark CAM-228 steps done that
       passed.
4. [ ] Decide with Claude: go / no-go for handing the installer to the pilot teams, and what has to
       change first.

## Pass / fail summary

| Part | Pass if | Result |
|---|---|---|
| A Install | studies and data intact, self-test all ok | |
| B Phone | app 0.3.13, ruler saved, load with no red | |
| C Golden | script passes | |
| D Glasses | ≥ 90 % tracked, ≤ 1° after offset, live check shown | |
| E Blinding | tables + exploration hidden; heatmap gap recorded (or fixed) | |
| F Endurance | 15–20 min with no drop in tracking or fps; unplug handled | |
