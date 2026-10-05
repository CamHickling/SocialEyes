// SocialEyes experiment builder: the form. Logic lives in core.js.
(() => {
  "use strict";
  const C = Core;
  const STORE = "socialeyes-builder-draft";

  const ui = {
    study: null, content: null, section: "start", withCsv: true,
    opened: null,           // file name when the study came from a study.yaml
    openStep: null,         // procedure card that is expanded
    previewFile: "study.yaml",
    loadError: null,
    // inside the desktop app (socialeyes app) only
    desktop: false,         // the Python bridge is available
    appInfo: null,          // {version, studies_dir}
    tab: "design",          // app tab: studies, design, content, phone, data
    folder: null,           // the study folder this study is saved in
    savedYaml: null,        // study.yaml as last saved or opened, to spot unsaved changes
    hadComments: false,     // the opened study.yaml had comments, which saving drops
    saved: null,            // result of the last save: {written, kept, backup, at}
    compiler: null,         // the compiler's checks of the folder: {errors, warnings, at}
    busy: null,             // what the bridge is doing ("Saving…"), shown while it works
    desktopError: null,
  };

  const APP_TABS = [
    ["studies", "Studies", "A list of your study folders and their status (designing, ready, collecting data, sessions so far), and new studies from blank or from the example. For now, open or start a study in the Design tab."],
    ["design", "Design", ""],
    ["content", "Content", "A checklist of every image, avatar, video and AOI file the design needs, found or missing."],
    ["phone", "Phone", "Check, compile and load a study onto the phone in one step, install or update the app, and check the phone is ready (storage, battery, Do Not Disturb, camera)."],
    ["data", "Data", "Copy sessions off the phone, check every file arrived intact, delete them from the phone, run the quality checks and keep a register of who took part."],
  ];

  /** Call a method of the desktop app's Python bridge; returns its result or throws its message. */
  async function bridge(name, busy, ...args) {
    ui.busy = busy;
    if (busy) render();
    try {
      const r = await window.pywebview.api[name](...args);
      if (r && r.error) throw new Error(r.error);
      return r ? r.ok : null;
    } finally {
      ui.busy = null;
    }
  }

  const unsaved = () => ui.desktop && ui.study && ui.folder !== null && C.toYaml(ui.study) !== ui.savedYaml;
  const clock = (d) => d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

  // ------------------------------------------------------------ guidance texts

  const SECTIONS = [
    ["start", "Start"], ["basics", "Basics"], ["design", "Design"], ["content", "Content"], ["feed", "Feed"],
    ["procedure", "Procedure"], ["recording", "Recording"], ["participants", "Participants"], ["download", "Download"],
  ];

  const ATTR_INFO = {
    image_version: ["Image version", "Shows a different version of each critical post's image per level (e.g. original vs. retouched). images.csv gets one row per version."],
    label: ["Label", "Adds a label to the post (e.g. a disclaimer) or none. Define the labels below."],
    comment_variant: ["Comments", "Shows a different set of comments per level (e.g. neutral vs. appearance-focused). comments.csv gets a set per level."],
    caption_variant: ["Caption", "Shows a different caption per level. captions.csv gets one caption per level."],
    like_count: ["Like count", "Shows a different number of likes per level (e.g. 50 vs. 5000)."],
  };

  const STEP_INFO = {
    instructions: ["Instructions", "A screen of text with a Continue button."],
    marker_calibration: ["Marker calibration", "Shows AprilTags on screen and a sync flash so the scene camera can map gaze onto the screen. Do one before and one after the feed."],
    validation: ["Validation", "Dots to look at and tap: measures eye-tracking accuracy on the phone."],
    camera_check: ["Camera check", "Researcher-run framing check for the front camera. Shows a guide and whether a face is detected, never the video."],
    profile_photo: ["Profile photo", "Optional selfie as the participant's profile picture; kept in memory only and deleted when the session ends."],
    questionnaire: ["Questionnaire", "Questions on one screen: sliders (VAS), Likert scales, choices, text or numbers."],
    feed: ["Feed", "The mock social media feed. Exactly one per study."],
    image_rating: ["Image ratings", "Each post's image again, with questions about it."],
    recognition: ["Recognition test", "Images one at a time: \"did you see exactly this image?\". Lures are images not shown: foils (never in the feed) and/or the other version of a post."],
    end: ["End", "The last screen. The session is saved when it appears."],
  };

  const KIND_INFO = { vas: "Slider (VAS)", likert: "Likert scale", choice: "Multiple choice", text: "Free text", number: "Number" };

  // ------------------------------------------------------------ paths

  const segs = (path) => path.split(".").map((k) => (/^\d+$/.test(k) ? Number(k) : k));

  function getP(path) {
    let o = ui.study;
    for (const k of segs(path)) { if (o == null) return undefined; o = o[k]; }
    return o;
  }

  function setP(path, value) {
    const ks = segs(path);
    let o = ui.study;
    for (let i = 0; i < ks.length - 1; i++) {
      if (o[ks[i]] == null || typeof o[ks[i]] !== "object") o[ks[i]] = typeof ks[i + 1] === "number" ? [] : {};
      o = o[ks[i]];
    }
    const last = ks[ks.length - 1];
    if (value === undefined) { if (Array.isArray(o)) o.splice(last, 1); else delete o[last]; } else o[last] = value;
  }

  /** Current value, or the schema / step default. */
  function val(path, def) {
    const v = getP(path);
    if (v !== undefined) return v;
    if (def !== undefined) return def;
    const top = C.get({}, path);
    return top;
  }

  // ------------------------------------------------------------ html helpers

  const esc = (s) => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

  function help(text) { return text ? `<p class="help">${text}</p>` : ""; }

  /**
   * One form field bound to a path in the study (or "content.x" for builder-only numbers).
   * kind: text | textarea | int | float | nullnum | bool | select | list
   */
  function field(o) {
    const id = "f_" + o.path.replace(/\W/g, "_");
    const cur = o.path.startsWith("content.") ? ui.content[o.path.slice(8)] : val(o.path, o.def);
    const attrs = `id="${id}" data-path="${esc(o.path)}" data-kind="${o.kind}" data-key="${esc(o.path)}"${o.num ? ' data-num="1"' : ""}`;
    let input;
    if (o.kind === "bool") {
      return `<label class="check"><input type="checkbox" ${attrs} ${cur ? "checked" : ""}> <span>${o.label}</span></label>${help(o.help)}`;
    } else if (o.kind === "select") {
      input = `<select ${attrs}>${o.options.map(([v, l]) => `<option value="${esc(v)}" ${String(cur) === String(v) ? "selected" : ""}>${esc(l)}</option>`).join("")}</select>`;
    } else if (o.kind === "textarea") {
      input = `<textarea ${attrs} rows="${o.rows || 3}" placeholder="${esc(o.placeholder || "")}">${esc(cur)}</textarea>`;
    } else if (o.kind === "list") {
      input = `<input type="text" ${attrs} value="${esc((cur || []).join(", "))}" placeholder="${esc(o.placeholder || "comma-separated")}">`;
    } else if (o.kind === "int" || o.kind === "float" || o.kind === "nullnum") {
      input = `<input type="number" ${attrs} value="${cur === null || cur === undefined ? "" : esc(cur)}" ${o.min !== undefined ? `min="${o.min}"` : ""} ${o.max !== undefined ? `max="${o.max}"` : ""} step="${o.kind === "int" ? 1 : "any"}" placeholder="${esc(o.placeholder || "")}">`;
    } else {
      input = `<input type="text" ${attrs} value="${esc(cur)}" placeholder="${esc(o.placeholder || "")}">`;
    }
    return `<div class="field ${o.wide ? "wide" : ""}"><label for="${id}">${o.label}</label>${input}${help(o.help)}</div>`;
  }

  function parseInput(el) {
    const k = el.dataset.kind;
    if (k === "bool") return el.checked;
    if (k === "list") return el.value.split(",").map((s) => s.trim()).filter((s) => s !== "");
    if (k === "int") return el.value === "" ? undefined : Math.round(Number(el.value));
    if (k === "float") return el.value === "" ? undefined : Number(el.value);
    if (k === "nullnum") return el.value === "" ? null : Number(el.value);
    if (k === "select") {
      const v = el.value;
      if (el.dataset.num) return Number(v);
      if (v === "__null__") return null;
      return v;
    }
    return el.value;
  }

  const btn = (action, label, cls = "", extra = "") => `<button type="button" class="btn ${cls}" data-action="${action}" ${extra}>${label}</button>`;

  // ------------------------------------------------------------ sections

  function sectionStart() {
    let draft = null;
    try { draft = JSON.parse(localStorage.getItem(STORE) || "null"); } catch (e) { draft = null; }
    const open = ui.desktop
      ? `<div class="card"><h3>Open a study folder</h3><p>Edit an existing study in place. Your CSV files are never overwritten.</p>${btn("open-folder", "Choose folder…")}</div>`
      : `<div class="card" id="drop"><h3>Open a study.yaml</h3><p>Edit an existing study. Comments in the file are not kept; your CSV files are not touched.</p>
          <label class="btn file">Choose file…<input type="file" id="open-file" accept=".yaml,.yml,text/yaml"></label>
          <p class="hint">or drop the file here</p></div>`;
    return `
      <h2>Start</h2>
      <p class="lead">This builder walks you through the decisions for a SocialEyes study and writes
      <code>study.yaml</code> plus CSV files with a row for every piece of content your design needs.
      ${ui.desktop ? "Everything stays on this computer." : "Everything stays in this browser; nothing is uploaded."}</p>
      ${ui.desktopError ? `<p class="error-box">${esc(ui.desktopError)}</p>` : ""}
      <div class="cards">
        <div class="card"><h3>New study</h3><p>Just the basic feed (posts, likes, comments to read) and the eye-tracking steps. Every optional feature starts off; switch on what you need.</p>${btn("new-blank", "Start blank", "primary")}</div>
        <div class="card"><h3>From the example</h3><p>The 2 x 2 x 2 retouching study from <code>studies/example</code>, to adapt.</p>${btn("new-example", "Use the example")}</div>
        ${open}
        ${draft && draft.study ? `<div class="card"><h3>Continue</h3><p>Your last draft: <b>${esc(draft.study.title || draft.study.id)}</b>.</p>${btn("resume", "Continue where you left off")}</div>` : ""}
      </div>
      ${ui.loadError ? `<p class="error-box">${esc(ui.loadError)}</p>` : ""}
      ${ui.study ? `<p class="hint">Working on <b>${esc(ui.study.title || ui.study.id)}</b>${ui.folder ? ` in <span class="folder">${esc(ui.folder)}</span>` : ui.opened ? ` (opened from ${esc(ui.opened)})` : ""}. ${btn("go-basics", "Carry on →", "link")}</p>` : ""}`;
  }

  function sectionBasics() {
    return `
      <h2>Basics</h2>
      ${help("The study id names the folder and the data (<code>build/&lt;id&gt;</code>, <code>data/&lt;id&gt;/…</code>); keep it short and don't change it once you collect data.")}
      <div class="grid">
        ${field({ path: "id", label: "Study id", kind: "text", placeholder: "my_study", help: "Letters, digits, - and _." })}
        ${field({ path: "title", label: "Title", kind: "text", wide: true })}
        ${field({ path: "version", label: "Version", kind: "int", def: 1, min: 1, help: "Raise it when you change the study after piloting." })}
        <div class="field"><label for="f_seed">Seed</label><div class="row"><input type="number" id="f_seed" data-path="seed" data-kind="int" data-key="seed" value="${esc(val("seed", 1))}">${btn("random-seed", "Random")}</div>
          ${help("Decides every participant's plan (post order, conditions). Same seed = same plans. Never change it once data collection has started.")}</div>
      </div>
      <h3>How the app looks</h3>
      <div class="grid">
        ${field({ path: "platform.name", label: "App name in the feed", kind: "text", help: "Never use a real platform's name or logo." })}
        ${field({ path: "platform.theme", label: "Theme", kind: "select", options: [["light", "Light"], ["dark", "Dark"]] })}
        ${field({ path: "platform.participant_handle", label: "Participant's handle", kind: "text", help: "The name their own comments and replies appear under." })}
      </div>`;
  }

  function factorCard(f, i) {
    const p = `factors.${i}`;
    const used = new Set((ui.study.factors || []).flatMap((g, j) => (j === i ? [] : Object.keys(g.sets || {}))));
    const own = Object.keys(f.sets || {});
    const free = C.ATTRIBUTES.filter((a) => !used.has(a) && !own.includes(a));
    const controls = own.map((a) => controlRow(f, i, a, used)).join("");
    return `<div class="card factor">
      <div class="card-head"><b>Factor ${i + 1}</b>${btn(`del-factor:${i}`, "Remove", "link danger")}</div>
      <div class="grid">
        ${field({ path: `${p}.name`, label: "Name", kind: "text", placeholder: "e.g. edit", help: "Used in the data; letters, digits and _." })}
        ${field({ path: `${p}.design`, label: "Design", kind: "select", options: [["within", "Within subjects"], ["between", "Between subjects"]], help: f.design === "between" ? "Each participant gets one level." : "Every participant sees every level." })}
        ${field({ path: `${p}.levels`, label: "Levels", kind: "list", placeholder: "e.g. original, retouched", wide: true, help: "At least 2. These names appear in the data and, for images, comments and captions, in the CSV files." })}
        ${f.design === "between" ? field({ path: `${p}.applies_to`, label: "Applies to", kind: "select", def: "critical", options: [["critical", "Critical posts only"], ["all", "All posts (fillers too)"]], help: "With all posts, every filler needs the content for each level too." }) : ""}
      </div>
      <h4>What it changes</h4>
      ${controls || `<p class="hint">Nothing yet: choose what this factor manipulates.</p>`}
      ${free.length ? `<div class="row"><label for="add-attr-${i}" class="hint">${own.length ? "Also change" : "Change"}</label>${`<select id="add-attr-${i}">${free.map((a) => `<option value="${a}">${ATTR_INFO[a][0]}</option>`).join("")}</select>`}${btn(`add-attr:${i}`, "Add")}</div>` : ""}
    </div>`;
  }

  function controlRow(f, i, attr) {
    const spec = f.sets[attr];
    const levels = f.levels || [];
    const base = `factors.${i}.sets.${attr}`;
    let body = "";
    if (attr === "label") {
      const opts = [["__null__", "No label"], ...Object.keys(ui.study.labels || {}).map((k) => [k, `${k}: “${(ui.study.labels[k] || {}).text || ""}”`])];
      body = `<div class="grid">${levels.map((lv) => field({ path: `${base}.${lv}`, label: `Level “${esc(lv)}”`, kind: "select", options: opts, def: null })).join("")}</div>`;
    } else if (attr === "like_count") {
      body = `<div class="grid">${levels.map((lv) => field({ path: `${base}.${lv}`, label: `Likes for “${esc(lv)}”`, kind: "text", placeholder: "e.g. 5000" })).join("")}</div>`;
    } else {
      const custom = typeof spec !== "string";
      body = `<label class="check"><input type="checkbox" data-action-change="custom-map:${i}:${attr}" ${custom ? "checked" : ""}> <span>Use different names than the level names</span></label>`;
      if (custom) body += `<div class="grid">${levels.map((lv) => field({ path: `${base}.${lv}`, label: `Level “${esc(lv)}”`, kind: "text" })).join("")}</div>`;
      else if (spec !== "{level}") body += field({ path: base, label: "Template", kind: "text", help: "{level} is replaced by the level name." });
      else body += help(`Values: ${levels.map((l) => `<code>${esc(l)}</code>`).join(", ") || "…"}`);
    }
    return `<div class="control"><div class="card-head"><b>${ATTR_INFO[attr][0]}</b>${btn(`del-attr:${i}:${attr}`, "Remove", "link danger")}</div>${help(ATTR_INFO[attr][1])}${body}</div>`;
  }

  function sectionDesign() {
    const fs = ui.study.factors || [];
    const needLabels = fs.some((f) => (f.sets || {}).label !== undefined) || Object.keys(ui.study.labels || {}).length;
    const c = C.cells(ui.study), g = C.groups(ui.study);
    return `
      <h2>Design</h2>
      <p class="lead">Each <b>factor</b> manipulates something about the <b>critical posts</b> (the posts your
      hypotheses are about; the other posts are fillers).</p>
      <ul class="tips">
        <li><b>Within subjects</b>: every participant sees every level, on different posts. More power with fewer people; use it unless seeing one level would change how people react to the other.</li>
        <li><b>Between subjects</b>: each participant gets one level. Use it when levels would contaminate each other (e.g. a whole comment climate).</li>
      </ul>
      ${fs.map(factorCard).join("")}
      ${btn("add-factor", "+ Add factor", "primary")}
      <div class="summary"><b>${c}</b> within-subject cell${c === 1 ? "" : "s"} · <b>${g}</b> between-subject group${g === 1 ? "" : "s"} · balanced block of <b>${c * g}</b> participant${c * g === 1 ? "" : "s"}</div>
      ${needLabels ? sectionLabels() : ""}`;
  }

  function sectionLabels() {
    const labels = ui.study.labels || {};
    return `<h3>Labels</h3>${help("Labels a factor can put on a post. The key is what the factor refers to.")}
      ${Object.keys(labels).map((k) => `<div class="card"><div class="card-head"><b>${esc(k)}</b>${btn(`del-label:${k}`, "Remove", "link danger")}</div>
        <div class="grid">${field({ path: `labels.${k}.text`, label: "Text", kind: "text", wide: true })}
        ${field({ path: `labels.${k}.style`, label: "Style", kind: "select", def: "banner", options: [["banner", "Banner over the image"], ["caption", "Line under the image"]] })}</div></div>`).join("")}
      <div class="row"><input type="text" id="new-label" placeholder="key, e.g. edited">${btn("add-label", "Add label")}</div>`;
  }

  function sectionContent() {
    const need = C.needs(ui.study, "critical"), needF = C.needs(ui.study, "filler");
    const nv = (need.image_version || []).length || 1, nvf = (needF.image_version || []).length || 1;
    const rec = (ui.study.procedure || []).some((s) => s.type === "recognition" && (s.lures || "both") !== "alternate_version");
    const c = C.cells(ui.study);
    const nImages = ui.content.critical * nv + ui.content.fillers * nvf + (rec ? ui.content.foils : 0);
    return `
      <h2>Content</h2>
      <p class="lead">How much content the study has. This only decides how many rows the CSV skeletons get; it isn't stored in study.yaml.</p>
      ${ui.opened ? `<p class="hint">You opened an existing study: its CSV files already exist. ${ui.desktop ? "These numbers matter only for CSV files that don't exist yet; saving never overwrites the others." : "These numbers matter only if you download CSV skeletons."}</p>` : ""}
      <div class="grid">
        ${field({ path: "content.critical", label: "Critical posts", kind: "int", min: 0, help: c > 1 ? `A multiple of ${c} (the number of within-subject cells), so everyone sees each cell equally often.` : "Posts that carry the manipulation." })}
        ${field({ path: "content.fillers", label: "Filler posts", kind: "int", min: 0, help: "Unmanipulated posts around the critical ones. More fillers make the manipulation less obvious." })}
        ${field({ path: "content.accounts", label: "Accounts", kind: "int", min: 1, help: "Fake poster accounts; posts are spread over them." })}
        ${field({ path: "content.stories", label: "Stories", kind: "int", min: 0, help: "Images behind the story circles (0 = circles are decoration)." })}
        ${field({ path: "content.reels", label: "Reels", kind: "int", min: 0, help: "Short videos in the Reels tab (0 = the tab does nothing)." })}
        ${rec ? field({ path: "content.foils", label: "Recognition foils", kind: "int", min: 0, help: "Never-shown images for the recognition test." }) : ""}
      </div>
      ${field({ path: "content.comments", label: "Posts have comments (when no factor sets them)", kind: "bool" })}
      <div class="summary">You'll need <b>${nImages}</b> image${nImages === 1 ? "" : "s"}${nv > 1 ? ` (${nv} versions of each critical post)` : ""}, ${ui.content.accounts} avatar${ui.content.accounts === 1 ? "" : "s"}${ui.content.stories ? `, ${ui.content.stories} story image(s)` : ""}${ui.content.reels ? `, ${ui.content.reels} video(s)` : ""}, and an AOI file for every critical image.</div>`;
  }

  function sectionFeed() {
    const P = "feed.";
    return `
      <h2>Feed</h2>
      <div class="grid">
        ${field({ path: P + "order", label: "Post order", kind: "select", options: [["shuffle", "Shuffled per participant"], ["fixed", "Fixed (posts.csv order)"]], help: "Shuffled orders still follow the rules below." })}
        ${field({ path: P + "lead_in_fillers", label: "Fillers at the top", kind: "int", min: 0, help: "Warm-up posts before the first critical post." })}
        ${field({ path: P + "max_run_same_cell", label: "Max critical posts in a row from one cell", kind: "int", min: 1 })}
        ${field({ path: P + "min_fillers_between_critical", label: "Fillers between critical posts", kind: "int", min: 0 })}
        ${field({ path: P + "done_button_after_s", label: "“I'm done” button after (s)", kind: "nullnum", min: 0, placeholder: "never", help: "Blank = never shown." })}
        ${field({ path: P + "time_limit_s", label: "Time limit (s)", kind: "nullnum", min: 1, placeholder: "none", help: "Blank = no limit. With neither, participants scroll until the end of the feed." })}
        ${field({ path: P + "story_duration_s", label: "Seconds per story", kind: "float", min: 1, max: 60 })}
      </div>
      <h3>What participants can do</h3>
      <div class="checks-grid">
        ${field({ path: P + "allow_likes", label: "Like posts", kind: "bool" })}
        ${field({ path: P + "allow_saves", label: "Save posts", kind: "bool" })}
        ${field({ path: P + "allow_shares", label: "Send posts (shows “Sent”)", kind: "bool" })}
        ${field({ path: P + "allow_comment_likes", label: "Like comments", kind: "bool" })}
        ${field({ path: P + "allow_comment_typing", label: "Write comments and replies", kind: "bool", help: "The final text and every draft edit are logged." })}
      </div>`;
  }

  function itemEditor(base, it, j) {
    const p = `${base}.items.${j}`;
    const k = it.kind || "vas";
    return `<div class="item">
      <div class="card-head"><b>Question ${j + 1}</b><span>${btn(`move-item:${base}:${j}:-1`, "↑", "link")}${btn(`move-item:${base}:${j}:1`, "↓", "link")}${btn(`del-item:${base}:${j}`, "Remove", "link danger")}</span></div>
      <div class="grid">
        ${field({ path: `${p}.id`, label: "Id", kind: "text", help: "Column name in the data." })}
        ${field({ path: `${p}.kind`, label: "Kind", kind: "select", def: "vas", options: C.ITEM_KINDS.map((x) => [x, KIND_INFO[x]]) })}
        ${field({ path: `${p}.text`, label: "Question", kind: "text", wide: true })}
        ${k === "likert" ? field({ path: `${p}.points`, label: "Points", kind: "int", min: 2, max: 11 }) : ""}
        ${k === "likert" ? field({ path: `${p}.labels`, label: "Point labels (optional)", kind: "list", wide: true, help: "One per point, or leave blank." }) : ""}
        ${k === "vas" || k === "likert" ? field({ path: `${p}.min_label`, label: "Left end label", kind: "text" }) : ""}
        ${k === "vas" || k === "likert" ? field({ path: `${p}.max_label`, label: "Right end label", kind: "text" }) : ""}
        ${k === "choice" ? field({ path: `${p}.options`, label: "Options", kind: "list", wide: true }) : ""}
        ${field({ path: `${p}.required`, label: "Answer required", kind: "bool", def: true })}
      </div></div>`;
  }

  function stepFields(s, i) {
    const p = `procedure.${i}`;
    const d = C.STEP_DEFAULTS[s.type] || {};
    const f = (key, label, kind, extra = {}) => field({ path: `${p}.${key}`, label, kind, def: d[key], ...extra });
    switch (s.type) {
      case "instructions": return `<div class="grid">${f("title", "Title", "text")}${f("button", "Button text", "text")}${f("min_time_s", "Minimum time (s)", "float", { min: 0 })}</div>${f("text", "Text", "textarea", { rows: 4 })}`;
      case "marker_calibration": return `<div class="grid">${f("duration_s", "Duration (s)", "float", { min: 1, max: 30 })}</div>`;
      case "camera_check": return `<div class="grid">${f("min_face_s", "Face in view for (s)", "float", { min: 0.5, max: 30 })}${f("instructions", "Instructions", "text", { wide: true })}</div>`;
      case "profile_photo": return `${f("text", "Text", "textarea")}${f("allow_skip", "Participants can skip it", "bool")}`;
      case "validation": return `<div class="grid">${f("points", "Dots", "select", { num: true, options: [[5, "5"], [9, "9"], [13, "13"]] })}${f("target_dp", "Dot size (dp)", "int", { min: 12, max: 80 })}${f("instructions", "Instructions", "text", { wide: true })}</div>`;
      case "questionnaire":
      case "image_rating": {
        const items = s.items || [];
        return `<div class="grid">${f("title", "Title", "text")}${s.type === "questionnaire" ? f("randomize", "Shuffle question order", "bool") : f("posts", "Posts to rate", "select", { options: [["critical", "Critical posts"], ["all", "All posts"]] })}</div>
          ${items.map((it, j) => itemEditor(p, it, j)).join("")}${btn(`add-item:${p}`, "+ Add question")}`;
      }
      case "feed": return f("instructions", "Text shown before the feed (optional)", "textarea");
      case "recognition": return `<div class="grid">${f("question", "Question", "text", { wide: true })}
          ${f("lures", "Lures", "select", { options: [["both", "Foils and the other version"], ["foils", "Foils only"], ["alternate_version", "The other version only"]] })}
          ${f("confidence", "Ask how sure they are", "bool")}</div>
          ${(s.lures || "both") !== "alternate_version" ? help(`Foils: ${(s.foils || []).map((x) => `<code>${esc(x)}</code>`).join(", ") || "none yet"}. Set how many under Content; images.csv gets a row for each.`) : ""}`;
      case "end": return f("text", "Text", "textarea");
      default: return help("This step type isn't known to the builder; it is kept as it is.");
    }
  }

  function sectionProcedure() {
    const steps = ui.study.procedure || [];
    const cards = steps.map((s, i) => {
      const open = ui.openStep === i;
      const info = STEP_INFO[s.type] || [s.type, ""];
      return `<div class="card step ${open ? "open" : ""}">
        <div class="card-head">
          <button type="button" class="step-title" data-action="toggle-step:${i}"><span class="num">${i + 1}</span><span class="badge">${esc(info[0])}</span> ${esc(s.id || "")}</button>
          <span>${btn(`move-step:${i}:-1`, "↑", "link", 'title="Move up"')}${btn(`move-step:${i}:1`, "↓", "link", 'title="Move down"')}${btn(`del-step:${i}`, "Remove", "link danger")}</span>
        </div>
        ${open ? `${help(info[1])}<div class="grid">${field({ path: `procedure.${i}.id`, label: "Step id", kind: "text", help: "Names the step in the data." })}</div>${stepFields(s, i)}` : ""}
      </div>`;
    }).join("");
    return `
      <h2>Procedure</h2>
      <p class="lead">The screens a participant goes through, in order. Click a step to edit it.</p>
      ${cards}
      <div class="row add-step"><select id="new-step">${C.STEP_TYPES.filter((t) => t !== "end").map((t) => `<option value="${t}">${STEP_INFO[t][0]}</option>`).join("")}</select>${btn("add-step", "+ Add step", "primary")}</div>
      <p class="hint">New steps go before the end screen.</p>`;
  }

  function sectionRecording() {
    const L = "logging.";
    const cam = val("logging.front_camera.enabled", false);
    const camSteps = val("logging.front_camera.steps", ["feed"]);
    const ids = (ui.study.procedure || []).map((s) => s.id).filter(Boolean);
    return `
      <h2>Recording</h2>
      <p class="lead">Gaze (from the Neon glasses), where every post is on screen, interactions, answers and
      session-quality events are always recorded. These are the optional extras.</p>
      <div class="card">
        ${field({ path: L + "touches", label: "Touch points", kind: "bool", help: "Every finger down / move / up. Needed for gestures and for spotting a finger covering part of an image. Cheap; keep it on." })}
      </div>
      <div class="card">
        ${field({ path: L + "sensors", label: "Motion sensors", kind: "bool", help: "Accelerometer, gyroscope and rotation: how the phone is held and moved. Useful for cleaning gaze data; small files." })}
        ${val("logging.sensors", false) ? `<div class="grid">${field({ path: L + "sensor_hz", label: "Samples per second", kind: "int", min: 5, max: 200 })}</div>` : ""}
      </div>
      <div class="card">
        ${field({ path: L + "front_camera.enabled", label: "Front camera video of the face", kind: "bool", help: "For facial-expression analysis. Android shows a camera indicator while recording, which may make people more self-aware; pilot it. Uses battery and warms the phone." })}
        ${cam ? `<div class="grid">
          ${field({ path: L + "front_camera.resolution", label: "Resolution", kind: "select", def: "720p", options: [["480p", "480p"], ["720p", "720p (recommended)"], ["1080p", "1080p"]] })}
          ${field({ path: L + "front_camera.fps", label: "Frames per second", kind: "select", def: 30, num: true, options: [[15, "15"], [24, "24"], [30, "30"]] })}
          ${field({ path: L + "front_camera.bitrate_mbps", label: "Bitrate (Mbit/s)", kind: "float", min: 0.5, max: 20, def: 3 })}
          ${field({ path: L + "front_camera.segment_s", label: "New file every (s)", kind: "int", min: 10, max: 600, def: 60, help: "A crash loses at most one file." })}
        </div>
        <h4>Steps to record</h4>
        <label class="check"><input type="checkbox" data-action-change="cam-all" ${camSteps === "all" ? "checked" : ""}> <span>All steps</span></label>
        ${camSteps === "all" ? "" : `<div class="checks-grid">${ids.map((id) => `<label class="check"><input type="checkbox" data-action-change="cam-step:${esc(id)}" ${Array.isArray(camSteps) && camSteps.includes(id) ? "checked" : ""}> <span>${esc(id)}</span></label>`).join("")}</div>`}` : ""}
      </div>
      <div class="card">
        ${field({ path: L + "screen_recording", label: "Screen recording (pilots only)", kind: "bool", help: "Records exactly what was on screen, to check the gaze mapping. Android asks for permission every session and it costs performance. Not built in the app yet; can't be combined with the front camera." })}
        ${val("logging.screen_recording", false) ? `<div class="grid">${field({ path: L + "screen_recording_fps", label: "Frames per second", kind: "int", min: 5, max: 60 })}</div>` : ""}
      </div>
      <h3>Eye tracker</h3>
      <div class="card">
        ${field({ path: "neon.required", label: "Require the Neon glasses to start a session", kind: "bool", help: "Neon control in the app isn't built yet; leave this off for now." })}
        ${field({ path: "neon.auto_record", label: "Start and stop the Neon recording from the app", kind: "bool" })}
      </div>`;
  }

  function sectionParticipants() {
    const b = C.blockSize(ui.study);
    const n = Number(val("participants.n_plans")) || 0;
    const pre = val("participants.id_prefix"), dig = Number(val("participants.id_digits")) || 3;
    const id = (k) => pre + String(k).padStart(dig, "0");
    const lo = Math.max(b, Math.floor(n / b) * b), hi = Math.ceil(n / b) * b;
    return `
      <h2>Participants</h2>
      <p class="lead">The compiler writes one plan per participant id. Participants are balanced in blocks of
      <b>${b}</b> (${C.groups(ui.study)} group(s) x ${C.cells(ui.study)} cell(s)): every complete block sees every
      combination equally often. Recruit in multiples of the block too.</p>
      <div class="grid">
        ${field({ path: "participants.n_plans", label: "Number of plans", kind: "int", min: 1, max: 5000, help: "Make more plans than you expect to need; unused ones do no harm." })}
        ${field({ path: "participants.id_prefix", label: "Id prefix", kind: "text" })}
        ${field({ path: "participants.id_digits", label: "Digits", kind: "int", min: 1, max: 6 })}
      </div>
      ${b > 1 && n % b ? `<div class="row">${btn(`set-n:${lo}`, `Use ${lo}`)}${hi !== lo ? btn(`set-n:${hi}`, `Use ${hi}`) : ""}</div>` : ""}
      <div class="summary">Ids: <code>${esc(id(1))}</code>, <code>${esc(id(2))}</code> … <code>${esc(id(n))}</code></div>`;
  }

  /** The Download section as it is in the desktop app: save into the study folder. */
  function sectionSave() {
    const files = C.studyFiles(ui.study, ui.content, true);
    if (!files[ui.previewFile]) ui.previewFile = "study.yaml";
    const errors = C.checks(ui.study, ui.content).filter((c) => c.level === "error");
    const s = ui.saved;
    return `
      <h2>Save</h2>
      ${errors.length ? `<p class="error-box">The design has ${errors.length === 1 ? "1 problem" : `${errors.length} problems`} (see the list on the right). You can still save and fix ${errors.length === 1 ? "it" : "them"} later.</p>` : ""}
      <div class="card">
        ${ui.folder
          ? `<p>Study folder: <b class="folder">${esc(ui.folder)}</b> ${unsaved() ? `<span class="pill">unsaved changes</span>` : ""}</p>
             <div class="row">${btn("save", "Save to study folder", "primary", ui.busy ? "disabled" : "")}${btn("check-folder", "Check study", "", ui.busy ? "disabled" : "")}${btn("save-new", "Save as a new study…", "link", ui.busy ? "disabled" : "")}</div>`
          : `<p>This study isn't saved yet. Choose the folder to put it in (usually <code>studies</code>); a new folder named <code>${esc(ui.study.id || "…")}</code> is made inside it.</p>
             <div class="row">${btn("save-new", "Save to a new folder…", "primary", ui.busy ? "disabled" : "")}</div>`}
        ${ui.busy ? `<p class="hint">${esc(ui.busy)}</p>` : ""}
        ${s ? `<p class="hint">Saved at ${clock(s.at)}: wrote ${s.written.map((f) => `<code>${esc(f)}</code>`).join(", ")}${s.kept.length ? `; kept your existing ${s.kept.map((f) => `<code>${esc(f)}</code>`).join(", ")}` : ""}${s.backup ? `. The previous study.yaml is in <code>study.yaml.bak</code>` : ""}.</p>` : ""}
      </div>
      <p class="hint">Saving writes <code>study.yaml</code> and creates the CSV files and NEXT_STEPS.txt only if they don't exist yet:
      your CSV files are never overwritten. The previous study.yaml is kept as <code>study.yaml.bak</code>.
      ${ui.hadComments ? "<b>Your study.yaml has comments (# …); they are not kept when you save.</b>" : ""}
      After saving, the study is checked like <code>socialeyes validate</code> does: images, AOIs and CSV contents (list on the right).</p>
      <div class="tabs">${Object.keys(files).map((f) => `<button type="button" class="tab ${f === ui.previewFile ? "on" : ""}" data-action="preview:${esc(f)}">${esc(f)}</button>`).join("")}</div>
      <pre class="preview">${esc(files[ui.previewFile])}</pre>`;
  }

  function sectionDownload() {
    if (ui.desktop) return sectionSave();
    const files = C.studyFiles(ui.study, ui.content, ui.withCsv);
    if (!files[ui.previewFile]) ui.previewFile = "study.yaml";
    const errors = C.checks(ui.study, ui.content).filter((c) => c.level === "error");
    return `
      <h2>Download</h2>
      ${errors.length ? `<p class="error-box">There ${errors.length === 1 ? "is 1 problem" : `are ${errors.length} problems`} that <code>socialeyes validate</code> will reject (see the list on the right). You can still download and fix them later.</p>` : `<p class="ok-box">No problems found. <code>socialeyes validate</code> will also check your images, AOIs and CSV contents.</p>`}
      <label class="check"><input type="checkbox" data-path="ui.withCsv" data-kind="bool" data-ui="1" ${ui.withCsv ? "checked" : ""}> <span>Include CSV skeletons and NEXT_STEPS.txt</span></label>
      ${ui.opened && ui.withCsv ? `<p class="hint">Careful: unzipping over your study folder would replace your existing CSV files.</p>` : ""}
      <div class="row">${btn("download-zip", `Download ${esc(ui.study.id || "study")}.zip`, "primary")}${btn("download-yaml", "Download study.yaml only")}</div>
      <p class="hint">Unzip into <code>studies/</code>, then follow NEXT_STEPS.txt.</p>
      <div class="tabs">${Object.keys(files).map((f) => `<button type="button" class="tab ${f === ui.previewFile ? "on" : ""}" data-action="preview:${esc(f)}">${esc(f)}</button>`).join("")}</div>
      <pre class="preview">${esc(files[ui.previewFile])}</pre>`;
  }

  const RENDER = {
    start: sectionStart, basics: sectionBasics, design: sectionDesign, content: sectionContent, feed: sectionFeed,
    procedure: sectionProcedure, recording: sectionRecording, participants: sectionParticipants, download: sectionDownload,
  };

  // ------------------------------------------------------------ side panel

  function renderSide() {
    const side = document.getElementById("side");
    if (!ui.study) { side.innerHTML = `<p class="hint">Start a study to see checks here.</p>`; return; }
    const list = C.checks(ui.study, ui.content);
    const icon = { error: "✕", warning: "!", tip: "i" };
    const order = { error: 0, warning: 1, tip: 2 };
    list.sort((a, b) => order[a.level] - order[b.level]);
    side.innerHTML = `
      <h3>${esc(ui.study.title || ui.study.id || "Untitled")}</h3>
      <p class="design-line">${esc(C.designSummary(ui.study))}</p>
      <dl class="stats"><dt>Cells</dt><dd>${C.cells(ui.study)}</dd><dt>Groups</dt><dd>${C.groups(ui.study)}</dd><dt>Block</dt><dd>${C.blockSize(ui.study)}</dd><dt>Steps</dt><dd>${(ui.study.procedure || []).length}</dd></dl>
      <h3>Checks</h3>
      ${list.length ? `<ul class="checks">${list.map((c) => `<li class="${c.level}"><button type="button" data-action="goto:${c.section}"><span class="ic">${icon[c.level]}</span><span>${esc(c.msg)}</span></button></li>`).join("")}</ul>` : `<p class="ok-box">All good.</p>`}
      ${ui.desktop ? folderChecks() : ""}`;
    const counts = {};
    for (const c of list) if (c.level === "error") counts[c.section] = (counts[c.section] || 0) + 1;
    document.querySelectorAll("#nav button").forEach((b) => {
      const n = counts[b.dataset.section];
      b.querySelector(".count").textContent = n ? String(n) : "";
    });
  }

  /** The compiler's checks of the saved folder (desktop app only). */
  function folderChecks() {
    const head = `<h3>Study folder</h3>${ui.desktopError ? `<p class="error-box">${esc(ui.desktopError)}</p>` : ""}`;
    if (!ui.folder) return `${head}<p class="hint">Save the study to a folder to check its images, AOIs and CSV files too.</p>`;
    const k = ui.compiler;
    const items = k ? [...k.errors.map((m) => ["error", "✕", m]), ...k.warnings.map((m) => ["warning", "!", m])] : [];
    return `${head}
      ${unsaved() ? `<p class="hint"><span class="pill">unsaved changes</span> These checks are of the saved files. ${btn("save", "Save", "link", ui.busy ? "disabled" : "")}</p>` : ""}
      ${!k ? `<p class="hint">Not checked yet.</p>`
        : items.length ? `<ul class="checks">${items.map(([lv, ic, m]) => `<li class="${lv}"><div class="msg"><span class="ic">${ic}</span><span>${esc(m)}</span></div></li>`).join("")}</ul>`
        : `<p class="ok-box">Images, AOIs and CSV files all check out.</p>`}
      <p class="hint">${k ? `Checked at ${clock(k.at)}. ` : ""}${btn("check-folder", ui.busy === "Checking…" ? "Checking…" : "Check study", "link", ui.busy ? "disabled" : "")}</p>`;
  }

  // ------------------------------------------------------------ render

  const sectionLabel = (k, label) => (k === "download" && ui.desktop ? "Save" : label);

  /** The desktop app's tabs; every tab but Design is a placeholder until it is built. */
  function renderApp() {
    const tabs = document.getElementById("apptabs");
    tabs.hidden = !ui.desktop;
    const onDesign = !ui.desktop || ui.tab === "design";
    document.querySelector(".layout").hidden = !onDesign;
    const page = document.getElementById("tabpage");
    page.hidden = onDesign;
    if (!ui.desktop) return true;
    document.getElementById("app-title").textContent = "SocialEyes";
    document.getElementById("app-sub").hidden = true;
    tabs.innerHTML = APP_TABS.map(([k, label]) => `<button type="button" data-action="tab:${k}" class="${ui.tab === k ? "on" : ""}">${label}</button>`).join("");
    if (!onDesign) {
      const [, label, text] = APP_TABS.find(([k]) => k === ui.tab);
      page.innerHTML = `<h2>${label}</h2><p class="lead">${text}</p><p class="hint">Coming in a later version of the desktop app.</p>`;
    }
    return onDesign;
  }

  function render() {
    if (!renderApp()) return;
    const focused = document.activeElement && document.activeElement.dataset ? document.activeElement.dataset.key : null;
    let sel = null;
    try { sel = focused ? [document.activeElement.selectionStart, document.activeElement.selectionEnd] : null; } catch (e) { sel = null; }
    document.getElementById("nav").innerHTML = SECTIONS.map(([k, label]) =>
      `<button type="button" data-section="${k}" class="${ui.section === k ? "on" : ""}" ${!ui.study && k !== "start" ? "disabled" : ""}>${sectionLabel(k, label)}<span class="count"></span></button>`).join("");
    const main = document.getElementById("main");
    main.innerHTML = (ui.study || ui.section === "start" ? RENDER[ui.section]() : sectionStart()) + navButtons();
    renderSide();
    if (focused) {
      const el = main.querySelector(`[data-key="${CSS.escape(focused)}"]`);
      if (el) { el.focus(); try { if (sel && sel[0] != null) el.setSelectionRange(sel[0], sel[1]); } catch (e) { /* not a text field */ } }
    }
    save();
  }

  function navButtons() {
    if (!ui.study) return "";
    const i = SECTIONS.findIndex(([k]) => k === ui.section);
    const prev = SECTIONS[i - 1], next = SECTIONS[i + 1];
    return `<div class="pager">${prev ? btn(`goto:${prev[0]}`, `← ${sectionLabel(...prev)}`) : "<span></span>"}${next ? btn(`goto:${next[0]}`, `${sectionLabel(...next)} →`, "primary") : ""}</div>`;
  }

  /** Keeps the draft in the browser's storage, so it survives closing the page. */
  function save() {
    if (!ui.study) return;
    try {
      localStorage.setItem(STORE, JSON.stringify({ study: ui.study, content: ui.content, withCsv: ui.withCsv, opened: ui.opened,
        folder: ui.folder, savedYaml: ui.savedYaml, hadComments: ui.hadComments }));
    } catch (e) { /* storage unavailable */ }
  }

  // ------------------------------------------------------------ editing helpers

  /** Keep factor mappings in line with their levels (new level -> empty entry, removed level -> dropped). */
  function normalizeFactors() {
    for (const f of ui.study.factors || []) {
      for (const [a, spec] of Object.entries(f.sets || {})) {
        if (spec && typeof spec === "object") {
          const m = {};
          for (const lv of f.levels || []) m[lv] = lv in spec ? spec[lv] : (a === "label" ? null : "");
          f.sets[a] = m;
        }
      }
    }
  }

  function uniqueId(base, taken) {
    if (!taken.includes(base)) return base;
    let k = 2;
    while (taken.includes(base + k)) k++;
    return base + k;
  }

  const STEP_ID_BASE = { instructions: "info", marker_calibration: "cal", validation: "val", camera_check: "camcheck", profile_photo: "photo",
    questionnaire: "q", feed: "feed", image_rating: "ratings", recognition: "recog", end: "end" };

  function newStep(type) {
    const ids = (ui.study.procedure || []).map((s) => s.id);
    const s = { id: uniqueId(STEP_ID_BASE[type] + (["feed", "end", "photo", "camcheck"].includes(STEP_ID_BASE[type]) ? "" : "1"), ids), type };
    if (type === "instructions") s.text = "";
    if (type === "questionnaire" || type === "image_rating") s.items = [{ id: uniqueId(type === "questionnaire" ? "item1" : "rating1", []), kind: type === "questionnaire" ? "vas" : "likert", text: "", ...(type === "image_rating" ? { points: 7 } : {}) }];
    if (type === "recognition") { s.lures = "both"; if (!ui.content.foils) ui.content.foils = 4; s.foils = []; }
    return s;
  }

  /** `folder`: the study folder it was opened from (desktop app), else null. */
  function load(study, content, opened, folder = null) {
    ui.study = study;
    ui.content = content;
    ui.opened = opened;
    ui.withCsv = !opened;
    ui.openStep = null;
    ui.loadError = null;
    ui.folder = folder;
    ui.savedYaml = folder ? C.toYaml(study) : null;
    ui.hadComments = false;
    ui.saved = null;
    ui.compiler = null;
    ui.desktopError = null;
    if (!opened) C.syncFoils(ui.study, ui.content);
    ui.section = "basics";
    render();
  }

  function parseStudy(text) {
    const study = jsyaml.load(text);
    if (!study || typeof study !== "object" || Array.isArray(study)) throw new Error("this file doesn't contain a study (expected settings like id:, procedure:)");
    if (!Array.isArray(study.procedure)) study.procedure = [];
    if (!Array.isArray(study.factors)) study.factors = study.factors ? [] : [];
    return study;
  }

  // ------------------------------------------------------------ study folders (desktop app)

  async function openFolder() {
    try {
      const folder = await bridge("pick_folder", null, ui.folder || (ui.appInfo && ui.appInfo.studies_dir));
      if (!folder) return;
      const r = await bridge("open_folder", "Opening…", folder);
      const study = parseStudy(r.study.yaml);
      load(study, C.contentFor(study), "study.yaml", r.study.folder);
      ui.hadComments = /^\s*#/m.test(r.study.yaml);
      ui.compiler = { ...r.check, at: new Date() };
    } catch (e) {
      ui.desktopError = `Couldn't open the study: ${e.message}`;
      ui.section = "start";
    }
    render();
  }

  /** Save into the study's folder, or (asNew / not saved yet) into a new folder named after the study id. */
  async function saveStudy(asNew) {
    const files = C.studyFiles(ui.study, ui.content, true);
    try {
      let r;
      if (ui.folder && !asNew) {
        r = await bridge("save", "Saving…", ui.folder, files);
      } else {
        const start = ui.folder ? ui.folder.replace(/[\\/][^\\/]+$/, "") : ui.appInfo && ui.appInfo.studies_dir;
        const parent = await bridge("pick_folder", null, start);
        if (!parent) return;
        r = await bridge("save_new", "Saving…", parent, ui.study.id || "", files);
      }
      ui.folder = r.saved.folder;
      ui.savedYaml = files["study.yaml"];
      ui.hadComments = false; // the saved file has none (a commented original is in study.yaml.bak)
      ui.saved = { ...r.saved, at: new Date() };
      ui.compiler = { ...r.check, at: new Date() };
      ui.desktopError = null;
    } catch (e) {
      ui.desktopError = `Couldn't save: ${e.message}`;
    }
    render();
  }

  async function checkFolder() {
    try {
      ui.compiler = { ...(await bridge("check", "Checking…", ui.folder)), at: new Date() };
      ui.desktopError = null;
    } catch (e) {
      ui.desktopError = `Couldn't check the study: ${e.message}`;
    }
    render();
  }

  function openFile(file) {
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const study = parseStudy(String(reader.result));
        load(study, C.contentFor(study), file.name);
      } catch (e) {
        ui.loadError = `Couldn't read ${file.name}: ${e.message}`;
        ui.section = "start";
        render();
      }
    };
    reader.readAsText(file);
  }

  function download(name, bytes, type) {
    const blob = new Blob([bytes], { type });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = name;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
  }

  // ------------------------------------------------------------ actions

  function act(action, el) {
    const [name, ...args] = action.split(":");
    const S = ui.study;
    switch (name) {
      case "new-blank": { const t = C.newStudy("blank"); load(t.study, t.content, null); return; }
      case "new-example": { const t = C.newStudy("example"); load(t.study, t.content, null); return; }
      case "resume": {
        try {
          const d = JSON.parse(localStorage.getItem(STORE));
          load(d.study, d.content, d.opened || null, ui.desktop ? d.folder || null : null);
          if (ui.folder) { ui.savedYaml = d.savedYaml; ui.hadComments = !!d.hadComments; }
          ui.withCsv = d.withCsv !== false;
          render();
        } catch (e) { ui.loadError = "The saved draft couldn't be read."; render(); }
        return;
      }
      case "go-basics": ui.section = "basics"; break;
      case "goto": ui.section = args[0]; window.scrollTo(0, 0); break;
      case "random-seed": S.seed = Math.floor(Math.random() * 1e8); break;
      case "add-factor": {
        S.factors = S.factors || [];
        S.factors.push({ name: uniqueId("factor" + (S.factors.length + 1), S.factors.map((f) => f.name)), design: "within", levels: ["a", "b"], sets: {} });
        break;
      }
      case "del-factor": S.factors.splice(Number(args[0]), 1); break;
      case "add-attr": {
        const f = S.factors[Number(args[0])];
        const a = document.getElementById(`add-attr-${args[0]}`).value;
        f.sets = f.sets || {};
        if (a === "label") {
          S.labels = S.labels || {};
          if (!Object.keys(S.labels).length) S.labels.edited = { text: "This image has been digitally altered", style: "banner" };
          const first = Object.keys(S.labels)[0];
          f.sets.label = Object.fromEntries((f.levels || []).map((lv, k) => [lv, k === 0 ? null : first]));
        } else if (a === "like_count") {
          f.sets.like_count = Object.fromEntries((f.levels || []).map((lv, k) => [lv, String([50, 5000, 500, 50000][k % 4])]));
        } else f.sets[a] = "{level}";
        break;
      }
      case "del-attr": delete S.factors[Number(args[0])].sets[args[1]]; break;
      case "add-label": {
        const key = (document.getElementById("new-label").value || "").trim();
        if (!key) return;
        S.labels = S.labels || {};
        if (!S.labels[key]) S.labels[key] = { text: "", style: "banner" };
        break;
      }
      case "del-label": delete S.labels[args[0]]; break;
      case "toggle-step": ui.openStep = ui.openStep === Number(args[0]) ? null : Number(args[0]); break;
      case "move-step": {
        const i = Number(args[0]), j = i + Number(args[1]);
        if (j < 0 || j >= S.procedure.length) return;
        [S.procedure[i], S.procedure[j]] = [S.procedure[j], S.procedure[i]];
        if (ui.openStep === i) ui.openStep = j;
        break;
      }
      case "del-step": S.procedure.splice(Number(args[0]), 1); ui.openStep = null; break;
      case "add-step": {
        const type = document.getElementById("new-step").value;
        const s = newStep(type);
        const endAt = S.procedure.length && S.procedure[S.procedure.length - 1].type === "end" ? S.procedure.length - 1 : S.procedure.length;
        S.procedure.splice(endAt, 0, s);
        if (type === "recognition") C.syncFoils(S, ui.content);
        ui.openStep = endAt;
        break;
      }
      case "add-item": {
        const items = getP(`${args[0]}.items`) || [];
        items.push({ id: uniqueId("item" + (items.length + 1), items.map((x) => x.id)), kind: "vas", text: "" });
        setP(`${args[0]}.items`, items);
        break;
      }
      case "del-item": getP(`${args[0]}.items`).splice(Number(args[1]), 1); break;
      case "move-item": {
        const items = getP(`${args[0]}.items`);
        const i = Number(args[1]), j = i + Number(args[2]);
        if (j < 0 || j >= items.length) return;
        [items[i], items[j]] = [items[j], items[i]];
        break;
      }
      case "set-n": setP("participants.n_plans", Number(args[0])); break;
      case "preview": ui.previewFile = args.join(":"); break;
      case "download-zip": {
        const files = C.studyFiles(S, ui.content, ui.withCsv);
        download(`${S.id || "study"}.zip`, C.zip(files, S.id || "study"), "application/zip");
        return;
      }
      case "download-yaml": download("study.yaml", C.toYaml(S), "text/yaml"); return;
      case "tab": ui.tab = args[0]; window.scrollTo(0, 0); break;
      case "open-folder": openFolder(); return;
      case "save": saveStudy(false); return;
      case "save-new": saveStudy(true); return;
      case "check-folder": checkFolder(); return;
      default: return;
    }
    render();
  }

  function actChange(action, el) {
    const [name, ...args] = action.split(":");
    const S = ui.study;
    if (name === "custom-map") {
      const f = S.factors[Number(args[0])];
      const a = args[1];
      f.sets[a] = el.checked ? Object.fromEntries((f.levels || []).map((lv) => [lv, lv])) : "{level}";
    } else if (name === "cam-all") {
      setP("logging.front_camera.steps", el.checked ? "all" : ["feed"]);
    } else if (name === "cam-step") {
      let steps = val("logging.front_camera.steps", ["feed"]);
      steps = Array.isArray(steps) ? steps.slice() : [];
      const id = args.join(":");
      if (el.checked && !steps.includes(id)) steps.push(id);
      if (!el.checked) steps = steps.filter((x) => x !== id);
      const order = S.procedure.map((s) => s.id);
      steps.sort((x, y) => order.indexOf(x) - order.indexOf(y));
      setP("logging.front_camera.steps", steps);
    }
    render();
  }

  /** Apply an input's value to the study (or the builder's content numbers). */
  function applyInput(el, commit) {
    const path = el.dataset.path;
    const v = parseInput(el);
    if (el.dataset.ui) { ui.withCsv = v; return; }
    if (path.startsWith("content.")) {
      const key = path.slice(8);
      ui.content[key] = typeof v === "number" ? Math.max(0, v) : v === undefined ? 0 : v;
      if (key === "foils") C.syncFoils(ui.study, ui.content);
      return;
    }
    const oldId = path.match(/^procedure\.(\d+)\.id$/) ? getP(path) : null;
    setP(path, v);
    // only once typing is done: half-typed levels would drop the choices made for the others
    if (commit && /^factors\.\d+\.levels$/.test(path)) normalizeFactors();
    if (oldId !== null) {   // a renamed step stays chosen for the front camera
      const camSteps = getP("logging.front_camera.steps");
      if (Array.isArray(camSteps)) setP("logging.front_camera.steps", camSteps.map((x) => (x === oldId ? v : x)));
    }
  }

  // ------------------------------------------------------------ wiring

  document.addEventListener("click", (e) => {
    const nav = e.target.closest("#nav button");
    if (nav && !nav.disabled) { ui.section = nav.dataset.section; render(); window.scrollTo(0, 0); return; }
    const b = e.target.closest("[data-action]");
    if (b) act(b.dataset.action, b);
  });

  document.addEventListener("input", (e) => {
    const el = e.target;
    if (!el.dataset || !el.dataset.path || el.dataset.kind === "bool" || el.tagName === "SELECT") return;
    applyInput(el);
    renderSide();
    save();
  });

  document.addEventListener("change", (e) => {
    const el = e.target;
    if (el.id === "open-file" && el.files && el.files[0]) { openFile(el.files[0]); return; }
    if (el.dataset && el.dataset.actionChange) { actChange(el.dataset.actionChange, el); return; }
    if (!el.dataset || !el.dataset.path) return;
    applyInput(el, true);
    setTimeout(render, 0); // after the focus has moved, so render() can put it back
  });

  document.addEventListener("dragover", (e) => { if (ui.section === "start") e.preventDefault(); });
  document.addEventListener("drop", (e) => {
    if (ui.section !== "start") return;
    e.preventDefault();
    const f = e.dataTransfer && e.dataTransfer.files[0];
    if (f) openFile(f);
  });

  // Inside the desktop app, pywebview adds window.pywebview.api (possibly after this script runs).
  async function enterDesktop() {
    if (ui.desktop || !(window.pywebview && window.pywebview.api)) return;
    ui.desktop = true;
    try { ui.appInfo = await bridge("app_info", null); } catch (e) { ui.desktopError = e.message; }
    render();
  }
  window.addEventListener("pywebviewready", enterDesktop);

  render();
  enterDesktop();
})();
