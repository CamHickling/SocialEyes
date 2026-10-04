# Designing a study

> [!NOTE]
> **Draft (v0.1).** The CSV layout below is what the compiler implements today,
> but it may still change before v1. [`studies/example/`](../studies/example)
> is a complete, working study that uses every file described here.

A study is a folder:

```
studies/my_study/
  study.yaml       design, procedure, settings (see the README for the format)
  accounts.csv     fake poster accounts
  images.csv       every image file, including all versions and recognition foils
  posts.csv        the posts; which are critical and which are fillers
  comments.csv     comment sets (optional)
  captions.csv     caption variants (optional)
  stories.csv      stories shown from the story circles (optional)
  images/          image files
  avatars/         profile pictures
  aois/            one AOI file per image (see "AOIs" in the README)
```

Check it, then build the package the phone app loads:

```powershell
socialeyes validate studies/my_study
socialeyes compile studies/my_study        # writes build/<study id>/
```

`validate` reports **every** problem it finds, with file and line number, so
you can fix them in one go. It also warns about things that are allowed but
probably unintended (an unbalanced number of posts or participants, for example).

## General CSV rules

- UTF-8 (Excel: *CSV UTF-8*). The first row holds the column names.
- Column order doesn't matter. Unknown columns are an error, so typos don't go
  unnoticed. Optional columns can be left out entirely.
- Values that contain commas must be in double quotes: `"Wow, love this"`.
- Blank rows are ignored. Leading and trailing spaces are trimmed.
- File paths are relative to the study folder and must stay inside it. `/` and
  `\` both work.
- The file names can be changed in `study.yaml` (`accounts:`, `images:`,
  `posts:`, `comments:`, `captions:`).

## accounts.csv

| column | required | meaning |
|---|---|---|
| `account_id` | yes | unique key, used by posts and comments |
| `handle` | yes | shown as @handle (a leading `@` is removed) |
| `avatar` | yes | profile picture path |
| `display_name` | no | |
| `verified` | no | `true`/`false` (blank = false): shows a verified badge |

## images.csv

One row per image **file**. A critical post normally has one row per version
(e.g. `original` and `retouched`).

| column | required | meaning |
|---|---|---|
| `image_id` | yes | unique key. Recognition foils are referenced by this id in `study.yaml` |
| `file` | yes | image path |
| `post_id` | no | the post this image belongs to. **Blank = a foil** that never appears in the feed |
| `version` | no | version name, e.g. `original`, `retouched`. Must match the values your `image_version` factor produces. Can be blank for posts with only one image |
| `aoi_file` | no | AOI file path. Default: `aois/<image file name>.json` |

Each (`post_id`, `version`) pair must be unique. Every image of a critical post
needs an AOI file, and the AOI file's `width`/`height` must match the image's
real size. AOI files for fillers and foils are optional; they are used when
present.

## posts.csv

| column | required | meaning |
|---|---|---|
| `post_id` | yes | unique key |
| `role` | yes | `critical` (carries the manipulation) or `filler` |
| `account_id` | yes | who posted it |
| `default_version` | no | image version shown when no factor sets `image_version`. Not needed when the post has only one image |
| `caption` | no | the caption, unless a factor sets `caption_variant` |
| `like_count` | no | whole number (default 0), unless a factor sets `like_count` |
| `posted_ago` | no | display text such as `3h` or `2d` |

With `feed: order: fixed`, the feed shows the posts in this file's order.

## comments.csv (optional)

One row per comment. Comments are grouped into **variants** per post.

| column | required | meaning |
|---|---|---|
| `post_id` | yes | the post the comment belongs to |
| `account_id` | yes | who wrote it |
| `text` | yes | the comment |
| `variant` | no | which set it belongs to. **Blank = the default set**, shown when no factor sets `comment_variant` |
| `order` | no | position under the post (default: file order) |
| `like_count` | no | whole number (default 0) |

If a factor sets `comment_variant: "{level}"`, every post the factor applies
to needs at least one comment for each level (e.g. variants `neutral` and
`appearance`). A post without default comments simply has none.

## captions.csv (optional)

Only needed when a factor sets `caption_variant`. Posts without a variant use
the `caption` column of `posts.csv`.

| column | required | meaning |
|---|---|---|
| `post_id` | yes | |
| `variant` | yes | matches the values the factor produces |
| `text` | yes | the caption |

## stories.csv (optional)

Stories, opened by tapping an account's circle at the top of the feed. Every
participant sees the same stories (they are not manipulated by factors).
Without this file the story circles are only decoration.

| column | required | meaning |
|---|---|---|
| `account_id` | yes | whose story it is; the circles appear in the order accounts first occur in this file |
| `file` | yes | image path; 9:16 portrait (e.g. 1080x1920) looks like a real story, any size works |
| `story_id` | no | unique key (default `<account_id>_<n>`); must not equal an `image_id` |
| `order` | no | position among the account's stories (default: file order) |
| `duration_s` | no | seconds before it moves on (default `feed.story_duration_s`, 5) |
| `posted_ago` | no | display text such as `2h` |
| `aoi_file` | no | AOI file for the story image (default `aois/<image file name>.json` if it exists) |

The image is always shown whole, so gaze on it can be mapped to image pixels and AOIs.

## How factors pick content

Each factor `sets` one or more post attributes. For each post the compiler
works out the value and looks up the content:

| attribute | value | looks up |
|---|---|---|
| `image_version` | version name | the `images.csv` row with this `post_id` and `version` |
| `label` | label key or `null` | `labels:` in `study.yaml` (`null` = no label) |
| `comment_variant` | variant name | the `comments.csv` rows with this `post_id` and `variant` |
| `caption_variant` | variant name | the `captions.csv` row with this `post_id` and `variant` |
| `like_count` | a number | used directly |

Attributes that no factor sets fall back to the post's defaults (default image
version, no label, default comments, `caption`, `like_count`).

Within-subject factors apply to critical posts only. Between-subject factors
apply to critical posts, and also to fillers with `applies_to: all`. In that
case every filler needs the content too (for example comments for every
variant).

## Balance

- Within-subject cells are rotated across critical posts (Latin square). Use a
  number of critical posts that is a **multiple of the number of cells**
  (2 x 2 = 4 cells: 4, 8, 12, ... posts), so each participant sees each cell
  equally often.
- Participants are assigned in blocks of (between groups x cells). Make
  `participants.n_plans`, and your recruitment target, a multiple of that block
  size.

`validate` warns when either rule is broken.

## What `compile` writes

```
build/<study id>/
  study.json          resolved study.yaml, accounts, posts, images (with sizes),
                      sync code, validation dot positions
  plans/P001.json ... one plan per participant
  plans.csv           participant_id, group, list, between-factor levels
  media/              images and avatars (same paths as in the study folder)
  aois/<image_id>.json  AOIs, normalised to polygons
  tags/               screen AprilTags for marker_calibration steps
```

A plan lists the participant's feed in display order. For every post it gives
the cell and conditions, the image, the label, the caption, the like count and
the full comments. It also gives the trial order for `image_rating` and
`recognition` steps. Recognition trials are marked `old`, `alternate` (the
version of a post the participant did *not* see) or `foil`.

Plans depend only on `seed` and the participant number. Compiling the same
study again gives identical plans, so never change `seed` (or the order of
posts) once data collection has started.
