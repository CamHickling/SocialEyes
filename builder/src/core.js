// SocialEyes experiment builder: the logic, without any page code.
// A study is kept as the same object study.yaml holds (so opening an existing
// study keeps every setting, including ones the form doesn't show), plus a few
// builder-only "content" numbers that decide how big the CSV skeletons are.
// Runs in the browser and in Node (python/tests/test_builder.py).
const Core = (() => {
  "use strict";

  // ------------------------------------------------------------ defaults (schema.py)

  const DEFAULTS = {
    platform: { name: "Pictogram", theme: "light", participant_handle: "you" },
    feed: {
      order: "shuffle", lead_in_fillers: 2, max_run_same_cell: 2, min_fillers_between_critical: 0,
      time_limit_s: null, done_button_after_s: 60, allow_comment_typing: false, allow_likes: true,
      allow_saves: true, allow_shares: true, allow_comment_likes: true, story_duration_s: 5,
    },
    logging: {
      touches: true, sensors: false, sensor_hz: 50, screen_recording: false, screen_recording_fps: 30,
      front_camera: { enabled: false, resolution: "720p", fps: 30, bitrate_mbps: 3, steps: ["feed"], segment_s: 60 },
    },
    neon: { required: false, auto_record: true, sync_interval_s: 2 },
    display: { viewing_distance_cm: 35 },
    participants: { n_plans: 120, id_prefix: "P", id_digits: 3 },
  };

  const STEP_DEFAULTS = {
    instructions: { title: "", text: "", button: "Continue", min_time_s: 0 },
    marker_calibration: { duration_s: 4 },
    camera_check: { min_face_s: 3, instructions: "Hold the phone as you normally would and look at the screen." },
    profile_photo: { text: "Take a photo for your profile picture. It is only used during this session and is deleted afterwards.", allow_skip: true },
    validation: { points: 9, target_dp: 28, instructions: "Look at each dot and tap it." },
    questionnaire: { title: "", items: [], randomize: false },
    feed: { instructions: "" },
    image_rating: { title: "", posts: "critical", items: [] },
    recognition: { question: "Did you see exactly this image in the feed?", lures: "both", foils: [], confidence: true },
    end: { text: "Thank you! Please hand the phone back to the researcher." },
  };

  const STEP_TYPES = Object.keys(STEP_DEFAULTS);
  const ATTRIBUTES = ["image_version", "comment_variant", "caption_variant", "label", "like_count"];
  const ITEM_KINDS = ["vas", "likert", "choice", "text", "number"];

  const clone = (x) => JSON.parse(JSON.stringify(x));
  const isObj = (x) => x !== null && typeof x === "object" && !Array.isArray(x);

  /** Value at a dotted path ("feed.order", "logging.front_camera.fps"), or the schema default. */
  function get(study, path) {
    let v = study, d = DEFAULTS;
    for (const k of path.split(".")) {
      v = isObj(v) ? v[k] : undefined;
      d = isObj(d) ? d[k] : undefined;
    }
    return v === undefined ? d : v;
  }

  function set(study, path, value) {
    const keys = path.split(".");
    let o = study;
    for (const k of keys.slice(0, -1)) {
      if (!isObj(o[k])) o[k] = {};
      o = o[k];
    }
    o[keys[keys.length - 1]] = value;
  }

  // ------------------------------------------------------------ templates

  const EXAMPLE = {
    id: "example", title: "Retouching labels and visual attention (example)", version: 1, seed: 20251001,
    platform: { name: "Pictogram", theme: "light", participant_handle: "you" },
    labels: { edited: { text: "This image has been digitally altered", style: "banner" } },
    factors: [
      { name: "edit", design: "within", levels: ["original", "retouched"], sets: { image_version: "{level}" } },
      { name: "label", design: "within", levels: ["none", "edited"], sets: { label: { none: null, edited: "edited" } } },
      { name: "comments", design: "between", levels: ["neutral", "appearance"], applies_to: "critical", sets: { comment_variant: "{level}" } },
    ],
    feed: {
      order: "shuffle", lead_in_fillers: 2, max_run_same_cell: 2, min_fillers_between_critical: 1,
      done_button_after_s: 60, time_limit_s: null, allow_likes: true, allow_comment_typing: true,
    },
    logging: {
      touches: true, sensors: false, screen_recording: false,
      front_camera: { enabled: false, resolution: "720p", fps: 30, steps: ["feed"] },
    },
    procedure: [
      { id: "welcome", type: "instructions", title: "Welcome", text: "Please browse the feed as you normally would." },
      { id: "photo", type: "profile_photo" },
      { id: "cal1", type: "marker_calibration", duration_s: 4 },
      { id: "val1", type: "validation", points: 9 },
      { id: "pre", type: "questionnaire", title: "Right now...", items: [
        { id: "body_sat_pre", kind: "vas", text: "How satisfied are you with your body right now?", min_label: "Not at all", max_label: "Extremely" },
      ] },
      { id: "feed", type: "feed" },
      { id: "cal2", type: "marker_calibration" },
      { id: "post", type: "questionnaire", items: [
        { id: "body_sat_post", kind: "vas", text: "How satisfied are you with your body right now?", min_label: "Not at all", max_label: "Extremely" },
      ] },
      { id: "ratings", type: "image_rating", posts: "critical", items: [
        { id: "attractive", kind: "likert", points: 7, text: "How attractive is this person?" },
        { id: "realistic", kind: "likert", points: 7, text: "How realistic is this image?" },
      ] },
      { id: "recog", type: "recognition", lures: "both", foils: ["foil01", "foil02"], confidence: true },
      { id: "end", type: "end" },
    ],
    participants: { n_plans: 16, id_prefix: "P", id_digits: 3 },
  };

  const BLANK = {
    id: "my_study", title: "", version: 1, seed: 1,
    platform: { name: "Pictogram", theme: "light", participant_handle: "you" },
    labels: {},
    factors: [],
    feed: { order: "shuffle", lead_in_fillers: 2, done_button_after_s: 60, time_limit_s: null },
    logging: { touches: true, sensors: false, screen_recording: false, front_camera: { enabled: false } },
    procedure: [
      { id: "welcome", type: "instructions", title: "Welcome", text: "Please browse the feed as you normally would." },
      { id: "cal1", type: "marker_calibration", duration_s: 4 },
      { id: "val1", type: "validation", points: 9 },
      { id: "feed", type: "feed" },
      { id: "end", type: "end" },
    ],
    participants: { n_plans: 40, id_prefix: "P", id_digits: 3 },
  };

  const TEMPLATES = {
    blank: { label: "Blank study", study: BLANK, content: { critical: 8, fillers: 12, accounts: 6, comments: true, stories: 0, reels: 0, foils: 0 } },
    example: { label: "Example: 2 x 2 x 2 retouching study", study: EXAMPLE, content: { critical: 8, fillers: 12, accounts: 6, comments: true, stories: 6, reels: 3, foils: 2 } },
  };

  function newStudy(name) {
    const t = TEMPLATES[name];
    return { study: clone(t.study), content: clone(t.content) };
  }

  /** Builder content numbers for a study opened from a file (its CSVs already exist). */
  function contentFor(study) {
    const rec = (study.procedure || []).find((s) => s.type === "recognition");
    return { critical: Math.max(cells(study), 1) * 2, fillers: 12, accounts: 6, comments: true, stories: 0, reels: 0,
      foils: rec && Array.isArray(rec.foils) ? rec.foils.length : 0 };
  }

  // ------------------------------------------------------------ design arithmetic

  const factorsOf = (study, design) => (study.factors || []).filter((f) => f.design === design);
  const product = (fs) => fs.reduce((n, f) => n * Math.max((f.levels || []).length, 1), 1);
  /** Within-subject cells (each participant sees all of them). */
  const cells = (study) => product(factorsOf(study, "within"));
  /** Between-subject groups (each participant is in one). */
  const groups = (study) => product(factorsOf(study, "between"));
  const blockSize = (study) => cells(study) * groups(study);

  /** The values a factor's `sets` gives an attribute, across its levels (nulls left out). */
  function attributeValues(factor, attr) {
    const spec = (factor.sets || {})[attr];
    if (spec === undefined) return [];
    const vals = (factor.levels || []).map((lv) =>
      typeof spec === "string" ? spec.split("{level}").join(lv) : isObj(spec) ? spec[lv] : null);
    return [...new Set(vals.filter((v) => v !== null && v !== undefined && v !== "").map(String))];
  }

  /** Does the factor change posts with this role? */
  function appliesTo(factor, role) {
    if (role === "critical") return true;
    return factor.design === "between" && factor.applies_to === "all";
  }

  /** attr -> values that posts of this role need content for. */
  function needs(study, role) {
    const out = {};
    for (const f of study.factors || []) {
      if (!appliesTo(f, role)) continue;
      for (const attr of Object.keys(f.sets || {})) out[attr] = attributeValues(f, attr);
    }
    return out;
  }

  /** One line for the YAML header: 2 (edit: original vs. retouched, within) x ... */
  function designSummary(study) {
    const fs = study.factors || [];
    if (!fs.length) return "no factors (every participant sees the same feed)";
    return fs.map((f) => `${(f.levels || []).length} (${f.name}: ${(f.levels || []).join(" vs. ")}, ${f.design})`).join(" x ");
  }

  // ------------------------------------------------------------ checks

  const IDENT = /^[A-Za-z_][A-Za-z0-9_]*$/;

  /** The multiples of `m` either side of `n`: "6 or 12". */
  function nearby(n, m) {
    const lo = Math.floor(n / m) * m, hi = Math.ceil(n / m) * m;
    return lo > 0 && lo !== hi ? `${lo} or ${hi}` : String(Math.max(hi, m));
  }

  /**
   * Problems and advice, each {level: "error" | "warning" | "tip", section, msg}.
   * Errors are what `socialeyes validate` would reject; warnings are allowed but
   * probably unintended; tips are suggestions.
   */
  function checks(study, content) {
    const out = [];
    const add = (level, section, msg) => out.push({ level, section, msg });
    const id = String(study.id || "");
    if (!id) add("error", "basics", "The study needs an id.");
    else if (!IDENT.test(id.replace(/-/g, "_"))) add("error", "basics", "The study id may only contain letters, digits, '-' and '_' (and must not start with a digit).");

    // factors
    const fs = study.factors || [];
    const names = fs.map((f) => f.name);
    const owner = {};
    fs.forEach((f, i) => {
      const what = f.name ? `Factor "${f.name}"` : `Factor ${i + 1}`;
      if (!IDENT.test(f.name || "")) add("error", "design", `${what}: the name must be a simple identifier (letters, digits, _), e.g. "edit".`);
      if (names.indexOf(f.name) !== i) add("error", "design", `${what}: two factors have the same name.`);
      const lv = f.levels || [];
      if (lv.length < 2) add("error", "design", `${what} needs at least 2 levels.`);
      if (new Set(lv).size !== lv.length) add("error", "design", `${what}: levels must be different from each other.`);
      if (lv.some((l) => !String(l).trim())) add("error", "design", `${what}: a level is empty.`);
      const attrs = Object.keys(f.sets || {});
      if (!attrs.length) add("error", "design", `${what} doesn't change anything yet: choose what it controls.`);
      for (const a of attrs) {
        if (!ATTRIBUTES.includes(a)) add("error", "design", `${what}: it can't control "${a}".`);
        if (owner[a]) add("error", "design", `"${a}" is controlled by both "${owner[a]}" and "${f.name}"; one factor per attribute.`);
        owner[a] = f.name;
        const spec = f.sets[a];
        if (isObj(spec)) {
          for (const l of lv) if (!(l in spec)) add("error", "design", `${what}: no ${a} chosen for level "${l}".`);
        }
        if (a === "label") {
          for (const v of attributeValues(f, a)) {
            if (!(study.labels || {})[v]) add("error", "design", `${what}: label "${v}" isn't defined under Labels.`);
          }
        }
        if (a === "like_count") {
          for (const v of attributeValues(f, a)) if (!/^\d+$/.test(v)) add("error", "design", `${what}: like count "${v}" must be a whole number.`);
        }
        if (typeof spec === "string" && !spec.includes("{level}") && a !== "label")
          add("warning", "design", `${what}: ${a} is "${spec}" for every level, so the factor makes no difference.`);
      }
      if (f.design === "between" && f.applies_to === "all" && (f.sets || {}).comment_variant !== undefined)
        add("tip", "design", `${what} applies to all posts, so every filler post needs comments for each level too.`);
    });
    for (const [key, lab] of Object.entries(study.labels || {})) {
      if (!IDENT.test(key)) add("error", "design", `Label "${key}": the key must be a simple identifier.`);
      if (!lab || !String(lab.text || "").trim()) add("error", "design", `Label "${key}" has no text.`);
    }

    // content and balance
    const c = cells(study), b = blockSize(study);
    if (content) {
      if (content.critical < 1 && fs.length) add("error", "content", "The factors need at least one critical post to act on.");
      if (c > 1 && content.critical % c !== 0)
        add("warning", "content", `${content.critical} critical posts can't be split evenly over ${c} within-subject cells; use a multiple of ${c} (e.g. ${nearby(content.critical, c)}).`);
      const lead = Number(get(study, "feed.lead_in_fillers")) || 0;
      if (lead > content.fillers) add("warning", "feed", `The feed starts with ${lead} fillers but there are only ${content.fillers}.`);
      const gap = Number(get(study, "feed.min_fillers_between_critical")) || 0;
      const neededFillers = lead + gap * Math.max(content.critical - 1, 0);
      if (gap && neededFillers > content.fillers)
        add("warning", "feed", `With ${gap} filler(s) between critical posts and ${lead} at the top, the feed needs at least ${neededFillers} fillers (you have ${content.fillers}).`);
    }
    const n = Number(get(study, "participants.n_plans")) || 0;
    if (b > 1 && n % b !== 0)
      add("warning", "participants", `${n} participant plans aren't a multiple of the balanced block of ${b} (${groups(study)} group(s) x ${c} cell(s)); use ${nearby(n, b)}.`);

    // procedure
    const steps = study.procedure || [];
    const ids = steps.map((s) => s.id);
    steps.forEach((s, i) => {
      const what = `Step ${i + 1}${s.id ? ` ("${s.id}")` : ""}`;
      if (!String(s.id || "").trim()) add("error", "procedure", `${what} needs an id.`);
      else if (ids.indexOf(s.id) !== i) add("error", "procedure", `${what}: another step has the same id.`);
      if (!STEP_TYPES.includes(s.type)) add("error", "procedure", `${what}: unknown step type "${s.type}".`);
      if (s.type === "instructions" && !String(s.text || "").trim()) add("error", "procedure", `${what}: instructions need text.`);
      if ((s.type === "questionnaire" || s.type === "image_rating") && !(s.items || []).length)
        add("error", "procedure", `${what}: add at least one question.`);
      const itemIds = (s.items || []).map((it) => it.id);
      (s.items || []).forEach((it, j) => {
        const q = `${what}, question ${j + 1}`;
        if (!String(it.id || "").trim()) add("error", "procedure", `${q} needs an id.`);
        else if (itemIds.indexOf(it.id) !== j) add("error", "procedure", `${q}: another question in this step has the same id.`);
        if (!String(it.text || "").trim()) add("error", "procedure", `${q} has no text.`);
        if (it.kind === "likert" && !it.points) add("error", "procedure", `${q}: a Likert scale needs a number of points.`);
        if (it.kind === "likert" && it.labels && it.labels.length !== it.points) add("error", "procedure", `${q}: give one label per point (${it.points}).`);
        if (it.kind === "choice" && !(it.options || []).length) add("error", "procedure", `${q}: a choice question needs options.`);
      });
      if (s.type === "recognition") {
        const lures = s.lures || "both";
        if (lures !== "alternate_version" && !(s.foils || []).length)
          add("error", "procedure", `${what}: "${lures}" lures need foil images (never-shown images); set the number of foils under Content.`);
        if (lures !== "foils" && !Object.keys(needs(study, "critical")).includes("image_version"))
          add("warning", "procedure", `${what}: "alternate version" lures need a factor that switches image versions.`);
      }
    });
    const feeds = steps.filter((s) => s.type === "feed").length;
    if (feeds !== 1) add("error", "procedure", feeds ? "The procedure can have only one feed step." : "The procedure needs a feed step.");
    if (!steps.length || steps[steps.length - 1].type !== "end") add("error", "procedure", "The last step must be the end screen.");
    const feedAt = steps.findIndex((s) => s.type === "feed");
    if (feedAt >= 0 && !steps.slice(0, feedAt).some((s) => s.type === "marker_calibration"))
      add("tip", "procedure", "Add a marker calibration before the feed: the gaze mapping uses it (and one after the feed to check for drift).");
    if (feedAt >= 0 && !steps.some((s) => s.type === "validation"))
      add("tip", "procedure", "A validation step measures eye-tracking accuracy on the phone for each participant.");

    // recording
    const cam = get(study, "logging.front_camera") || {};
    if (cam.enabled && get(study, "logging.screen_recording"))
      add("error", "recording", "The front camera and screen recording can't both be on (two video encoders make the feed stutter).");
    if (cam.enabled) {
      const camSteps = cam.steps === undefined ? ["feed"] : cam.steps;
      if (Array.isArray(camSteps)) {
        for (const sid of camSteps) if (!ids.includes(sid)) add("error", "recording", `Front camera: there is no step "${sid}" to record.`);
        if (!camSteps.length) add("warning", "recording", "The front camera is on but no step is chosen to record.");
      }
      const first = Array.isArray(camSteps) ? Math.min(...camSteps.map((sid) => ids.indexOf(sid)).filter((x) => x >= 0)) : 0;
      if (!steps.slice(0, Number.isFinite(first) ? first : steps.length).some((s) => s.type === "camera_check"))
        add("tip", "recording", "Add a camera check step before the recorded steps, so you know the face is in view.");
    }
    if (get(study, "logging.screen_recording"))
      add("warning", "recording", "Screen recording is meant for pilots: Android asks for permission every session and it costs performance.");
    return out;
  }

  // ------------------------------------------------------------ YAML writer

  const ORDER = {
    "": ["id", "title", "version", "seed", "platform", "display", "markers", "neon", "labels", "factors", "feed", "logging", "procedure", "participants",
      "accounts", "images", "posts", "comments", "captions", "stories", "reels"],
    platform: ["name", "theme", "participant_handle"],
    "factors[]": ["name", "design", "levels", "applies_to", "sets"],
    feed: ["order", "lead_in_fillers", "max_run_same_cell", "min_fillers_between_critical", "done_button_after_s", "time_limit_s",
      "allow_likes", "allow_saves", "allow_shares", "allow_comment_likes", "allow_comment_typing", "story_duration_s"],
    logging: ["touches", "sensors", "sensor_hz", "screen_recording", "screen_recording_fps", "front_camera"],
    "logging.front_camera": ["enabled", "resolution", "fps", "bitrate_mbps", "steps", "segment_s"],
    "procedure[]": ["id", "type"],
    "procedure[].items[]": ["id", "kind", "text"],
    participants: ["n_plans", "id_prefix", "id_digits"],
  };

  const COMMENTS = {
    seed: "change it and every plan changes; never change it once data collection has started",
    "platform.name": "never use a real platform's name or logo",
    "platform.participant_handle": "name the participant's own comments appear under",
    "feed.order": "shuffle: a new order per participant; fixed: posts.csv order",
    "feed.lead_in_fillers": "filler posts at the top, before any critical post",
    "feed.max_run_same_cell": "at most this many critical posts in a row from the same cell",
    "feed.min_fillers_between_critical": "fillers between two critical posts",
    "feed.done_button_after_s": "show the \"I'm done\" button after this long (null = never)",
    "feed.time_limit_s": "end the feed after this long (null = no limit)",
    "feed.allow_comment_typing": "participants can comment and reply (text and draft edits are logged)",
    logging: "besides gaze; see docs/EVENT_LOG.md",
    "logging.touches": "raw touch points",
    "logging.sensors": "accelerometer / gyroscope / rotation",
    "logging.screen_recording": "pilots only: Android asks permission every session",
    "logging.front_camera": "face video for expression analysis",
    "logging.front_camera.segment_s": "new video file every this many seconds",
    "participants.n_plans": "make it a multiple of the balanced block size",
  };

  const PLAIN = /^[A-Za-z_][A-Za-z0-9_ .\-\/()'!?…]*$/;
  const YAML11_WORDS = /^(y|yes|n|no|true|false|on|off|null|~)$/i;

  function scalar(v, inFlow) {
    if (v === null || v === undefined) return "null";
    if (typeof v === "boolean" || typeof v === "number") return String(v);
    const s = String(v);
    const plain = s !== "" && PLAIN.test(s) && !YAML11_WORDS.test(s) && s.trim() === s && !/ #|: |:$/.test(s) &&
      !(inFlow && /[,\[\]{}]/.test(s));
    return plain ? s : JSON.stringify(s);
  }

  const isScalar = (v) => v === null || ["string", "number", "boolean"].includes(typeof v);

  function orderedKeys(obj, path) {
    const pref = ORDER[path] || [];
    const keys = Object.keys(obj).filter((k) => obj[k] !== undefined);
    return [...pref.filter((k) => keys.includes(k)), ...keys.filter((k) => !pref.includes(k))];
  }

  function flowMap(obj) {
    return "{" + Object.keys(obj).map((k) => `${scalar(k, true)}: ${scalar(obj[k], true)}`).join(", ") + "}";
  }

  function emit(obj, path, indent, lines) {
    const pad = " ".repeat(indent);
    for (const key of orderedKeys(obj, path)) {
      const v = obj[key];
      const p = path ? `${path}.${key}` : key;
      const cmt = COMMENTS[p] ? `  # ${COMMENTS[p]}` : "";
      if (indent === 0 && lines.length && (isObj(v) || Array.isArray(v)) && lines[lines.length - 1] !== "") lines.push("");
      if (isScalar(v)) {
        lines.push(`${pad}${key}: ${scalar(v)}${cmt}`);
      } else if (Array.isArray(v) && v.every(isScalar)) {
        lines.push(`${pad}${key}: [${v.map((x) => scalar(x, true)).join(", ")}]${cmt}`);
      } else if (Array.isArray(v)) {
        lines.push(`${pad}${key}:${cmt}`);
        for (const item of v) {
          if (isObj(item)) {
            const sub = [];
            emit(item, `${p}[]`, indent + 4, sub);
            if (!sub.length) { lines.push(`${pad}  - {}`); continue; }
            sub[0] = `${pad}  - ${sub[0].slice(indent + 4)}`;
            lines.push(...sub);
          } else {
            lines.push(`${pad}  - ${isScalar(item) ? scalar(item) : JSON.stringify(item)}`);
          }
        }
      } else if (isObj(v)) {
        if (!Object.keys(v).length) lines.push(`${pad}${key}: {}${cmt}`);
        else if (/(^|\.)sets$/.test(path) && Object.values(v).every(isScalar)) lines.push(`${pad}${key}: ${flowMap(v)}${cmt}`);
        else {
          lines.push(`${pad}${key}:${cmt}`);
          emit(v, p, indent + 2, lines);
        }
      }
    }
    return lines;
  }

  /** study.yaml text, with a header and short comments on the main settings. */
  function toYaml(study) {
    const head = [
      `# ${study.title || study.id}`,
      `# Design: ${designSummary(study)}`,
      "#",
      "# Made with the SocialEyes experiment builder (builder/index.html).",
      `# Check it:  socialeyes validate studies/${study.id}`,
      `# Build it:  socialeyes compile studies/${study.id}`,
      "",
    ];
    return head.join("\n") + emit(study, "", 0, []).join("\n") + "\n";
  }

  // ------------------------------------------------------------ CSV skeletons

  const pad2 = (i) => String(i).padStart(2, "0");

  function csvCell(v) {
    const s = v === null || v === undefined ? "" : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  }

  const csv = (columns, rows) => [columns.join(","), ...rows.map((r) => columns.map((c) => csvCell(r[c])).join(","))].join("\n") + "\n";

  function foilIds(study, content) {
    const rec = (study.procedure || []).find((s) => s.type === "recognition" && (s.lures || "both") !== "alternate_version");
    if (!rec) return [];
    if ((rec.foils || []).length) return rec.foils;
    return Array.from({ length: content.foils }, (_, i) => `foil${pad2(i + 1)}`);
  }

  /** Keep recognition steps' foil lists in step with the number of foils under Content. */
  function syncFoils(study, content) {
    for (const s of study.procedure || []) {
      if (s.type === "recognition" && (s.lures || "both") !== "alternate_version")
        s.foils = Array.from({ length: content.foils }, (_, i) => `foil${pad2(i + 1)}`);
    }
  }

  /**
   * The CSV files, with one row for every piece of content the design needs, so
   * only file names and texts are left to fill in. {file name: text}
   */
  function skeletons(study, content) {
    const files = {};
    const accounts = Array.from({ length: Math.max(1, content.accounts) }, (_, i) => `acc${pad2(i + 1)}`);
    const acc = (i) => accounts[i % accounts.length];
    files["accounts.csv"] = csv(["account_id", "handle", "display_name", "avatar", "verified"],
      accounts.map((a, i) => ({ account_id: a, handle: `account${pad2(i + 1)}`, display_name: `Account ${i + 1}`, avatar: `avatars/${a}.jpg`, verified: "false" })));

    const posts = [
      ...Array.from({ length: content.critical }, (_, i) => ({ id: `crit${pad2(i + 1)}`, role: "critical" })),
      ...Array.from({ length: content.fillers }, (_, i) => ({ id: `fill${pad2(i + 1)}`, role: "filler" })),
    ];
    const need = { critical: needs(study, "critical"), filler: needs(study, "filler") };
    files["posts.csv"] = csv(["post_id", "role", "account_id", "default_version", "caption", "like_count", "posted_ago"],
      posts.map((p, i) => {
        const nd = need[p.role];
        return { post_id: p.id, role: p.role, account_id: acc(i), default_version: "",
          caption: nd.caption_variant ? "" : `Caption for ${p.id}`,
          like_count: nd.like_count ? "" : 100 + 37 * i, posted_ago: `${i + 1}h` };
      }));

    const images = [];
    for (const p of posts) {
      const versions = need[p.role].image_version || [];
      if (!versions.length) images.push({ image_id: p.id, file: `images/${p.id}.jpg`, post_id: p.id, version: "" });
      for (const v of versions) images.push({ image_id: `${p.id}_${v}`, file: `images/${p.id}_${v}.jpg`, post_id: p.id, version: v });
    }
    for (const f of foilIds(study, content)) images.push({ image_id: f, file: `images/${f}.jpg`, post_id: "", version: "" });
    files["images.csv"] = csv(["image_id", "file", "post_id", "version", "aoi_file"], images);

    const comments = [];
    posts.forEach((p, i) => {
      const variants = need[p.role].comment_variant;
      if (variants && variants.length) {
        for (const v of variants) for (const k of [1, 2])
          comments.push({ post_id: p.id, variant: v, order: k, account_id: acc(i + k), text: `${v} comment ${k} on ${p.id}`, like_count: k });
      } else if (content.comments) {
        for (const k of [1, 2]) comments.push({ post_id: p.id, variant: "", order: k, account_id: acc(i + k), text: `Comment ${k} on ${p.id}`, like_count: k });
      }
    });
    if (comments.length) files["comments.csv"] = csv(["post_id", "variant", "order", "account_id", "text", "like_count"], comments);

    const captions = [];
    for (const p of posts) for (const v of need[p.role].caption_variant || []) captions.push({ post_id: p.id, variant: v, text: `${v} caption for ${p.id}` });
    if (captions.length) files["captions.csv"] = csv(["post_id", "variant", "text"], captions);

    if (content.stories > 0) {
      files["stories.csv"] = csv(["account_id", "file", "posted_ago"],
        Array.from({ length: content.stories }, (_, i) => {
          const a = acc(Math.floor(i / 2));
          return { account_id: a, file: `stories/${a}_${(i % 2) + 1}.jpg`, posted_ago: `${i + 1}h` };
        }));
    }
    if (content.reels > 0) {
      files["reels.csv"] = csv(["account_id", "file", "caption", "like_count", "audio", "posted_ago"],
        Array.from({ length: content.reels }, (_, i) => ({ account_id: acc(i), file: `reels/${acc(i)}_reel${i + 1}.mp4`,
          caption: `Reel ${i + 1}`, like_count: 500 + 120 * i, audio: "Original audio", posted_ago: `${i + 1}d` })));
    }
    return files;
  }

  /** NEXT_STEPS.txt: what the researcher still has to add. */
  function nextSteps(study, content, files) {
    const crit = (study.factors || []).length ? content.critical : 0;
    const lines = [
      `${study.title || study.id}: what to do next`,
      "",
      "The builder wrote study.yaml and CSV files with one row for every piece of",
      "content your design needs. Replace the placeholder texts and add the files:",
      "",
      "1. Images: put every file listed in images.csv into images/ (or change the",
      "   paths). Avatars for accounts.csv go into avatars/." + (files["stories.csv"] ? " Story images into stories/." : "") +
        (files["reels.csv"] ? " Reel videos into reels/." : ""),
      "2. AOIs: every image of a critical post needs an AOI file, by default named",
      "   after the image: aois/crit01.json for images/crit01.jpg (see \"AOIs\" in the README).",
      "3. Texts: handles and names in accounts.csv, captions and like counts in posts.csv" +
        (files["comments.csv"] ? ",\n   the comments in comments.csv" : "") + (files["captions.csv"] ? ", caption variants in captions.csv" : "") + ".",
      "4. Check and build:",
      `     socialeyes validate studies/${study.id}`,
      `     socialeyes compile studies/${study.id}`,
      "",
      `Design: ${designSummary(study)}`,
      `Critical posts: ${crit || content.critical}, fillers: ${content.fillers}. Balanced block: ${blockSize(study)} participant(s).`,
      "",
      "File formats: docs/STUDY_DESIGN.md. Never change `seed` or the post order once",
      "data collection has started.",
    ];
    return lines.join("\n") + "\n";
  }

  /** Every file of the study folder: {path: text}. */
  function studyFiles(study, content, withCsv) {
    const files = { "study.yaml": toYaml(study) };
    if (withCsv) {
      Object.assign(files, skeletons(study, content));
      files["NEXT_STEPS.txt"] = nextSteps(study, content, files);
    }
    return files;
  }

  // ------------------------------------------------------------ zip (stored, no compression)

  const CRC = (() => {
    const t = new Uint32Array(256);
    for (let n = 0; n < 256; n++) {
      let c = n;
      for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
      t[n] = c >>> 0;
    }
    return t;
  })();

  function crc32(bytes) {
    let c = 0xffffffff;
    for (let i = 0; i < bytes.length; i++) c = CRC[(c ^ bytes[i]) & 0xff] ^ (c >>> 8);
    return (c ^ 0xffffffff) >>> 0;
  }

  /** {path: text} -> zip file bytes. Paths are put under `folder/`. */
  function zip(files, folder) {
    const enc = new TextEncoder();
    const parts = [], central = [];
    let offset = 0;
    const now = new Date();
    const dosTime = (now.getHours() << 11) | (now.getMinutes() << 5) | (now.getSeconds() >> 1);
    const dosDate = ((now.getFullYear() - 1980) << 9) | ((now.getMonth() + 1) << 5) | now.getDate();
    for (const [path, text] of Object.entries(files)) {
      const name = enc.encode(`${folder}/${path}`);
      const data = enc.encode(text);
      const crc = crc32(data);
      const local = new DataView(new ArrayBuffer(30));
      local.setUint32(0, 0x04034b50, true); local.setUint16(4, 20, true); local.setUint16(6, 0x0800, true);
      local.setUint16(8, 0, true); local.setUint16(10, dosTime, true); local.setUint16(12, dosDate, true);
      local.setUint32(14, crc, true); local.setUint32(18, data.length, true); local.setUint32(22, data.length, true);
      local.setUint16(26, name.length, true); local.setUint16(28, 0, true);
      parts.push(new Uint8Array(local.buffer), name, data);
      const cen = new DataView(new ArrayBuffer(46));
      cen.setUint32(0, 0x02014b50, true); cen.setUint16(4, 20, true); cen.setUint16(6, 20, true); cen.setUint16(8, 0x0800, true);
      cen.setUint16(10, 0, true); cen.setUint16(12, dosTime, true); cen.setUint16(14, dosDate, true);
      cen.setUint32(16, crc, true); cen.setUint32(20, data.length, true); cen.setUint32(24, data.length, true);
      cen.setUint16(28, name.length, true); cen.setUint32(42, offset, true);
      central.push(new Uint8Array(cen.buffer), name);
      offset += 30 + name.length + data.length;
    }
    const cenSize = central.reduce((n, a) => n + a.length, 0);
    const end = new DataView(new ArrayBuffer(22));
    end.setUint32(0, 0x06054b50, true); end.setUint16(8, Object.keys(files).length, true);
    end.setUint16(10, Object.keys(files).length, true); end.setUint32(12, cenSize, true); end.setUint32(16, offset, true);
    const all = [...parts, ...central, new Uint8Array(end.buffer)];
    const out = new Uint8Array(all.reduce((n, a) => n + a.length, 0));
    let at = 0;
    for (const a of all) { out.set(a, at); at += a.length; }
    return out;
  }

  return {
    DEFAULTS, STEP_DEFAULTS, STEP_TYPES, ATTRIBUTES, ITEM_KINDS, TEMPLATES,
    clone, get, set, newStudy, contentFor, cells, groups, blockSize, attributeValues, needs, designSummary,
    checks, toYaml, skeletons, nextSteps, studyFiles, syncFoils, zip, crc32,
  };
})();

if (typeof module !== "undefined") module.exports = Core;
