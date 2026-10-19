# Your first study

From nothing to the first exported tables, with the desktop app (Windows). Every step can also be
done on the command line (`socialeyes --help`); the README has the details.

## 1. Install

1. Run `SocialEyes-Setup-<version>.exe`. It includes everything: Python, the phone app and adb.
2. On the Android phone (Android 10 or newer): **Settings > About phone**, tap **Build number** seven
   times, then **Settings > System > Developer options > USB debugging** on.
3. Plug the phone in and tap **Allow** when it asks about USB debugging.

## 2. Make the study

1. Open **SocialEyes**. On **Studies**, either **New study**, or **Copy** the example under a new
   study id (the example is a complete 2 x 2 x 2 study with placeholder images: the quickest way to
   see everything working).
2. Work through the **Design** steps on the left: **Basics**, **Design** (your factors: what changes
   between conditions), **Content** (how many posts, accounts, stories), **Feed**, **Procedure** (the
   screens participants go through), **Recording**, **Participants**. The panel on the right lists
   problems as you go; each one links to the step it's about.
3. **Save**. This creates the study folder with CSV files to fill in and a `NEXT_STEPS.txt`.
4. Put your images, avatars and videos in the folder and fill in the CSV files (posts, captions,
   comments). The **Content** step shows which files are still missing ("54 of 61 files ready").
5. AOIs (areas of interest) for the critical posts' images: **Draw AOIs** in the **Content** step
   draws face, hair, upper body, waist, legs and body automatically; check them on the review page
   and correct any in [LabelMe](https://github.com/wkentaro/labelme). Other shapes can be drawn in
   LabelMe from scratch.
6. **Check study** until it says everything checks out.

## 3. Try it yourself

1. **Phone**, then **Load onto phone**. It installs the app if needed and checks every file arrived.
2. On the phone, open **SocialEyes**, tap your study and **Start the next participant**. Go through
   the whole session as a participant would. Note what's unclear.
3. Change what needs changing in **Design**, **Save**, and load again. Before anyone takes part,
   edits are free; once sessions exist, changes that would break them ask for a new version.

## 4. Collect data

Follow [Running a session](RUNNING_A_SESSION.md). At the end of each day: **Data**, **Copy from the
phone**.

## 5. Look at the data, without looking at the results

1. **Data**, then **Make tables**. This writes, in the `export` folder of the study's data folder:
   - `by_session.csv`, `by_item.csv`, `by_condition.csv`: one row per session, per post seen, and per
     condition, ready for Excel, SPSS or R
   - `codebook.csv`: what every column means
   - `exploration.html`: data quality and each measure's distribution, with the conditions shown
     as **condition A, B, …** so you can check the data without seeing the results
2. Write your analysis plan, including which sessions you will exclude and why (the exploration
   page lists the sessions with problems, but never excludes any).
3. Only then: tick **Unblind the exploration page** and **Make tables** again, and run your planned
   analysis on the tables. SocialEyes fits no models: the analysis is yours, run once, as planned.

## 6. Eye tracking and the face camera (optional)

- Neon recordings are matched to sessions with `socialeyes gaze <neon recording> <session>` (on the
  command line for now). Afterwards **Make tables** adds gaze columns (time on each AOI, time to the
  first fixation) and **Make heatmaps** draws where people looked, by condition.
- Studies that record the front camera: **Analyse face videos** (face in view, looking at the phone
  or away, distance); **Make tables** then adds those columns.
