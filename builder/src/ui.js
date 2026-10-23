// SocialEyes experiment builder: the form. Logic lives in core.js.
(() => {
  "use strict";
  const C = Core;
  const STORE = "socialeyes-builder-draft";
  const ADVANCED_STORE = "socialeyes-builder-advanced";

  const ui = {
    study: null, content: null, section: "start", withCsv: true,
    advanced: false,        // show the advanced settings (remembered on this computer)
    hidden: [],             // advanced settings left out of the section being drawn: {label, changed}
    opened: null,           // file name when the study came from a study.yaml
    openStep: null,         // procedure card that is expanded
    previewFile: "study.yaml",
    loadError: null,
    // inside the desktop app (socialeyes app) only
    desktop: false,         // the Python bridge is available
    appInfo: null,          // {version, studies_dir}
    tab: "studies",         // app page: studies (home), or the open study's design, phone, data
    folder: null,           // the study folder this study is saved in
    savedYaml: null,        // study.yaml as last saved or opened, to spot unsaved changes
    hadComments: false,     // the opened study.yaml had comments, which saving drops
    saved: null,            // result of the last save: {written, kept, backup, at}
    compiler: null,         // the compiler's checks of the folder: {errors, warnings, at}
    busy: null,             // what the bridge is doing ("Saving…"), shown while it works
    desktopError: null,
    sessions: 0,            // sessions already collected with this study (from its register)
    protect: null,          // a save refused because it would break them: {reasons, sessions, version}
    // Phone tab: result of the last phone check / load, and the choices on the tab
    phone: { result: null, serial: "", devices: [], updateApp: false, progress: null, error: null,
      setup: null, setupOpen: false, setupNote: null, setupError: null },
    // Data tab: the study's folders and register, the phone's sessions, the last unload
    data: { status: null, unload: null, export: null, faces: null, gaze: null, heatmaps: null, blur: false, by: "cell", unblind: false, error: null },
    studies: { list: null, newId: "", error: null },
    files: { result: null, missingOnly: true, error: null },   // the study folder's files (Design > Content)
    // Design > Content: adding images from a folder, and the image check
    images: { match: null, assign: {}, replace: false, copied: null, report: null, resized: null, error: null },
    aois: { result: null, overwrite: false, error: null },     // the last automatic AOIs (Design > Content)
    preview: { result: null, pid: null, conditions: false, error: null },   // Design > Preview (desktop)
    // undo/redo: the study (and content numbers) as JSON before each change; typing in one field is one step
    history: { past: [], future: [], last: null, key: null, at: 0 },
  };

  const DRAFT_PREFIX = STORE + ":";   // the desktop app's unsaved changes, one draft per study folder
  const TYPING_MS = 2000;             // typing in the same field within this counts as one undo step
  const HISTORY_MAX = 200;

  /** The open study's pages in the desktop app; Studies (the home page) comes first. */
  const APP_TABS = [["design", "Design"], ["phone", "Phone"], ["data", "Data"]];

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
  /** Switching away would lose something: unsaved changes, or a new study never saved (desktop app). */
  const wouldLose = () => unsaved() || (ui.desktop && ui.study && ui.folder === null);
  // without a trailing full stop ("9:56 p.m." in some locales), as it is followed by one
  const clock = (d) => d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }).replace(/\.$/, "");

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
    tag_ladder: ["Tag size check", "Setup test, not for participants: tags in several sizes and edge distances while the phone is held in different ways, to choose the on-screen tag size for these glasses and phone (the sizes, insets and holds it tries are set in the study file)."],
    display_calibration: ["Display calibration (retired)", "Retired: set the screen brightness and scene camera exposure under Recording instead, chosen with a Settings test step. Kept so older studies still run. It found the screen brightness and Neon scene camera exposure at which the on-screen tags read best without blowing out the screen. A laptop runs socialeyes calibrate-display during it (about 30 s); the researcher can skip it. Put it before the first marker calibration."],
    settings_test: ["Settings test", "Setup test with the Neon, not for participants: the app steps through screen brightness x scene camera exposure itself (no laptop) with the study's tags in the bars, to choose the screen brightness and scene camera exposure (Recording) for phone-only sessions. The levels it tries are set in the study file; score it with python -m socialeyes.gaze.settings_test."],
    validation: ["Validation", "Dots to look at and tap: measures eye-tracking accuracy on the phone."],
    camera_check: ["Camera check", "Researcher-run framing check for the front camera. Shows a guide and whether a face is detected, never the video."],
    profile_photo: ["Profile photo", "Optional selfie as the participant's profile picture; kept in memory only and deleted when the session ends."],
    questionnaire: ["Questionnaire", "Questions on one screen: sliders (VAS), Likert scales, choices, text or numbers."],
    feed: ["Feed", "The mock social media feed. Exactly one per study."],
    image_rating: ["Image ratings", "Each post's image again, with questions about it."],
    recognition: ["Recognition test", "Images one at a time: \"did you see exactly this image?\". Lures are images not shown: foils (never in the feed) and/or the other version of a post."],
    end: ["End", "The last screen. The session is saved when it appears."],
  };

  /** Setup steps, offered under "Add step" only with advanced settings on. */
  const ADVANCED_STEPS = ["tag_ladder", "settings_test"];
  /** Kept for older studies, never offered under "Add step". */
  const RETIRED_STEPS = ["display_calibration"];

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

  const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

  /** Whether the study sets `path` to something other than its default. */
  function changed(path, def) {
    const v = getP(path);
    return v !== undefined && !same(v, def !== undefined ? def : C.get({}, path));
  }

  /**
   * Advanced-only html: shown with "Advanced settings" on; otherwise left out and listed under
   * the section (moreSettings), saying when the study has changed it.
   */
  function advanced(label, isChanged, html) {
    if (ui.advanced) return html;
    ui.hidden.push({ label, changed: !!isChanged });
    return "";
  }

  /** Under a section: the advanced settings it has, when they are hidden. */
  function moreSettings() {
    const h = ui.hidden;
    if (ui.advanced || !h.length) return "";
    const names = [...new Set(h.map((x) => x.label))];
    const ch = [...new Set(h.filter((x) => x.changed).map((x) => x.label))];
    return `<p class="more-settings" title="${esc(names.join(", "))}">${names.length} more setting${names.length === 1 ? "" : "s"} under Advanced${ch.length
      ? ` <span class="pill">changed</span> ${ch.map(esc).join(", ")}` : ""} ${btn("advanced-on", "Show", "link")}</p>`;
  }

  /**
   * One form field bound to a path in the study (or "content.x" for builder-only numbers).
   * kind: text | textarea | int | float | nullnum | bool | select | list | lines (a list, one per line)
   * adv: only shown with "Advanced settings" on.
   */
  function field(o) {
    if (o.adv) return advanced(o.label.replace(/<[^>]*>/g, ""), changed(o.path, o.def), field({ ...o, adv: false }));
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
    } else if (o.kind === "lines") {
      input = `<textarea ${attrs} rows="${o.rows || 3}" placeholder="${esc(o.placeholder || "one per line")}">${esc((cur || []).join("\n"))}</textarea>`;
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
    if (k === "lines") return el.value.split("\n").map((s) => s.trim()).filter((s) => s !== "");
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
      <div class="hero"><div><h2>Design your study</h2>
      <p>The builder walks you through the decisions for a SocialEyes study and writes
      <code>study.yaml</code> plus CSV files with a row for every piece of content your design needs.
      ${ui.desktop ? "Everything stays on this computer." : "Everything stays in this browser; nothing is uploaded."}</p></div></div>
      <p class="lead">Settings most studies can leave as they are are tucked away. Once you know your way around,
      tick <b>Advanced settings</b> in the menu on the left to see them all.</p>
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
      ${sessionsNote()}
      <div class="grid">
        ${field({ path: "id", label: "Study id", kind: "text", placeholder: "my_study", help: "Names the study's folder and data. Letters, digits, - and _; don't change it once you collect data." })}
        ${field({ path: "title", label: "Title", kind: "text", wide: true })}
        ${field({ path: "version", label: "Version", kind: "int", def: 1, min: 1, adv: true, help: "Raise it when you change the study after piloting. Saving asks for a new version when it's needed." })}
        ${advanced("Seed", false, `<div class="field"><label for="f_seed">Seed</label><div class="row"><input type="number" id="f_seed" data-path="seed" data-kind="int" data-key="seed" value="${esc(val("seed", 1))}">${btn("random-seed", "Random")}</div>
          ${help("Decides every participant's plan (post order, conditions). Same seed = same plans. Never change it once data collection has started.")}</div>`)}
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
        ${field({ path: `${p}.levels`, label: "Levels", kind: "list", placeholder: "e.g. original, retouched", wide: true, help: "At least 2, separated by commas. They name the conditions in the data and the CSV files." })}
        ${f.design === "between" ? field({ path: `${p}.applies_to`, label: "Applies to", kind: "select", def: "critical", adv: true, options: [["critical", "Critical posts only"], ["all", "All posts (fillers too)"]], help: "With all posts, every filler needs the content for each level too." }) : ""}
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
      const values = levels.map((l) => (custom ? (spec || {})[l] : String(spec).replace(/\{level\}/g, l)));
      const plain = help(`Values: ${values.map((v) => `<code>${esc(v)}</code>`).join(", ") || "…"}${custom || spec !== "{level}" ? "" : " (the level names)"}`);
      let names = `<label class="check"><input type="checkbox" data-action-change="custom-map:${i}:${attr}" ${custom ? "checked" : ""}> <span>Use different names than the level names</span></label>`;
      if (custom) names += `<div class="grid">${levels.map((lv) => field({ path: `${base}.${lv}`, label: `Level “${esc(lv)}”`, kind: "text" })).join("")}</div>`;
      else if (spec !== "{level}") names += field({ path: base, label: "Template", kind: "text", help: "{level} is replaced by the level name." });
      else names += plain;
      body = advanced("Names used in the CSV files", spec !== "{level}", names) || plain;
    }
    return `<div class="control"><div class="card-head"><b>${ATTR_INFO[attr][0]}</b>${btn(`del-attr:${i}:${attr}`, "Remove", "link danger")}</div>${help(ATTR_INFO[attr][1])}${body}</div>`;
  }

  function sectionDesign() {
    const fs = ui.study.factors || [];
    const needLabels = fs.some((f) => (f.sets || {}).label !== undefined) || Object.keys(ui.study.labels || {}).length;
    const c = C.cells(ui.study), g = C.groups(ui.study);
    return `
      <h2>Design</h2>
      <p class="lead">Each <b>factor</b> changes something about the <b>critical posts</b>; the other posts are fillers.</p>
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
      <p class="lead">How many of each the CSV files get rows for${ui.opened ? (ui.desktop ? " (only CSV files that don't exist yet)" : " (only if you download CSV skeletons)") : ""}.</p>
      <div class="grid">
        ${field({ path: "content.critical", label: "Critical posts", kind: "int", min: 0, help: c > 1 ? `A multiple of ${c} (the number of within-subject cells), so everyone sees each cell equally often.` : "Posts that carry the manipulation." })}
        ${field({ path: "content.fillers", label: "Filler posts", kind: "int", min: 0, help: "Unmanipulated posts around the critical ones. More fillers make the manipulation less obvious." })}
        ${field({ path: "content.accounts", label: "Accounts", kind: "int", min: 1, help: "Fake poster accounts; posts are spread over them." })}
        ${featureOn("stories") && !hasTable("stories") ? field({ path: "content.stories", label: "Stories", kind: "int", min: 1, help: "Images behind the story circles. Switch stories off under Procedure." }) : ""}
        ${featureOn("reels") && !hasTable("reels") ? field({ path: "content.reels", label: "Reels", kind: "int", min: 1, help: "Short videos in the Reels tab. Switch reels off under Procedure." }) : ""}
        ${rec ? field({ path: "content.foils", label: "Recognition foils", kind: "int", min: 0, help: "Never-shown images for the recognition test." }) : ""}
      </div>
      ${field({ path: "content.comments", label: "Posts have comments (when no factor sets them)", kind: "bool" })}
      <div class="summary">You'll need <b>${nImages}</b> image${nImages === 1 ? "" : "s"}${nv > 1 ? ` (${nv} versions of each critical post)` : ""}, ${ui.content.accounts} avatar${ui.content.accounts === 1 ? "" : "s"}${featureOn("stories") && !hasTable("stories") ? `, ${ui.content.stories} story image(s)` : ""}${featureOn("reels") && !hasTable("reels") ? `, ${ui.content.reels} video(s)` : ""}, and an AOI file for every critical image.</div>
      ${ui.desktop ? folderFiles() : ""}`;
  }

  function sectionFeed() {
    const P = "feed.";
    return `
      <h2>Feed</h2>
      <div class="grid">
        ${field({ path: P + "done_button_after_s", label: "“I'm done” button after (s)", kind: "nullnum", min: 0, placeholder: "never", help: "Blank = never shown." })}
        ${field({ path: P + "time_limit_s", label: "Time limit (s)", kind: "nullnum", min: 1, placeholder: "none", help: "Blank = no limit. With neither, participants scroll until the end of the feed." })}
        ${field({ path: P + "order", label: "Post order", kind: "select", adv: true, options: [["shuffle", "Shuffled per participant"], ["fixed", "Fixed (posts.csv order)"]], help: "Shuffled orders still follow the spacing rules next to it." })}
        ${field({ path: P + "lead_in_fillers", label: "Fillers at the top", kind: "int", min: 0, adv: true, help: "Warm-up posts before the first critical post." })}
        ${field({ path: P + "max_run_same_cell", label: "Max critical posts in a row from one cell", kind: "int", min: 1, adv: true })}
        ${field({ path: P + "min_fillers_between_critical", label: "Fillers between critical posts", kind: "int", min: 0, adv: true })}
        ${featureOn("stories") ? field({ path: P + "story_duration_s", label: "Seconds per story", kind: "float", min: 1, max: 60, adv: true }) : ""}
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
      case "instructions": return `<div class="grid">${f("title", "Title", "text")}${f("button", "Button text", "text")}${f("min_time_s", "Minimum time (s)", "float", { min: 0, adv: true })}</div>${f("text", "Text", "textarea", { rows: 4 })}`;
      case "marker_calibration": return `<div class="grid">${f("duration_s", "Duration (s)", "float", { min: 1, max: 30, adv: true })}</div>`;
      case "tag_ladder": return `<div class="grid">${f("hold_s", "Seconds per way of holding", "float", { min: 5, max: 120 })}${f("flip_every_s", "Reverse the order every (s)", "float", { min: 1, max: 60 })}</div>`;
      case "display_calibration": return `<div class="grid">${f("wait_s", "Offer Skip after (s)", "float", { min: 5, max: 600, adv: true })}${f("port", "Port", "int", { min: 1024, max: 65535, adv: true, help: "The laptop connects to the phone on this port." })}</div>${f("text", "Text", "textarea", { rows: 2 })}`;
      case "settings_test": return `<div class="grid">${f("setting_s", "Seconds per setting", "float", { min: 2, max: 30 })}${f("rounds", "Rounds per hold", "int", { min: 1, max: 4, help: "Each round reverses the order." })}</div>`;
      case "camera_check": return `<div class="grid">${f("min_face_s", "Face in view for (s)", "float", { min: 0.5, max: 30, adv: true })}${f("instructions", "Instructions", "text", { wide: true })}</div>`;
      case "profile_photo": return `${f("text", "Text", "textarea")}${f("allow_skip", "Participants can skip it", "bool")}`;
      case "validation": return `<div class="grid">${f("points", "Dots", "select", { num: true, options: [[5, "5"], [9, "9"], [13, "13"]] })}${f("target_dp", "Dot size (dp)", "int", { min: 12, max: 80, adv: true })}${f("instructions", "Instructions", "text", { wide: true })}</div>
          ${f("live_check", "Check the eye tracking right after the dots", "bool", { help: "With the Neon: if gaze didn't follow the dots (or isn't arriving, or the glasses say they're off), the researcher is asked to re-seat the glasses and redo the dots, before the participant goes on." })}`;
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

  // ------------------------------------------------------------ parts of the session (Procedure)

  /** Whether the study folder has this CSV (desktop app: the folder's file list). */
  function hasTable(kind) {
    const r = ui.files.result, name = getP(kind) || `${kind}.csv`;
    return !!(r && r.tables.some((t) => t.file === name && t.found));
  }

  /** Stories / reels are on: switched on (feed.stories / feed.reels) and there's content for them. */
  function featureOn(kind) {
    if (val(`feed.${kind}`, true) === false) return false;
    if (ui.opened && !ui.desktop) return true;   // a study.yaml opened in the browser: its CSVs can't be seen
    return ui.content[kind] > 0 || hasTable(kind);
  }

  const PARTS = [
    ["pre", "Pre-test survey", "Questions before the feed."],
    ["post", "Post-test survey", "Questions after the feed."],
    ["image_rating", "Image ratings", "Each critical post's image again, with questions about it."],
    ["recognition", "Recognition test", "\"Did you see exactly this image?\" for images shown and not shown."],
  ];

  /** Indexes of the procedure steps that make up a part: questionnaires before / after the feed, or steps of a type. */
  function partSteps(part) {
    const steps = ui.study.procedure || [], feed = steps.findIndex((s) => s.type === "feed");
    return steps.map((s, i) => [s, i]).filter(([s, i]) => part === "pre" ? s.type === "questionnaire" && i < feed
      : part === "post" ? s.type === "questionnaire" && i > feed : s.type === part).map(([, i]) => i);
  }

  function sessionParts() {
    const box = (part, label, hint, on) => `<label class="check"><input type="checkbox" data-action-change="part:${part}" ${on ? "checked" : ""}> <span>${label}</span></label>${help(hint)}`;
    return `<div class="card"><h4>Parts of the session</h4>
      <div class="checks-grid">
        ${PARTS.map(([part, label, hint]) => box(part, label, hint, partSteps(part).length)).join("")}
        ${box("stories", "Stories", "Story circles open full-screen stories. Off: the circles are only decoration.", featureOn("stories"))}
        ${box("reels", "Reels", "The Reels tab plays short videos. Off: the tab does nothing.", featureOn("reels"))}
      </div>
      <p class="hint">Ticking a part adds its step in the right place below; open the step to write its questions.</p></div>`;
  }

  /** Switch a part of the session on or off; false if the researcher cancelled. */
  function setPart(part, on) {
    const S = ui.study;
    if (part === "stories" || part === "reels") {
      setP(`feed.${part}`, on);
      if (on && !hasTable(part) && !ui.content[part]) ui.content[part] = part === "stories" ? 6 : 3;
      if (!on && !hasTable(part)) ui.content[part] = 0;
      return true;
    }
    const label = PARTS.find((p) => p[0] === part)[1];
    if (!on) {
      const at = partSteps(part);
      const written = at.some((i) => (S.procedure[i].items || []).some((it) => it.text));
      if (written && !confirm(`Remove the ${label.toLowerCase()} and its questions? Undo brings them back.`)) return false;
      S.procedure = S.procedure.filter((_, i) => !at.includes(i));
      ui.openStep = null;
      return true;
    }
    const steps = S.procedure, feed = steps.findIndex((s) => s.type === "feed");
    let afterFeed = feed + 1;   // after the feed and the marker calibration that closes it
    while (afterFeed < steps.length && steps[afterFeed].type === "marker_calibration") afterFeed++;
    const firstAfter = (types) => { const i = steps.findIndex((s, j) => j > feed && types.includes(s.type)); return i < 0 ? steps.length : i; };
    const s = newStep(part === "pre" || part === "post" ? "questionnaire" : part);
    let at;
    if (part === "pre") { s.id = uniqueId("pre", steps.map((x) => x.id)); at = feed; }
    else if (part === "post") { s.id = uniqueId("post", steps.map((x) => x.id)); at = afterFeed; }
    else if (part === "image_rating") at = Math.max(afterFeed, firstAfter(["recognition", "end"]));
    else at = Math.max(afterFeed, firstAfter(["end"]));
    if (part === "image_rating" || part === "recognition") {
      // after any post-test survey already there
      const post = partSteps("post");
      if (post.length) at = Math.max(at, post[post.length - 1] + 1);
    }
    steps.splice(at, 0, s);
    if (part === "recognition") C.syncFoils(S, ui.content);
    ui.openStep = at;
    return true;
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
        ${open ? `${help(info[1])}${advanced("Step id", false, `<div class="grid">${field({ path: `procedure.${i}.id`, label: "Step id", kind: "text", help: "Names the step in the data." })}</div>`)}${stepFields(s, i)}` : ""}
      </div>`;
    }).join("");
    const types = C.STEP_TYPES.filter((t) => t !== "end" && !RETIRED_STEPS.includes(t) && (ui.advanced || !ADVANCED_STEPS.includes(t)));
    if (!ui.advanced) ui.hidden.push(...ADVANCED_STEPS.map((t) => ({ label: `${STEP_INFO[t][0]} step`, changed: false })));
    return `
      <h2>Procedure</h2>
      <p class="lead">The screens a participant goes through, in order. Click a step to edit it.</p>
      ${sessionParts()}
      <h3>Steps</h3>
      ${cards}
      <div class="row add-step"><select id="new-step">${types.map((t) => `<option value="${t}">${STEP_INFO[t][0]}</option>`).join("")}</select>${btn("add-step", "+ Add step", "primary")}</div>
      <p class="hint">New steps go before the end screen.</p>`;
  }

  function sectionRecording() {
    const L = "logging.";
    const cam = val("logging.front_camera.enabled", false);
    const camSteps = val("logging.front_camera.steps", ["feed"]);
    return `
      <h2>Recording</h2>
      <p class="lead">Gaze, what is on screen, interactions, answers and session quality are always recorded. Optional extras:</p>
      <div class="card">
        ${field({ path: L + "touches", label: "Touch points", kind: "bool", help: "Every finger down / move / up. Needed for gestures and for spotting a finger covering part of an image. Cheap; keep it on." })}
      </div>
      <div class="card">
        ${field({ path: L + "sensors", label: "Motion sensors", kind: "bool", help: "Accelerometer, gyroscope and rotation: how the phone is held and moved. Useful for cleaning gaze data; small files." })}
        ${val("logging.sensors", false) ? `<div class="grid">${field({ path: L + "sensor_hz", label: "Samples per second", kind: "int", min: 5, max: 200, adv: true })}</div>` : ""}
      </div>
      <div class="card">
        ${field({ path: L + "front_camera.enabled", label: "Front camera video of the face", kind: "bool", help: "For facial-expression analysis. Android shows a camera indicator while recording, which may make people more self-aware; pilot it. Uses battery and warms the phone." })}
        ${cam ? `<div class="grid">
          ${field({ path: L + "front_camera.resolution", label: "Resolution", kind: "select", def: "720p", adv: true, options: [["480p", "480p"], ["720p", "720p (recommended)"], ["1080p", "1080p"]] })}
          ${field({ path: L + "front_camera.fps", label: "Frames per second", kind: "select", def: 30, num: true, adv: true, options: [[15, "15"], [24, "24"], [30, "30"]] })}
          ${field({ path: L + "front_camera.bitrate_mbps", label: "Bitrate (Mbit/s)", kind: "float", min: 0.5, max: 20, def: 3, adv: true })}
          ${field({ path: L + "front_camera.segment_s", label: "New file every (s)", kind: "int", min: 10, max: 600, def: 60, adv: true, help: "A crash loses at most one file." })}
        </div>
        <h4>Steps to record</h4>
        <label class="check"><input type="checkbox" data-action-change="cam-all" ${camSteps === "all" ? "checked" : ""}> <span>All steps</span></label>
        ${camSteps === "all" ? "" : stepChecks("cam-step", camSteps)}` : ""}
      </div>
      ${advanced("Screen recording", val("logging.screen_recording", false), `<div class="card">
        ${field({ path: L + "screen_recording", label: "Screen recording (pilots only)", kind: "bool", help: "Records exactly what was on screen, to check the gaze mapping. Android asks for permission every session and it costs performance. Not built in the app yet; can't be combined with the front camera." })}
        ${val("logging.screen_recording", false) ? `<div class="grid">${field({ path: L + "screen_recording_fps", label: "Frames per second", kind: "int", min: 5, max: 60 })}</div>` : ""}
      </div>`)}
      <h3>Eye tracker</h3>
      <div class="card">
        ${field({ path: "neon.required", label: "Require the Neon glasses to start a session", kind: "bool", help: "Without it, the researcher can go on without eye tracking when the glasses aren't ready." })}
        ${field({ path: "neon.auto_record", label: "Start and stop the Neon recording from the app", kind: "bool", adv: true, help: "Shows an eye tracker check (glasses, battery, streams, checklist) before each session. Keep it on: the settings below need it." })}
      </div>
      ${eyeTrackerAdvanced()}`;
  }

  /** A checkbox per procedure step; `action` gets the step id. */
  function stepChecks(action, chosen) {
    const ids = (ui.study.procedure || []).map((s) => s.id).filter(Boolean);
    return `<div class="checks-grid">${ids.map((id) => `<label class="check"><input type="checkbox" data-action-change="${action}:${esc(id)}" ${Array.isArray(chosen) && chosen.includes(id) ? "checked" : ""}> <span>${esc(id)}</span></label>`).join("")}</div>`;
  }

  /** Phone tracking and the Neon scene camera: settings for researchers who have piloted their setup. */
  function eyeTrackerAdvanced() {
    const exp = getP("neon.scene_exposure");
    const mode = exp ? exp.mode || "manual" : "__null__";
    const tagSteps = val("markers.on_screen.steps", []);
    const html = `
      <div class="card">
        <h4>On-screen tags</h4>
        ${help("AprilTags at the top and bottom of the screen during the chosen steps, so the scene camera can find the phone all the time (marker calibrations show their own). Pilot the size with a Tag size check step.")}
        ${stepChecks("tags-step", tagSteps)}
        ${tagSteps.length ? `<div class="grid">
          <div class="field"><label for="f_tags_layout">Where</label><select id="f_tags_layout" data-action-change="tags-layout" data-key="tags-layout">
            ${[["bars", "In the feed's top bar and tab bar"], ["bands", "In bands above and below the step"]].map(([v, l]) => `<option value="${v}" ${val("markers.on_screen.layout", "bands") === v ? "selected" : ""}>${l}</option>`).join("")}</select>
            ${help("The bars keep the app looking like Instagram; tested with the Neon at 10 mm (tag16h5). Other steps chosen get bands.")}</div>
          ${field({ path: "markers.on_screen.family", label: "Tag family", kind: "select", options: [["tag16h5", "tag16h5 (smallest that reads)"], ["tag25h9", "tag25h9"], ["tag36h11", "tag36h11 (most robust)"]] })}
          ${field({ path: "markers.on_screen.size_mm", label: "Tag size (mm)", kind: "float", min: 4, max: 20 })}
          ${val("markers.on_screen.layout", "bands") === "bars" ? field({ path: "markers.on_screen.side_inset_mm", label: "From the side edges (mm)", kind: "float", min: 0, max: 12, help: "To the tags' black border. 3 mm read as well as 5 mm, on curved edges and one-handed too." }) : ""}
          ${val("markers.on_screen.layout", "bands") === "bars" ? field({ path: "markers.on_screen.edge_gap_mm", label: "From the top and bottom edges (mm)", kind: "float", min: 0, max: 12 }) : ""}
        </div>` : ""}
      </div>
      <div class="card">
        <h4>Screen and scene camera</h4>
        <div class="grid">
          ${field({ path: "display.brightness", label: "Screen brightness (0.05 to 1)", kind: "nullnum", min: 0.05, max: 1, placeholder: "the phone's setting", help: "For the whole session. Blank = the phone's own setting. A Display calibration step chooses it for you." })}
          <div class="field"><label for="f_exposure">Scene camera exposure</label><select id="f_exposure" data-action-change="exposure-mode" data-key="exposure-mode">
            ${[["__null__", "Leave Companion's setting"], ["auto", "Automatic"], ["manual", "Fixed"]].map(([v, l]) => `<option value="${v}" ${mode === v ? "selected" : ""}>${l}</option>`).join("")}</select>
            ${help("Automatic exposure meters the room and can blow out the bright screen. Set at the start of each session, put back at the end.")}</div>
          ${mode === "manual" ? field({ path: "neon.scene_exposure.exposure_us", label: "Exposure time (µs)", kind: "int", min: 1, max: 1000000, placeholder: "e.g. 4000" }) : ""}
          ${mode === "manual" ? field({ path: "neon.scene_exposure.gain", label: "Gain", kind: "int", min: 0, placeholder: "Companion's" }) : ""}
          ${mode === "auto" ? field({ path: "neon.scene_exposure.brightness", label: "Target brightness", kind: "int", placeholder: "Companion's", help: "Lower = darker." }) : ""}
        </div>
      </div>
      <div class="card">
        ${field({ path: "neon.checklist", label: "Checklist before each recording", kind: "lines", rows: 4, wide: true, help: "One item per line; the researcher ticks each before starting. Leave empty for no checklist. Fields for Neon Companion's recording template can be set in the study file." })}
      </div>`;
    if (ui.advanced) return `<h3>Phone tracking</h3>${html}`;
    ui.hidden.push(
      { label: "On-screen tags", changed: tagSteps.length > 0 || changed("markers.on_screen.size_mm") || changed("markers.on_screen.layout") },
      { label: "Screen brightness", changed: changed("display.brightness") },
      { label: "Scene camera exposure", changed: exp != null },
      { label: "Eye tracker checklist", changed: changed("neon.checklist") },
    );
    return "";
  }

  function sectionParticipants() {
    const b = C.blockSize(ui.study);
    const n = Number(val("participants.n_plans")) || 0;
    const pre = val("participants.id_prefix"), dig = Number(val("participants.id_digits")) || 3;
    const id = (k) => pre + String(k).padStart(dig, "0");
    const lo = Math.max(b, Math.floor(n / b) * b), hi = Math.ceil(n / b) * b;
    return `
      <h2>Participants</h2>
      <p class="lead">One plan per participant id, balanced in blocks of <b>${b}</b>: recruit in multiples of ${b}.</p>
      <div class="grid">
        ${field({ path: "participants.n_plans", label: "Number of plans", kind: "int", min: 1, max: 5000, help: "Make more plans than you expect to need; unused ones do no harm." })}
        ${field({ path: "participants.id_prefix", label: "Id prefix", kind: "text", adv: true })}
        ${field({ path: "participants.id_digits", label: "Digits", kind: "int", min: 1, max: 6, adv: true })}
      </div>
      ${b > 1 && n % b ? `<div class="row">${btn(`set-n:${lo}`, `Use ${lo}`)}${hi !== lo ? btn(`set-n:${hi}`, `Use ${hi}`) : ""}</div>` : ""}
      <div class="summary">Ids: <code>${esc(id(1))}</code>, <code>${esc(id(2))}</code> … <code>${esc(id(n))}</code></div>`;
  }

  /** Shown on Basics and Save when the open study already has sessions. */
  function sessionsNote() {
    if (!ui.desktop || !ui.sessions || ui.protect) return "";
    return `<p class="hint"><span class="pill">${ui.sessions} session${ui.sessions === 1 ? "" : "s"} collected</span>
      Changes to the design, content or procedure need a new version; saving tells you.</p>`;
  }

  /** The Download section as it is in the desktop app: save into the study folder. */
  function sectionSave() {
    const files = C.studyFiles(ui.study, ui.content, true);
    if (!files[ui.previewFile]) ui.previewFile = "study.yaml";
    const errors = C.checks(ui.study, ui.content).filter((c) => c.level === "error");
    const s = ui.saved, P = ui.protect;
    return `
      <h2>Save</h2>
      ${P ? `<div class="card step open">
        <p><b>Not saved.</b> This study already has ${P.sessions} session${P.sessions === 1 ? "" : "s"} (version ${esc(P.version)}), and these changes would break ${P.sessions === 1 ? "it" : "them"}:</p>
        <ul class="checks">${P.reasons.map((m) => `<li class="error"><div class="msg"><span class="ic">✕</span><span>${esc(m)}</span></div></li>`).join("")}</ul>
        <p class="hint">Save them as a new version instead: sessions keep the version they ran, so the analysis can tell them apart.
        Give the next participants ids that haven't been used yet; the phone keeps the old version until its sessions are unloaded.</p>
        <div class="row">${btn("save-new-version", `Save as version ${Number(P.version) + 1}`, "primary", ui.busy ? "disabled" : "")}${btn("protect-cancel", "Cancel", "", ui.busy ? "disabled" : "")}</div>
      </div>` : ""}
      ${sessionsNote()}
      ${errors.length ? `<p class="error-box">The design has ${errors.length === 1 ? "1 problem" : `${errors.length} problems`} (see the list on the right). You can still save and fix ${errors.length === 1 ? "it" : "them"} later.</p>` : ""}
      ${ui.folder
        ? `<div class="row">${btn("save", "Save", "primary", ui.busy ? "disabled" : "")}${btn("check-folder", "Check study", "", ui.busy ? "disabled" : "")}${btn("save-new", "Save as a new study…", "link", ui.busy ? "disabled" : "")}
             ${unsaved() ? `<span class="pill">unsaved changes</span>` : ""}</div>`
        : `<p>Not saved yet: choose where (usually <code>studies</code>); a folder named <code>${esc(ui.study.id || "…")}</code> is made there.</p>
           <div class="row">${btn("save-new", "Save to a new folder…", "primary", ui.busy ? "disabled" : "")}</div>`}
      ${ui.busy ? `<p class="hint">${esc(ui.busy)}</p>` : ""}
      ${s ? `<p class="hint">Saved at ${clock(s.at)}: wrote ${s.written.map((f) => `<code>${esc(f)}</code>`).join(", ")}${s.kept.length ? `; kept your existing ${s.kept.map((f) => `<code>${esc(f)}</code>`).join(", ")}` : ""}.</p>` : ""}
      ${ui.hadComments ? `<p class="hint">Saving writes the study file in the app's own layout; notes typed into the file by hand are not kept, but the previous file stays next to it as <code>study.yaml.bak</code>.</p>` : ""}
      <p class="hint">Your CSV files are never overwritten: saving only creates the ones that don't exist yet.</p>
      ${filePreview(files)}`;
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
      <div class="row">${btn("download-zip", `Download ${esc(ui.study.id || "study")}.zip`, "primary")}${ui.advanced ? btn("download-yaml", "Download study.yaml only") : ""}</div>
      <p class="hint">Unzip into <code>studies/</code>, then follow NEXT_STEPS.txt.</p>
      ${filePreview(files)}`;
  }

  /** The files saving writes, one tab each (advanced settings only). */
  function filePreview(files) {
    return advanced("Preview of the files", false, `
      <div class="tabs">${Object.keys(files).map((f) => `<button type="button" class="tab ${f === ui.previewFile ? "on" : ""}" data-action="preview:${esc(f)}">${esc(f)}</button>`).join("")}</div>
      <pre class="preview">${esc(files[ui.previewFile])}</pre>`);
  }

  const RENDER = {
    start: sectionStart, basics: sectionBasics, design: sectionDesign, content: sectionContent, feed: sectionFeed,
    procedure: sectionProcedure, recording: sectionRecording, participants: sectionParticipants, download: sectionDownload,
    preview: sectionPreview,
  };

  /** Design > Preview (desktop): one participant's feed as the phone shows it, from the saved study. */
  function sectionPreview() {
    const P = ui.preview, r = P.result, dis = ui.busy ? "disabled" : "";
    let html = `<h2>Preview</h2>
      <p class="lead">One participant's feed as the phone will show it: their post order, images, labels and comments.</p>`;
    if (!ui.folder) return html + `<p class="hint">Save the study first: the preview is made from the saved study.</p>`;
    if (unsaved()) html += `<p class="hint"><span class="pill">unsaved changes</span> The preview shows the study as saved. ${btn("save", "Save", "link", dis)}</p>`;
    if (P.error) html += `<p class="error-box">${esc(P.error)}</p>`;
    if (!r) return html + `<p class="hint">${esc(ui.busy || "Making the preview…")}</p>`;
    html += `<div class="row"><label class="hint" for="preview-pid">Participant</label>
      <select id="preview-pid" class="narrow">${r.participants.map((p) => `<option ${p === r.participant ? "selected" : ""}>${esc(p)}</option>`).join("")}</select>
      ${btn("preview-refresh", "Refresh", "link", dis)}
      <label class="check"><input type="checkbox" id="preview-conditions" ${P.conditions ? "checked" : ""}> <span>Show each post's condition</span></label></div>
      ${r.group ? `<p class="hint">Group: ${esc(r.group)}</p>` : ""}`;
    const posts = r.posts.map((p) => `
      <article class="pv-post">
        <div class="pv-head">${p.avatar ? `<img class="pv-av" src="${p.avatar}" alt="">` : `<span class="pv-av"></span>`}<b>${esc(p.handle)}</b>${p.verified ? " ✓" : ""}
          ${P.conditions ? `<span class="pv-cond ${p.role}">${esc(p.role === "critical" ? p.cell : "filler")}</span>` : ""}</div>
        <div class="pv-img">${p.image ? `<img src="${p.image}" alt="${esc(p.image_id)}">` : `<div class="pv-missing">${esc(p.image_id)}: image missing</div>`}
          ${p.label && p.label.style === "banner" ? `<div class="pv-banner">ⓘ ${esc(p.label.text)}</div>` : ""}</div>
        ${p.label && p.label.style === "caption" ? `<p class="pv-labelcap">${esc(p.label.text)}</p>` : ""}
        <p class="pv-actions">♡ &nbsp;💬&nbsp; ➤</p>
        ${p.likes != null ? `<p><b>${Number(p.likes).toLocaleString()} likes</b></p>` : ""}
        ${p.caption ? `<p><b>${esc(p.handle)}</b> ${esc(p.caption)}</p>` : ""}
        ${p.n_comments > 2 ? `<p class="pv-muted">View all ${p.n_comments} comments</p>` : ""}
        ${p.comments.map((c) => `<p><b>${esc(c.handle)}</b> ${esc(c.text)}</p>`).join("")}
        ${p.posted_ago ? `<p class="pv-muted pv-small">${esc(p.posted_ago)} ago</p>` : ""}
      </article>`).join("");
    return html + `<div class="pv-phone ${r.theme === "dark" ? "dark" : ""}"><div class="pv-top">${esc(r.platform)}</div>${posts}</div>`;
  }

  async function previewRefresh() {
    const P = ui.preview;
    P.error = null;
    if (!ui.folder) { render(); return; }
    try { P.result = await bridge("preview", "Making the preview…", ui.folder, P.pid); }
    catch (e) { P.error = e.message; P.result = null; }
    render();
  }

  // ------------------------------------------------------------ side panel

  function renderSide() {
    const side = document.getElementById("side");
    if (!ui.study) { side.innerHTML = `<p class="hint">Start a study to see checks here.</p>`; return; }
    const list = C.checks(ui.study, ui.content);
    const icon = { error: "✕", warning: "!", tip: "i" };
    const order = { error: 0, warning: 1, tip: 2 };
    list.sort((a, b) => order[a.level] - order[b.level]);
    // a planned count (critical posts) means nothing once posts.csv exists: its rows decide
    for (const c of list) if (c.fix && c.fix.planning && hasTable("posts")) delete c.fix;
    ui.fixes = list.map((c) => c.fix || null);
    const fixBtn = (c, i) => c.fix ? `<div class="fix">${btn(`fix:${i}`, esc(c.fix.label), "link", ui.busy ? "disabled" : "")}</div>` : "";
    side.innerHTML = `
      ${ui.desktop ? "" : `<h3>${esc(ui.study.title || ui.study.id || "Untitled")}</h3>`}
      <p class="design-line">${esc(C.designSummary(ui.study))}</p>
      ${ui.advanced ? `<dl class="stats"><dt>Cells</dt><dd>${C.cells(ui.study)}</dd><dt>Groups</dt><dd>${C.groups(ui.study)}</dd><dt>Block</dt><dd>${C.blockSize(ui.study)}</dd><dt>Steps</dt><dd>${(ui.study.procedure || []).length}</dd></dl>` : ""}
      <h3>Checks</h3>
      ${list.length ? `<ul class="checks">${list.map((c, i) => `<li class="${c.level}"><button type="button" data-action="goto:${c.section}"><span class="ic">${icon[c.level]}</span><span>${esc(c.msg)}</span></button>${fixBtn(c, i)}</li>`).join("")}</ul>`
        : ui.desktop && folderClean() ? "" : `<p class="ok-box">All good.</p>`}
      ${ui.desktop ? folderChecks(!list.length, list) : ""}`;
    annotateTerms(side);
    const counts = {};
    for (const c of list) if (c.level === "error") counts[c.section] = (counts[c.section] || 0) + 1;
    document.querySelectorAll("#nav button[data-section]").forEach((b) => {
      const n = counts[b.dataset.section];
      b.querySelector(".count").textContent = n ? String(n) : "";
    });
  }

  /** A way to the place that settles one of the compiler's messages (missing files, AOIs). */
  function folderFix(m) {
    if (!ui.desktop || !ui.folder) return "";
    const dis = ui.busy ? "disabled" : "";
    if (/AOI/.test(m)) return `<div class="fix">${btn("aois-edit", "Edit AOIs…", "link", dis)}</div>`;
    if (/not found|is missing/.test(m) && /\.(png|jpe?g|webp|mp4|mov|m4v)\b/i.test(m)) return `<div class="fix">${btn("fix-files", "Add files from a folder…", "link", dis)}</div>`;
    return "";
  }

  /** The saved folder checked, with nothing to report and nothing unsaved. */
  const folderClean = () => !!(ui.folder && ui.compiler && !ui.compiler.errors.length && !ui.compiler.warnings.length && !unsaved() && !ui.desktopError);

  /** The compiler's checks of the saved folder (desktop app only); with ``designOk``, one line for both when all is well. */
  function folderChecks(designOk, design = []) {
    if (designOk && folderClean()) {
      return `<p class="ok-box">All good: the design, images, AOIs and CSV files check out.</p>
        <p class="hint">Checked at ${clock(ui.compiler.at)}. ${btn("check-folder", ui.busy === "Checking…" ? "Checking…" : "Check again", "link", ui.busy ? "disabled" : "")}</p>`;
    }
    const head = `<h3>Study folder</h3>${ui.desktopError ? `<p class="error-box">${esc(ui.desktopError)}</p>` : ""}`;
    if (!ui.folder) return `${head}<p class="hint">Save the study to a folder to check its images, AOIs and CSV files too.</p>`;
    const k = ui.compiler;
    // the design checks above already say these (in the same words), for the study being edited
    const said = (m) => design.some((c) => c.msg.slice(0, 40) === m.slice(0, 40));
    const items = k ? [...k.errors.map((m) => ["error", "✕", m]), ...k.warnings.filter((m) => !said(m)).map((m) => ["warning", "!", m])] : [];
    return `${head}
      ${unsaved() ? `<p class="hint"><span class="pill">unsaved changes</span> These checks are of the saved files. ${btn("save", "Save", "link", ui.busy ? "disabled" : "")}</p>` : ""}
      ${!k ? `<p class="hint">Not checked yet.</p>`
        : items.length ? `<ul class="checks">${items.map(([lv, ic, m]) => `<li class="${lv}"><div class="msg"><span class="ic">${ic}</span><span>${esc(m)}</span></div>${folderFix(m)}</li>`).join("")}</ul>`
        : `<p class="ok-box">Images, AOIs and CSV files all check out.</p>`}
      <p class="hint">${k ? `Checked at ${clock(k.at)}. ` : ""}${btn("check-folder", ui.busy === "Checking…" ? "Checking…" : "Check study", "link", ui.busy ? "disabled" : "")}</p>`;
  }

  // ------------------------------------------------------------ glossary

  /** Research and eye-tracking terms, explained on hover wherever they appear in the text. */
  const GLOSSARY = [
    [/\bwithin[- ]subjects?\b/i, "Within-subjects: every participant sees every level of this factor, on different posts."],
    [/\bbetween[- ]subjects?\b/i, "Between-subjects: each participant sees only one level; participants are split into groups."],
    [/\bcritical posts?\b/i, "Critical posts carry the manipulation: the factors change them, and gaze on them is what's analysed."],
    [/\bfillers?\b/i, "Filler posts are ordinary posts around the critical ones, the same for everyone, so the manipulation isn't obvious."],
    [/\bAOIs?\b/, "AOI (area of interest): a named region of an image, such as the face or waist, that gaze is counted in."],
    [/\bcells?\b/i, "A cell is one combination of the within-subject levels (e.g. retouched + labelled); each participant sees each cell equally often."],
    [/\bbalanced block\b/i, "The balanced block is the smallest number of participants that covers every group and cell once; use a multiple of it so the design stays balanced."],
    [/\bseed\b/i, "The seed is the number the random orders are made from: the same seed always makes the same participant plans."],
    [/\b(participant )?plans?\b/i, "A participant plan is one participant's post order and conditions, made in advance, so the session follows it exactly."],
    [/\bfoils?\b/i, "Foils are images never shown in the feed, used in the recognition test to see whether people say they saw them."],
    [/\blures?\b/i, "Lures are images in the recognition test that weren't in the feed (foils, or the other version of a post)."],
    [/\bmarker calibration\b/i, "A marker calibration shows tags at the screen's corners for a few seconds, so the eye tracker's view can be matched to the phone screen."],
    [/\bvalidation\b/i, "Validation: the participant looks at dots and taps them, which measures how accurate the eye tracking is for them."],
    [/\b(on-screen )?tags\b/i, "Tags (AprilTags) are small black-and-white squares on the phone screen that let the eye tracker's camera find the screen."],
    [/\bfixations?\b/i, "A fixation is a pause of the eyes on one spot (about a tenth of a second or more); it's where looking is counted."],
    [/\bcounterbalanc\w*/i, "Counterbalancing: participants get the conditions in different orders, so order effects even out."],
    [/\bscene camera\b/i, "The scene camera is the eye tracker's forward-facing camera; it sees the phone, and gaze is mapped onto its view."],
    [/\bunblind\w*/i, "Results are blinded (conditions hidden) until you unblind, so looking at data can't steer the analysis."],
  ];
  const GLOSSARY_SKIP = "button, a, input, select, textarea, code, pre, abbr, option, .ic, .logo, .nav, #nav, .tabs";

  /** Marks the first use of each glossary term in `root` with its explanation on hover. */
  function annotateTerms(root) {
    if (!root) return;
    const seen = new Set();
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode: (n) => n.nodeValue.trim() && n.parentElement && !n.parentElement.closest(GLOSSARY_SKIP)
        ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT,
    });
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    for (let node of nodes) {
      for (let g = 0; g < GLOSSARY.length; g++) {
        if (seen.has(g)) continue;
        const m = GLOSSARY[g][0].exec(node.nodeValue);
        if (!m) continue;
        seen.add(g);
        const after = node.splitText(m.index);
        const rest = after.splitText(m[0].length);
        const abbr = document.createElement("abbr");
        abbr.className = "term";
        abbr.title = GLOSSARY[g][1];
        abbr.textContent = after.nodeValue;
        after.replaceWith(abbr);
        node = rest;   // later terms are looked for in what's left of this text
      }
    }
  }

  // ------------------------------------------------------------ render

  const sectionLabel = (k, label) => (k === "download" && ui.desktop ? "Save" : label);
  // the desktop app has no Start step (the Studies page starts studies) and a Preview before Save
  const sections = () => (ui.desktop
    ? SECTIONS.filter(([k]) => k !== "start").flatMap((s) => (s[0] === "download" ? [["preview", "Preview"], s] : [s]))
    : SECTIONS);

  /**
   * The desktop app's header and pages: Studies, then, with a study open, its name and its
   * Design, Phone and Data pages. Returns whether the Design pages (the builder) are showing.
   */
  function renderApp() {
    const tabs = document.getElementById("apptabs");
    tabs.hidden = !ui.desktop;
    if (ui.desktop && !ui.study) ui.tab = "studies";
    const onDesign = !ui.desktop || ui.tab === "design";
    document.querySelector(".layout").hidden = !onDesign;
    const page = document.getElementById("tabpage");
    page.hidden = onDesign;
    if (!ui.desktop) return true;
    document.getElementById("app-title").textContent = "SocialEyes";
    document.getElementById("app-sub").hidden = true;
    const tab = (k, label, off) => `<button type="button" data-action="tab:${k}" class="${ui.tab === k ? "on" : ""}" ${off ? `disabled title="${esc(off)}"` : ""}>${label}</button>`;
    const name = ui.study ? ui.study.title || ui.study.id || "Untitled study" : "";
    tabs.innerHTML = tab("studies", "Studies") + (ui.study
      ? `<span class="crumb" title="${esc(ui.folder || "Not saved yet")}">${esc(name)}${unsaved() ? ` <span class="dot" title="Unsaved changes"></span>` : ""}</span>`
        + APP_TABS.map(([k, label]) => tab(k, label, k !== "design" && !ui.folder ? "Save the study first" : "")).join("")
      : "");
    if (ui.tab === "phone") page.innerHTML = renderPhone();
    else if (ui.tab === "data") page.innerHTML = renderData();
    else if (ui.tab === "studies") page.innerHTML = renderStudies();
    return onDesign;
  }

  // ------------------------------------------------------------ Phone tab (desktop app)

  const CHECK_CLASS = { block: ["error", "✕"], warn: ["warning", "!"], info: ["info", "→"], ok: ["ok", "✓"] };

  function renderPhone() {
    const P = ui.phone, r = P.result;
    const busy = !!ui.busy;
    const blockedNow = r && r.checks.some((c) => c.level === "block");
    const devices = P.devices.length > 1
      ? `<div class="row"><label for="phone-serial" class="hint">Phone</label><select id="phone-serial">${P.devices.map((d) =>
          `<option value="${esc(d.serial)}" ${d.serial === P.serial ? "selected" : ""}>${esc(d.model || d.serial)} (${esc(d.serial)}${d.state !== "device" ? `, ${esc(d.state)}` : ""})</option>`).join("")}</select></div>` : "";
    let body = "";
    if (P.error && !(P.setup && !P.setup.device)) body += `<p class="error-box">${esc(P.error)}</p>`;   // no phone: the guide says
    if (r && r.phone) {
      const p = r.phone;
      body += `<div class="phone-head"><h3>${esc(p.model || p.serial)}</h3><span class="hint">Android ${esc(p.android)} · ${esc(p.serial)}</span></div>
        <ul class="checks">${r.checks.map((c) => `<li class="${CHECK_CLASS[c.level][0]}"><div class="msg"><span class="ic">${CHECK_CLASS[c.level][1]}</span><span>${esc(c.text)}</span></div></li>`).join("")}</ul>`;
    }
    if (r && r.steps && r.steps.length) {
      body += `<ol class="steps">${r.steps.map((s) => `<li>${esc(s)}</li>`).join("")}</ol>`;
    }
    if (r && r.loaded) body += `<p class="ok-box">Loaded ${esc(r.study_id)} onto the phone.</p>`;
    const canLoad = r && r.phone && !blockedNow && !busy;
    const confirm = r && r.needs_confirmation;   // only warnings stand in the way
    return `
      <h2>Phone</h2>
      <p class="lead">Copies the study onto the phone, installing the SocialEyes app if it's missing.</p>
      ${phoneSetup()}
      ${unsaved() ? `<p class="hint"><span class="pill">unsaved changes</span> The phone gets the study as saved. ${btn("save", "Save it first", "link", busy ? "disabled" : "")}</p>` : ""}
      ${devices}
      <div class="row">${btn("phone-load", confirm ? "Load anyway" : "Load onto phone", "primary", canLoad ? "" : "disabled")}
        ${btn("phone-check", ui.busy === "Checking the phone…" ? "Checking…" : "Check again", "", busy ? "disabled" : "")}</div>
      ${r && r.update_available ? `<label class="check"><input type="checkbox" id="phone-update" ${P.updateApp ? "checked" : ""}> <span>Also update the SocialEyes app on the phone (keeps its data)</span></label>` : ""}
      ${confirm && !r.loaded ? `<p class="hint">Only warnings remain: you can load now and sort them out before the session.</p>` : ""}
      ${busy && P.progress ? `<p class="hint">${esc(P.progress)}</p>` : ""}
      ${body}`;
  }

  const SETUP_ICON = { done: ["ok", "✓"], todo: ["warning", "!"], optional: ["info", "○"], waiting: ["waiting", "·"] };

  /** The phone setup guide: shown open until the phone is set up, then folded to one line. */
  function phoneSetup() {
    const P = ui.phone, g = P.setup, busy = !!ui.busy;
    if (!g) return "";
    const done = !g.next && !g.error && g.device;
    if (done && !P.setupOpen) {
      return `<p class="ok-box">This phone is set up. ${btn("setup-toggle", "Show the setup steps", "link")}</p>`;
    }
    const step = (s) => {
      const [cls, ic] = SETUP_ICON[s.status];
      const open = s.id === g.next || s.status === "optional" || (s.status === "todo" && P.setupOpen);
      return `<li class="${s.id === g.next ? "next" : cls}">
        <div class="msg"><span class="ic">${ic}</span><span><b>${esc(s.title)}</b>${s.detail ? ` <span class="hint">${esc(s.detail)}</span>` : ""}</span></div>
        ${open ? `<div class="how">${s.how.map((h) => `<p>${esc(h)}</p>`).join("")}
          ${s.action ? `<div class="row">${btn(`setup-do:${s.action}`, esc(s.action_label), s.id === g.next ? "primary" : "", busy ? "disabled" : "")}</div>` : ""}</div>` : ""}
      </li>`;
    };
    return `<div class="card setup">
      <div class="row"><h3>Phone setup</h3><span class="grow"></span>${done ? btn("setup-toggle", "Hide", "link") : ""}</div>
      ${g.device ? `<p class="hint">${esc(g.device.model || g.device.serial)}${g.device.android ? ` · Android ${esc(g.device.android)}` : ""}</p>` : ""}
      ${g.error ? `<p class="error-box">${esc(g.error)}</p>` : ""}
      ${P.setupError ? `<p class="error-box">${esc(P.setupError)}</p>` : ""}
      ${P.setupNote ? `<p class="ok-box">${esc(P.setupNote)}</p>` : ""}
      <ol class="checks setup-steps">${g.steps.map(step).join("")}</ol>
      ${busy && P.progress ? `<p class="hint">${esc(P.progress)}</p>` : ""}
    </div>`;
  }

  async function setupDo(action) {
    const P = ui.phone;
    P.setupError = null;
    P.setupNote = null;
    try {
      const r = await bridge("phone_setup_do", "Working on the phone…", action, P.devices.length > 1 ? P.serial : null);
      P.setupNote = r.done;
      P.setup = r.guide;
    } catch (e) { P.setupError = e.message; }
    if (action === "install") await phoneCheck();
    else render();
  }

  async function phoneCheck() {
    const P = ui.phone;
    P.error = null;
    try {
      P.devices = (await bridge("phone_devices", null)) || [];
      if (P.devices.length && !P.devices.some((d) => d.serial === P.serial)) P.serial = P.devices[0].serial;
      P.setup = await bridge("phone_setup", "Reading the phone…", P.devices.length > 1 ? P.serial : null);
      const r = await bridge("phone_check", "Checking the phone…", ui.folder, P.devices.length > 1 ? P.serial : null);
      if (r.error) { P.error = r.error; P.result = null; } else P.result = r;
    } catch (e) { P.error = e.message; }
    render();
  }

  async function phoneLoad() {
    const P = ui.phone, r0 = P.result;
    P.error = null;
    P.progress = "Starting…";
    try {
      const r = await bridge("phone_load", "Loading…", ui.folder, P.updateApp && r0 && r0.update_available,
        !!(r0 && r0.needs_confirmation), P.devices.length > 1 ? P.serial : null);
      if (r.error) P.error = r.error;
      // without a phone reading (e.g. unplugged), keep the last check on screen with what was done
      P.result = r.phone ? r : r0 && r0.phone ? { ...r0, steps: r.steps, loaded: false } : null;
      if (r.loaded) {
        P.updateApp = false;
        // the checks were made before loading: "Loads study …" has happened now
        P.result.checks = P.result.checks.map((c) => c.level === "info" && /^Loads study /.test(c.text)
          ? { level: "ok", text: c.text.replace(/^Loads study /, "Study ").replace(/\.$/, " is on the phone.") }
          : c.level === "info" && /^Installs|^Updates/.test(c.text) ? { level: "ok", text: c.text } : c);
      }
    } catch (e) { P.error = e.message; }
    P.progress = null;
    render();
  }

  window.socialeyesProgress = (text) => {
    ui.phone.progress = text;
    if (ui.tab === "phone" || ui.tab === "data" || (ui.tab === "design" && ui.section === "content")) render();
  };

  // ------------------------------------------------------------ Studies tab (desktop app)

  const STATUS = { designing: "warning", ready: "ok", "collecting data": "info" };

  function renderStudies() {
    const S = ui.studies, L = S.list, dis = ui.busy ? "disabled" : "";
    let html = `<h2>Studies</h2>`;
    if (ui.desktopError) html += `<p class="error-box">${esc(ui.desktopError)}</p>`;
    if (S.error) html += `<p class="error-box">${esc(S.error)}</p>`;
    if (!L) return html + `<p class="hint">${esc(ui.busy || "Loading…")}</p>`;
    html += L.studies.length ? `<div class="table-wrap"><table class="register studies"><thead><tr><th>Study</th><th>Status</th><th>Sessions</th><th></th></tr></thead><tbody>
      ${L.studies.map((s, i) => `<tr>
        <td><b>${esc(s.title || s.id)}</b><br><span class="hint">${esc(s.id)} · version ${esc(s.version)}</span></td>
        <td><span class="status ${STATUS[s.status]}">${esc(s.status)}${s.status === "designing" ? ` · ${s.n_errors} problem${s.n_errors === 1 ? "" : "s"}` : ""}</span></td>
        <td>${s.n_sessions || "–"}${s.last_session ? `<br><span class="hint">last ${esc(s.last_session.slice(0, 10))}</span>` : ""}</td>
        <td class="end">${btn(`study-open:${i}`, "Open", "", dis)}</td>
      </tr>`).join("")}</tbody></table></div>`
      : `<p class="hint">No studies yet. The quickest start: copy the example below (a complete 2 x 2 x 2 study with placeholder images) and open the guide <i>Your first study</i>. Or start a new study from scratch.</p>`;
    html += guidesLine();
    const d = !ui.study && readDraft(STORE);
    if (d && d.study && !d.folder) {
      html += `<p class="hint">A new study wasn't saved last time: <b>${esc(d.study.title || d.study.id || "Untitled study")}</b>${d.at ? ` (${esc(new Date(d.at).toLocaleString())})` : ""}. ${btn("resume", "Continue it", "link", dis)}</p>`;
    }
    html += `
      <div class="row new-study">${btn("studies-new-blank", "New study", "primary", dis)}
        <span class="hint">or copy the example as</span>
        <input type="text" id="new-study-id" placeholder="study id, e.g. body_image_1" title="Letters, digits, _ and - (no spaces): it names the study's folder and data" value="${esc(S.newId)}">${btn("studies-copy", "Copy", "", dis)}
        ${btn("open-folder", "Open a folder…", "link", dis)}</div>
      <p class="hint">${btn("open-path:" + L.root, esc(L.root), "link")} ${btn("studies-refresh", "Refresh", "link", dis)}</p>`;
    return html;
  }

  async function studiesRefresh() {
    const S = ui.studies;
    S.error = null;
    try { S.list = await bridge("studies_list", "Checking the studies…"); }
    catch (e) { S.error = e.message; }
    if (!S.guides) {
      try { S.guides = await bridge("guides", null); } catch (e) { S.guides = []; }
    }
    render();
  }

  /** Studies: links to the researcher's guides (they open in the browser). */
  function guidesLine() {
    const g = ui.studies.guides || [];
    return g.length ? `<p class="hint">Guides: ${g.map((x) => btn("open-path:" + x.path, esc(x.title), "link")).join(" · ")}</p>` : "";
  }

  /** Open a study folder in the Design tab (asks first if the current study has unsaved changes). */
  async function openStudyAt(folder) {
    if (wouldLose() && !confirm("The open study has changes that aren't saved. Open another study anyway?")) return false;
    try {
      const r = await bridge("open_folder", "Opening…", folder);
      const study = parseStudy(r.study.yaml);
      load(study, C.contentFor(study), "study.yaml", r.study.folder);
      ui.hadComments = /^\s*#/m.test(r.study.yaml);
      // changes left unsaved last time (the app closed first), if study.yaml hasn't changed since
      const d = readDraft(DRAFT_PREFIX + r.study.folder);
      if (d && d.study && d.savedYaml === ui.savedYaml && C.toYaml(d.study) !== ui.savedYaml
          && confirm(`This study has changes from ${new Date(d.at).toLocaleString()} that were never saved. Bring them back?\n\n`
            + "OK: bring them back, to check and save. Cancel: open the study as saved (the changes are dropped).")) {
        ui.study = d.study;
        ui.content = d.content;
      }
      ui.compiler = { ...r.check, at: new Date() };
      ui.sessions = r.sessions || 0;
      ui.tab = "design";
      return true;
    } catch (e) {
      ui.desktopError = `Couldn't open the study: ${e.message}`;
      ui.section = "start";
      return true;
    }
  }

  async function studiesAct(name, args) {
    const S = ui.studies, L = S.list;
    if (name === "study-open") {
      if (await openStudyAt(L.studies[Number(args[0])].folder)) ui.tab = "design";
      render();
    } else if (name === "study-goto") {   // open it on one of its pages
      if (!(await openStudyAt(L.studies[Number(args[0])].folder))) return;
      if (args[1] === "content") { ui.tab = "design"; ui.section = "content"; render(); filesRefresh(); return; }
      act(`tab:${args[1]}`);
    } else if (name === "studies-new-blank") {
      if (wouldLose() && !confirm("The open study has changes that aren't saved. Start a new one anyway?")) return;
      ui.tab = "design";
      act("new-blank");
    } else if (name === "studies-copy") {
      S.newId = (document.getElementById("new-study-id").value || "").trim();
      try {
        const folder = await bridge("studies_copy_example", "Copying…", S.newId);
        S.newId = "";
        if (await openStudyAt(folder)) ui.tab = "design";
        S.list = null;
      } catch (e) { S.error = e.message; }
      render();
    }
  }

  // ------------------------------------------------------------ Content tab (desktop app)

  const KINDS = [["image", "Images"], ["aoi", "AOI files (critical posts)"], ["avatar", "Avatars"], ["story", "Story images"], ["video", "Reel videos"]];

  /** Design > Content in the desktop app: which of the files the CSVs name are in the study folder. */
  function folderFiles() {
    const F = ui.files, r = F.result, dis = ui.busy ? "disabled" : "";
    let html = `<h3>Files in the study folder</h3>`;
    if (!ui.folder) return html + `<p class="hint">Save the study, then add its images, avatars and AOI files to its folder.</p>`;
    if (F.error) html += `<p class="error-box">${esc(F.error)}</p>`;
    if (!r) return html + `<p class="hint">${esc(ui.busy || "Looking at the files…")}</p>`;
    const missingTables = r.tables.filter((t) => !t.found);
    if (missingTables.length) html += `<p class="error-box">Missing ${missingTables.map((t) => `<code>${esc(t.file)}</code>`).join(", ")}: save the study to create ${missingTables.length === 1 ? "it" : "them"}.</p>`;
    html += `<p><b>${r.n_found} of ${r.n_needed}</b> files ready ${btn("open-path:" + ui.folder, "Open folder", "link")}${btn("files-refresh", "Refresh", "link", dis)}</p>`;
    const rows = [];
    for (const [kind, label] of KINDS) {
      const all = r.items.filter((i) => i.kind === kind);
      if (!all.length) continue;
      const missing = all.filter((i) => !i.found);
      rows.push(`<li class="${missing.length ? "error" : "ok"}"><div class="msg"><span class="ic">${missing.length ? "✕" : "✓"}</span><span>${label}: ${all.length - missing.length} of ${all.length}${missing.length
        ? `. Missing ${missing.slice(0, 6).map((i) => `<code>${esc(i.file)}</code>`).join(", ")}${missing.length > 6 ? ` and ${missing.length - 6} more` : ""}` : ""}</span></div></li>`);
    }
    return html + `<ul class="checks">${rows.join("")}</ul>` + sourcesLine(r) + addImages() + imageCheck() + autoAois();
  }

  /** Design > Content: where each file came from (sources.csv), for the ethics record. */
  function sourcesLine(r) {
    const s = r.sources;
    if (!s) return "";
    if (s.error) return `<p class="hint">Couldn't update sources.csv: ${esc(s.error)} (close it in Excel and refresh).</p>`;
    if (!s.exists) return `<p class="hint">Keep a record of where each of the ${s.files} files came from (source, licence, credit, consent), for the ethics board:
      ${btn("sources-make", "Make sources.csv", "link", ui.busy ? "disabled" : "")}</p>`;
    const left = s.files - s.complete;
    return `<p class="hint">Sources: <b>${s.complete} of ${s.files}</b> files have a source and licence in ${btn("open-path:" + s.path, "sources.csv", "link")}${left ? ` (fill in the other ${left}: source, licence, credit, consent)` : ""}.</p>`;
  }

  /** Design > Content: images and videos from a folder, matched to the study's files by name. */
  function addImages() {
    const I = ui.images, m = I.match, dis = ui.busy ? "disabled" : "";
    let html = `<h3>Add images and videos</h3>
      <p class="hint">Choose a folder: files are matched to the study's files by name (case, spaces, dashes and the file type don't matter) and copied in under the names the CSV files use.</p>
      <div class="row">${btn("images-pick", "Add from a folder…", "", dis)}</div>`;
    if (I.error) html += `<p class="error-box">${esc(I.error)}</p>`;
    if (m) {
      const name = (p) => p.split(/[\\/]/).pop();
      const fresh = m.matched.filter((x) => !x.exists), existing = m.matched.filter((x) => x.exists);
      html += `<p>${m.matched.length} file${m.matched.length === 1 ? "" : "s"} match${m.matched.length === 1 ? "es" : ""}: ${fresh.length} new${existing.length ? `, ${existing.length} already in the study` : ""}.</p>`;
      if (m.unmatched.length) {
        const opts = [["", "skip"], ...m.missing.map((s) => [s.slot, `${s.slot} (${s.what})`])];
        html += `<p class="hint">These matched nothing; choose a file for each, or skip:</p><div class="table-wrap"><table class="register"><tbody>
          ${m.unmatched.map((src, i) => `<tr><td>${esc(name(src))}</td><td><select data-action-change="images-assign:${i}">
            ${opts.map(([v, l]) => `<option value="${esc(v)}" ${I.assign[src] === v ? "selected" : ""}>${esc(l)}</option>`).join("")}</select></td></tr>`).join("")}
          </tbody></table></div>`;
      }
      const n = fresh.length + Object.values(I.assign).filter(Boolean).length + (I.replace ? existing.length : 0);
      html += `<div class="row">${btn("images-copy", `Copy ${n} file${n === 1 ? "" : "s"} into the study`, "primary", dis || (n ? "" : "disabled"))}
        ${existing.length ? `<label class="check"><input type="checkbox" id="images-replace" ${I.replace ? "checked" : ""}> <span>Also replace the ${existing.length} already in the study</span></label>` : ""}</div>`;
    }
    if (I.copied) {
      const c = I.copied;
      html += `<p class="hint">Copied ${c.copied.length}${c.converted.length ? `, converted ${c.converted.length} to the file type the study uses` : ""}${c.kept.length ? `, kept ${c.kept.length} already there` : ""}.${c.errors.length ? ` Couldn't copy: ${esc(c.errors.join("; "))}.` : ""}</p>`;
    }
    return html;
  }

  /** Design > Content: each image's size and shape for the feed, duplicates, versions that differ. */
  function imageCheck() {
    const I = ui.images, r = I.report, dis = ui.busy ? "disabled" : "";
    let html = `<h3>Image check</h3><div class="row">${btn("images-report", r ? "Check the images again" : "Check the images", "", dis)}</div>`;
    if (!r) return html;
    const flagged = r.images.filter((x) => x.flags.length);
    if (!flagged.length && !r.notes.length) return html + `<p class="hint">All ${r.images.length} images look right for the feed.</p>`;
    // the same warning for many images (e.g. all 540 px wide) is one line, not thirty
    const groups = new Map();
    for (const x of flagged) for (const f of x.flags) groups.set(f, (groups.get(f) || []).concat(x));
    const list = (xs) => xs.length > 3 ? `${xs.length} images (${xs.slice(0, 3).map((x) => `<code>${esc(x.file)}</code>`).join(", ")}, …)`
      : xs.map((x) => `<code>${esc(x.file)}</code> (${esc(x.what)})`).join(", ");
    html += `<ul class="checks">${[...groups].map(([f, xs]) => `<li class="warning"><div class="msg"><span class="ic">!</span><span>${list(xs)}: ${esc(f)}</span></div></li>`).join("")}
      ${r.notes.map((n) => `<li class="warning"><div class="msg"><span class="ic">!</span><span>${esc(n)}</span></div></li>`).join("")}</ul>`;
    if (r.large.length) html += `<div class="row">${btn("images-resize", `Shrink the ${r.large.length} large image${r.large.length === 1 ? "" : "s"}`, "", dis)}<span class="hint">to 2160 px on the longest side; the originals are kept in <code>originals/</code></span></div>`;
    if (I.resized) html += `<p class="hint">Shrunk ${I.resized.resized.length}; the originals are in ${btn("open-path:" + I.resized.originals, "the originals folder", "link")}.</p>`;
    return html;
  }

  async function imagesPick() {
    const I = ui.images;
    I.error = null;
    try {
      const src = await bridge("pick_folder", null, null);
      if (!src) return;
      I.match = await bridge("images_match", "Matching the files…", ui.folder, src);
      I.assign = {};
      I.copied = null;
    } catch (e) { I.error = e.message; }
    render();
  }

  async function imagesCopy() {
    const I = ui.images, m = I.match;
    if (!m) return;
    const pairs = m.matched.filter((x) => I.replace || !x.exists).map((x) => ({ source: x.source, slot: x.slot }))
      .concat(Object.entries(I.assign).filter(([, slot]) => slot).map(([source, slot]) => ({ source, slot })));
    I.error = null;
    try {
      I.copied = await bridge("images_copy", "Copying…", ui.folder, pairs, I.replace);
      I.match = null;
      I.report = null;
    } catch (e) { I.error = e.message; }
    await filesRefresh();
  }

  async function imagesReport() {
    const I = ui.images;
    I.error = null;
    try { I.report = await bridge("images_report", "Checking the images…", ui.folder); I.resized = null; }
    catch (e) { I.error = e.message; }
    render();
  }

  async function imagesResize() {
    const I = ui.images;
    if (!confirm("Shrink the large images to 2160 px on their longest side? The originals are kept in the originals folder.")) return;
    try {
      I.resized = await bridge("images_resize", "Shrinking…", ui.folder);
      I.report = await bridge("images_report", "Checking the images…", ui.folder);
    } catch (e) { I.error = e.message; }
    render();
  }

  /** Features that work in tests but aren't yet shown to give results to rely on: the same list as
   *  python/src/socialeyes/experimental.py (a test checks), shown as a badge where they appear. */
  const EXPERIMENTAL = {
    face_analysis: "Looking away and distance were checked on one recording of known actions. Expressions are MediaPipe's estimates, not coded facial action units, and haven't been checked against human coding.",
    auto_aois: "The outlines come from segmentation models and haven't been checked on real stimuli: look at every AOI before collecting data.",
    gaze: "Tested on one real session and on simulated fixations.",
  };
  const expBadge = (key) => `<span class="exp" title="${esc(EXPERIMENTAL[key])}">Experimental</span>`;

  /** Design > Content: draw face and body AOIs on the critical posts' images (socialeyes aois). */
  function autoAois() {
    const A = ui.aois, r = A.result, dis = ui.busy ? "disabled" : "";
    let html = `<h3>AOIs (areas of interest) ${expBadge("auto_aois")}</h3>
      <p class="hint">Draw and name the areas to measure gaze on, image by image: outline a thing with a click, or draw polygons and boxes.</p>
      <div class="row">${btn("aois-edit", "Edit AOIs…", "", dis)}</div>
      <p class="hint">Or draw <i>face</i>, <i>hair</i>, <i>upper_body</i>, <i>waist</i>, <i>legs</i> and <i>body</i> on every critical post's image
      automatically, then check and correct them with Edit AOIs.</p>
      <div class="row">${btn("aois-draw", ui.busy === "Drawing AOIs…" ? "Drawing…" : "Draw AOIs automatically", "", dis)}
        <label class="check"><input type="checkbox" id="aois-overwrite" ${A.overwrite ? "checked" : ""}> <span>Replace existing AOI files</span></label></div>
      ${ui.busy === "Drawing AOIs…" && ui.phone.progress ? `<p class="hint">${esc(ui.phone.progress)}</p>` : ""}`;
    if (A.error) html += `<p class="error-box">${esc(A.error)}</p>`;
    if (!r) return html;
    const parts = [`${r.written.length} AOI file${r.written.length === 1 ? "" : "s"} written`];
    if (r.kept) parts.push(`${r.kept} existing kept`);
    if (r.empty.length) parts.push(`no person found in ${r.empty.length} image${r.empty.length === 1 ? "" : "s"}`);
    html += `<p>${parts.join(", ")}. ${r.review ? btn("open-path:" + r.review, "Open the review page", "link") : ""}</p>`;
    if (r.check.length) {
      html += `<ul class="checks">${r.check.slice(0, 8).map((c) => `<li class="warning"><div class="msg"><span class="ic">!</span><span><code>${esc(c.image)}</code>: ${esc(c.note)}</span></div></li>`).join("")}</ul>
        ${r.check.length > 8 ? `<p class="hint">and ${r.check.length - 8} more on the review page.</p>` : ""}`;
    }
    return html;
  }

  async function aoisDraw() {
    const A = ui.aois;
    A.error = null;
    ui.phone.progress = "Loading the models…";
    try { A.result = await bridge("aois_draw", "Drawing AOIs…", ui.folder, A.overwrite); }
    catch (e) { A.error = e.message; }
    ui.phone.progress = null;
    await filesRefresh();
  }

  async function filesRefresh() {
    const F = ui.files;
    F.error = null;
    if (!ui.folder) { F.result = null; render(); return; }
    try { F.result = await bridge("content", "Looking at the study's files…", ui.folder); }
    catch (e) { F.error = e.message; F.result = null; }
    render();
  }

  // ------------------------------------------------------------ Data tab (desktop app)

  function renderData() {
    const D = ui.data, st = D.status, busy = !!ui.busy;
    const dis = busy ? "disabled" : "";
    let html = `<h2>Data</h2>`;
    if (D.error) html += `<p class="error-box">${esc(D.error)}</p>`;
    if (!st) return html + `<p class="hint">${esc(ui.busy || "Loading…")}</p>`;
    const ph = st.phone || {}, all = st.register || [], x = D.export;
    const rows = all.filter((r) => r.session_uid);
    const nWithdrawn = new Set(all.filter((r) => r.status === "withdrawn").map((r) => r.participant_id)).size;
    const copiedOnPhone = rows.filter((r) => r.on_phone === "yes" && r.status !== "withdrawn").length;
    html += `
      <p class="lead">${rows.length} session${rows.length === 1 ? "" : "s"} on this computer${ph.error ? "" : ` · ${ph.sessions} on ${esc(ph.name)}${copiedOnPhone ? ` (${copiedOnPhone} copied)` : ""}`}${nWithdrawn ? ` · ${nWithdrawn} withdrawn` : ""}</p>
      ${storageLine(st)}${retentionLine(st)}
      <div class="row">${btn("data-unload", "Copy from the phone", "primary", busy || ph.error || !ph.sessions ? "disabled" : "")}
        ${!st.clear_after_unload && copiedOnPhone && !ph.error ? btn("data-clear-phone", `Clear ${copiedOnPhone} copied from the phone`, "", dis) : ""}
        ${btn("data-export", "Make tables", "", busy || !rows.length ? "disabled" : "")}
        ${btn("data-open:data", "Open data folder", "link", dis)}${btn("data-refresh", "Refresh", "link", dis)}</div>
      ${ph.error ? `<p class="hint">${esc(ph.error)}</p>` : ""}
      ${busy && ui.phone.progress ? `<p class="hint">${esc(ui.phone.progress)}</p>` : ""}
      ${rows.length ? `<label class="check"><input type="checkbox" id="data-unblind" ${D.unblind ? "checked" : ""}> <span>Unblind the tables and the exploration page (real condition names)</span></label>` : ""}
      ${x && x.exploration ? `<p>${btn("open-path:" + x.exploration, x.unblinded ? "Open the exploration page (unblinded)" : "Open the exploration page (blinded)", "link")}</p>` : ""}
      ${x && x.out_dir ? `<p class="hint">Tables (by session, by item, by condition, by comment, and a codebook${x.unblinded ? "" : "; blinded until you unblind"}) for ${x.sessions} session${x.sessions === 1 ? "" : "s"} in ${btn("data-open-export", esc(x.out_dir), "link")}${x.skipped.length
        ? `. Skipped ${x.skipped.length}: ${x.skipped.map((s) => esc(`${s.folder.split(/[\\/]/).slice(-2).join("/")} (${s.why})`)).join("; ")}` : ""}</p>` : ""}`;
    const L = D.last;
    if (L && L.notes && L.notes.length) html += `<p class="hint">${esc(L.participant_id)} ${esc(L.action)}: ${L.notes.map(esc).join("; ")}</p>`;
    if (L && L.deleted && typeof L.files === "number") html += `<p class="hint">Deleted ${L.files} file(s) of ${L.deleted.length} session(s).</p>`;
    const u = D.unload;
    if (u && u.error) html += `<p class="error-box">${esc(u.error)}</p>`;
    if (u && u.sessions && u.sessions.length) {
      html += `<ul class="checks">${u.sessions.map((s) => {
        const [cls, ic, msg] = s.error ? ["error", "✕", `not unloaded: ${s.error}`]
          : s.deleted ? [s.warnings.length ? "warning" : "ok", s.warnings.length ? "!" : "✓",
            `copied and checked${s.second_copy ? ", second copy checked" : ""}, deleted from the phone${s.warnings.length ? `. ${s.warnings.length} warning(s): ${s.warnings.join("; ")}` : ""}`]
          : s.copied ? ["ok", "✓", `copied and checked${s.second_copy ? ", second copy checked" : ""}${s.neon ? `; Neon recording ${s.neon}` : ""}; ${s.kept_reason}`]
          : ["info", "→", s.kept_reason || "left on the phone"];
        return `<li class="${cls}"><div class="msg"><span class="ic">${ic}</span><span><b>${esc(s.participant_id)}</b> ${esc(s.session_uid)}: ${esc(msg)}</span></div></li>`;
      }).join("")}</ul>`;
    }
    const firstRow = new Set();
    html += all.length ? `<div class="table-wrap"><table class="register"><thead><tr><th>Participant</th><th>Started</th><th>Completed</th><th>Warnings</th><th>Notes</th><th></th></tr></thead><tbody>
      ${all.map((r) => {
        const first = !firstRow.has(r.participant_id);
        firstRow.add(r.participant_id);
        const w = r.status === "withdrawn", gone = r.status === "deleted";
        const actions = !first ? "" : w ? `${btn(`data-restore:${r.participant_id}`, "Restore", "link", dis)}${btn(`data-delete-withdrawn:${r.participant_id}`, "Delete permanently…", "link danger", dis)}`
          : gone ? "" : btn(`data-withdraw:${r.participant_id}`, "Withdraw…", "link", dis);
        return `<tr class="${w || gone ? "withdrawn" : ""}"><td>${esc(r.participant_id)}${w ? ` <span class="pill">withdrawn ${esc((r.status_at || "").slice(0, 10))}</span>` : gone ? ` <span class="pill">deleted</span>` : ""}${r.duplicate_id && !w ? ` <span class="pill">ID used twice</span>` : ""}${r.on_phone === "yes" && !w ? ` <span class="pill">on phone</span>` : ""}</td>
        <td>${esc((r.started || "").replace("T", " ").slice(0, 16))}</td><td>${!r.session_uid ? "" : r.completed === "yes" ? "yes" : `<b>${esc(r.completed || "?")}</b> ${esc(r.end_reason || "")}`}</td>
        <td title="${esc(r.warnings)}">${esc(r.n_warnings || (r.session_uid ? "0" : ""))}</td><td>${esc(r.notes)}</td><td class="end">${actions}</td></tr>`;
      }).join("")}
      </tbody></table></div><p class="hint">Hover a warning count to read the warnings. Notes added to <code>sessions.csv</code> in Excel are kept.
      Withdrawing moves a participant's data aside and out of every table (Restore undoes it); <i>Delete permanently</i> then removes it, from the phone too.</p>`
      : `<p class="hint">No sessions yet.</p>`;
    html += analysisSection(st);
    html += `
      <details class="folders"><summary>Folders</summary>
        <p>Sessions: <span class="folder">${esc(st.data_dir)}</span> ${btn("data-pick:data", "Change…", "link", dis)}</p>
        <p>Second copy: ${st.second_copy_dir ? `<span class="folder">${esc(st.second_copy_dir)}</span> ${btn("data-pick:second", "Change…", "link", dis)}${btn("data-clear:second", "Stop", "link danger", dis)}`
          : `none ${btn("data-pick:second", "Choose a folder…", "link", dis)}`}</p>
        <p class="hint">A second copy of every session, e.g. on a university drive. Set for this computer only.</p>
      </details>`;
    return html;
  }

  /** Data: a warning when a data folder is inside a cloud-sync folder (its files upload themselves). */
  function storageLine(st) {
    const items = (st.storage || []).map((s) => s.cloud
      ? `<span class="status warning" title="${esc(s.path)}">${esc(s.folder)}: inside ${esc(s.cloud)}, so it uploads itself</span>`
      : "");
    return items.some(Boolean) ? `<p class="hint">${items.join(" ")}</p>` : "";
  }

  /** Data: what the study's retention rules (data: in study.yaml) say is due. */
  function retentionLine(st) {
    const r = st.retention, dis = ui.busy ? "disabled" : "";
    if (!r || (!r.keep_until && r.face_video_days == null)) return "";
    const parts = [];
    if (r.sessions.length) parts.push(`${r.sessions.length} session${r.sessions.length === 1 ? "" : "s"} past the keep-until date (${esc(r.keep_until)}) ${btn("data-retention:sessions", "Delete them…", "link danger", dis)}`);
    if (r.face_videos.length) parts.push(`face videos of ${r.face_videos.length} session${r.face_videos.length === 1 ? "" : "s"} older than ${r.face_video_days} days ${btn("data-retention:face_videos", "Delete the videos…", "link danger", dis)}`);
    return parts.length ? `<p class="error-box">Retention: ${parts.join("; ")}</p>`
      : `<p class="hint">Retention: keep until ${esc(r.keep_until || "–")}${r.face_video_days != null ? `; face videos ${r.face_video_days} days after unloading` : ""}. Nothing due.</p>`;
  }

  async function dataCall(name, busy, ...args) {
    const D = ui.data;
    D.error = null;
    ui.phone.progress = "Starting…";
    try { D.last = await bridge(name, busy, ui.folder, ...args); }
    catch (e) { D.error = e.message; }
    ui.phone.progress = null;
    await dataRefresh();
  }

  async function dataPeople(name, pid) {
    if (name === "data-withdraw") {
      const reason = prompt(`Withdraw ${pid}? Their data is moved aside and left out of every table; you can restore it until you delete it permanently.\n\nReason (optional, kept in withdrawals.csv):`, "");
      if (reason === null) return;
      if (prompt(`Type ${pid} to confirm the withdrawal:`) !== pid) return;
      await dataCall("data_withdraw", "Withdrawing…", pid, reason);
    } else if (name === "data-restore") {
      if (!confirm(`Restore ${pid}'s data? They will be in the tables again.`)) return;
      await dataCall("data_restore", "Restoring…", pid);
    } else if (name === "data-delete-withdrawn") {
      if (prompt(`Delete ${pid}'s data permanently, from this computer, the second copy and the phone if connected? This can't be undone. Type ${pid} to confirm:`) !== pid) return;
      await dataCall("data_delete_withdrawn", "Deleting…", pid, ui.phone.serial || null);
    }
  }

  /** Data: face videos and eye tracking, for studies that have them. */
  function analysisSection(st) {
    const D = ui.data, f = st.faces || {}, g = st.gaze || {}, dis = ui.busy ? "disabled" : "";
    if (!f.videos && !g.sessions && !g.recorded) return "";
    let html = `<h3>Analysis</h3>`;
    if (f.videos) {
      const left = f.videos - f.analysed;
      html += `<div class="row">${btn("data-faces", "Analyse face videos", "", dis || (!left && !D.blur ? "disabled" : ""))} ${expBadge("face_analysis")}
        <span class="hint">${f.analysed} of ${f.videos} analysed${left ? ` · about as long as the videos` : ""}</span>
        <label class="check"><input type="checkbox" id="data-blur" ${D.blur ? "checked" : ""}> <span>Also make blurred copies for sharing</span></label></div>`;
      const r = D.faces;
      if (r) html += `<p class="hint">Analysed ${r.analysed}${r.blurred ? `, blurred ${r.blurred}` : ""}${r.skipped.length
        ? `. Couldn't do ${r.skipped.length}: ${r.skipped.map((x) => esc(`${x.folder.split(/[\\/]/).slice(-2).join("/")} (${x.why})`)).join("; ")}` : ""}. Make tables to add the face columns.</p>`;
    }
    if (g.recorded) {
      const left = g.copied - g.sessions, missing = g.recorded - g.copied;
      html += `<div class="row">${btn("data-gaze", "Analyse eye tracking", "", dis || (left > 0 ? "" : "disabled"))} ${expBadge("gaze")}
        <span class="hint">${g.sessions} of ${g.recorded} session${g.recorded === 1 ? "" : "s"} analysed${left > 0 ? ` · a few minutes each` : ""}${missing
          ? ` · ${missing} Neon recording${missing === 1 ? "" : "s"} not copied yet: Copy from the phone with Companion's phone connected` : ""}</span></div>`;
      const r = D.gaze;
      if (r) {
        html += `<p class="hint">Analysed ${r.analysed}.${r.skipped.length ? ` Couldn't do ${r.skipped.length}: ${r.skipped.map((x) => esc(`${x.session} (${x.why})`)).join("; ")}.` : ""}</p>`;
        if (r.results.length) html += `<ul class="checks">${r.results.map((x) => `<li class="${x.warnings.length ? "warning" : "ok"}"><div class="msg"><span class="ic">${x.warnings.length ? "!" : "✓"}</span><span>${esc(x.session)}: feed ${x.feed_mapped == null ? "–" : Math.round(x.feed_mapped * 100) + "%"} on screen; accuracy ${x.accuracy_deg == null ? "–" : x.accuracy_deg.toFixed(2) + "°"}${x.offset_applied ? " after the offset" : " (no offset: validation dots not scored)"}; ${x.fixations == null ? "no fixations" : x.fixations + " fixations"}${x.warnings.length ? ". " + esc(x.warnings.join("; ")) : ""}</span></div></li>`).join("")}</ul>`;
      }
    }
    if (g.sessions) {
      const factors = (ui.study && ui.study.factors || []).map((x) => x.name);
      html += `<div class="row">${btn("data-heatmaps", "Make heatmaps", "", dis)} ${expBadge("gaze")}
        <label class="hint" for="data-by">by</label>
        <select id="data-by">${[["cell", "condition"], ...factors.map((n) => [n, n])].map(([v, l]) => `<option value="${esc(v)}" ${D.by === v ? "selected" : ""}>${esc(l)}</option>`).join("")}</select>
        <span class="hint">${g.sessions} session${g.sessions === 1 ? "" : "s"} with eye tracking</span>
        ${(D.heatmaps && D.heatmaps.page) || g.heatmaps ? btn("open-path:" + ((D.heatmaps && D.heatmaps.page) || g.heatmaps), "Open heatmaps", "link") : ""}</div>`;
      const h = D.heatmaps;
      if (h && h.skipped.length) html += `<p class="hint">Left out ${h.skipped.length} session(s) without fixations.</p>`;
    }
    return html + (ui.busy && ui.phone.progress && ["Analysing faces…", "Analysing eye tracking…", "Making heatmaps…"].includes(ui.busy) ? `<p class="hint">${esc(ui.phone.progress)}</p>` : "");
  }

  async function dataFaces() {
    const D = ui.data;
    D.error = null;
    ui.phone.progress = "Starting…";
    try { D.faces = await bridge("data_faces", "Analysing faces…", ui.folder, D.blur); }
    catch (e) { D.error = e.message; }
    ui.phone.progress = null;
    await dataRefresh();
  }

  async function dataGaze() {
    const D = ui.data;
    D.error = null;
    ui.phone.progress = "Starting…";
    try { D.gaze = await bridge("data_gaze", "Analysing eye tracking…", ui.folder); }
    catch (e) { D.error = e.message; }
    ui.phone.progress = null;
    await dataRefresh();
  }

  async function dataHeatmaps() {
    const D = ui.data;
    D.error = null;
    ui.phone.progress = "Starting…";
    try { D.heatmaps = await bridge("data_heatmaps", "Making heatmaps…", ui.folder, D.by); }
    catch (e) { D.error = e.message; }
    ui.phone.progress = null;
    await dataRefresh();
  }

  async function dataRefresh() {
    const D = ui.data;
    D.error = null;
    if (!ui.folder) { D.status = null; render(); return; }
    try { D.status = await bridge("data_status", "Looking at the phone…", ui.folder, ui.phone.serial || null); }
    catch (e) { D.error = e.message; D.status = null; }
    render();
  }

  async function dataUnload() {
    const D = ui.data;
    D.error = null;
    ui.phone.progress = "Starting…";
    try { D.unload = await bridge("data_unload", "Unloading…", ui.folder, ui.phone.serial || null); }
    catch (e) { D.error = e.message; }
    ui.phone.progress = null;
    await dataRefresh();
  }

  async function dataExport() {
    const D = ui.data;
    D.error = null;
    ui.phone.progress = "Starting…";
    try { D.export = await bridge("data_export", "Making tables…", ui.folder, D.unblind); }
    catch (e) { D.error = e.message; }
    ui.phone.progress = null;
    render();
  }

  async function dataPick(which) {
    try {
      const start = which === "data" ? ui.data.status && ui.data.status.data_dir : ui.data.status && ui.data.status.second_copy_dir;
      const path = await bridge("pick_folder", null, start || null);
      if (!path) return;
      await bridge("data_set_folder", null, ui.folder, which, path);
    } catch (e) { ui.data.error = e.message; }
    await dataRefresh();
  }

  async function dataAct(name, arg) {
    try {
      if (name === "data-clear") await bridge("data_set_folder", null, ui.folder, arg, null);
      if (name === "data-open") { await bridge("open_path", null, ui.data.status.data_dir); return; }
    } catch (e) { ui.data.error = e.message; render(); return; }
    await dataRefresh();
  }

  function render() {
    if (!renderApp()) return;
    const focused = document.activeElement && document.activeElement.dataset ? document.activeElement.dataset.key : null;
    let sel = null;
    try { sel = focused ? [document.activeElement.selectionStart, document.activeElement.selectionEnd] : null; } catch (e) { sel = null; }
    document.getElementById("nav").innerHTML = sections().map(([k, label]) =>
      `<button type="button" data-section="${k}" class="${ui.section === k ? "on" : ""}" ${!ui.study && k !== "start" ? "disabled" : ""}>${sectionLabel(k, label)}<span class="count"></span></button>`).join("")
      + `<label class="check adv-toggle" title="Show every setting, for researchers who know the study design and their eye-tracking setup"><input type="checkbox" id="advanced-toggle" ${ui.advanced ? "checked" : ""}> <span>Advanced settings</span></label>`
      + (ui.study ? `<div class="undo-row">${btn("undo", "↶ Undo", "link", 'title="Undo (Ctrl+Z)"')}${btn("redo", "↷ Redo", "link", 'title="Redo (Ctrl+Y)"')}</div>` : "");
    const main = document.getElementById("main");
    ui.hidden = [];
    const page = ui.study || ui.section === "start" ? RENDER[ui.section]() : sectionStart();
    main.innerHTML = page + moreSettings() + navButtons();
    annotateTerms(main);
    renderSide();
    save();
    syncUndo();
    if (focused) {
      const el = main.querySelector(`[data-key="${CSS.escape(focused)}"]`);
      if (el) { el.focus(); try { if (sel && sel[0] != null) el.setSelectionRange(sel[0], sel[1]); } catch (e) { /* not a text field */ } }
    }
  }

  function navButtons() {
    if (!ui.study) return "";
    const list = sections();
    const i = list.findIndex(([k]) => k === ui.section);
    const prev = list[i - 1], next = list[i + 1];
    return `<div class="pager">${prev ? btn(`goto:${prev[0]}`, `← ${sectionLabel(...prev)}`) : "<span></span>"}${next ? btn(`goto:${next[0]}`, `${sectionLabel(...next)} →`, "primary") : ""}</div>`;
  }

  /** Advanced settings on or off, remembered on this computer. */
  function setAdvanced(on) {
    ui.advanced = on;
    try { localStorage.setItem(ADVANCED_STORE, on ? "1" : "0"); } catch (e) { /* storage unavailable */ }
  }

  /** Keeps the draft in the browser's storage, so it survives closing the page (or the app).
   * `key`: the field being typed in, so a burst of typing is one undo step. */
  function save(key = null) {
    if (!ui.study) return;
    track(key);
    const draft = JSON.stringify({ study: ui.study, content: ui.content, withCsv: ui.withCsv, opened: ui.opened,
      folder: ui.folder, savedYaml: ui.savedYaml, hadComments: ui.hadComments, at: Date.now() });
    try {
      localStorage.setItem(STORE, draft);
      // the desktop app also keeps each study's unsaved changes, offered back when the study is opened
      if (ui.desktop && ui.folder) {
        if (unsaved()) localStorage.setItem(DRAFT_PREFIX + ui.folder, draft);
        else localStorage.removeItem(DRAFT_PREFIX + ui.folder);
      }
    } catch (e) { /* storage unavailable */ }
  }

  function readDraft(key) {
    try { return JSON.parse(localStorage.getItem(key) || "null"); } catch (e) { return null; }
  }

  // ------------------------------------------------------------ undo

  function resetHistory() { ui.history = { past: [], future: [], last: null, key: null, at: 0 }; }

  /** Notes a change to the study as an undo step (typing on in one field joins the step before it). */
  function track(key) {
    const H = ui.history, cur = JSON.stringify({ study: ui.study, content: ui.content });
    if (H.last === null) { H.last = cur; return; }
    if (cur === H.last) return;
    const now = Date.now();
    if (!(key && key === H.key && now - H.at < TYPING_MS)) {
      H.past.push(H.last);
      if (H.past.length > HISTORY_MAX) H.past.shift();
    }
    H.future = [];
    H.last = cur;
    H.key = key;
    H.at = now;
  }

  function undo(redo = false) {
    const H = ui.history, from = redo ? H.future : H.past, to = redo ? H.past : H.future;
    if (!from.length) return;
    to.push(H.last);
    H.last = from.pop();
    H.key = null;
    const s = JSON.parse(H.last);
    ui.study = s.study;
    ui.content = s.content;
    ui.protect = null;
    render();
  }

  function syncUndo() {
    for (const [a, list] of [["undo", ui.history.past], ["redo", ui.history.future]]) {
      const b = document.querySelector(`#nav [data-action="${a}"]`);
      if (b) b.disabled = !list.length;
    }
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

  function newStep(type) {
    const s = { id: C.stepId(type, (ui.study.procedure || []).map((x) => x.id)), type };
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
    ui.sessions = 0;
    ui.protect = null;
    ui.phone.result = null;
    ui.data = { status: null, unload: null, export: null, faces: null, gaze: null, heatmaps: null, blur: false, by: "cell", unblind: false, error: null };
    ui.files.result = null;
    ui.aois = { result: null, overwrite: false, error: null };
    ui.images = { match: null, assign: {}, replace: false, copied: null, report: null, resized: null, error: null };
    ui.preview = { result: null, pid: null, conditions: false, error: null };
    resetHistory();
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
      if (folder) await openStudyAt(folder);
    } catch (e) {
      ui.desktopError = `Couldn't open the study: ${e.message}`;
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
        if (r.needs_version) {   // nothing was written: the edit would break the sessions collected so far
          ui.protect = r.needs_version;
          ui.section = "download";
          render();
          return;
        }
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
      ui.sessions = r.sessions || 0;
      ui.protect = null;
      ui.desktopError = null;
      ui.files.result = null;
      ui.preview.result = null;
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
          if (ui.desktop) ui.tab = "design";
          render();
        } catch (e) { ui.loadError = "The saved draft couldn't be read."; render(); }
        return;
      }
      case "go-basics": ui.section = "basics"; break;
      case "undo": undo(); return;
      case "redo": undo(true); return;
      case "goto":
        ui.section = args[0];
        window.scrollTo(0, 0);
        if (ui.desktop && (ui.section === "content" || ui.section === "procedure") && !ui.files.result && !ui.busy) { render(); filesRefresh(); return; }
        if (ui.desktop && ui.section === "preview" && !ui.preview.result && !ui.busy) { render(); previewRefresh(); return; }
        break;
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
      case "del-step": {
        const [gone] = S.procedure.splice(Number(args[0]), 1);
        const tagged = getP("markers.on_screen.steps");
        if (Array.isArray(tagged) && gone) setP("markers.on_screen.steps", tagged.filter((id) => id !== gone.id));
        ui.openStep = null;
        break;
      }
      case "add-step": {
        const type = document.getElementById("new-step").value;
        const s = newStep(type);
        const endAt = S.procedure.length && S.procedure[S.procedure.length - 1].type === "end" ? S.procedure.length - 1 : S.procedure.length;
        S.procedure.splice(endAt, 0, s);
        if (type === "recognition") C.syncFoils(S, ui.content);
        // a study with on-screen tags shows them during validation too, so its dots can be scored
        const tagged = getP("markers.on_screen.steps");
        if (type === "validation" && Array.isArray(tagged) && tagged.length) setP("markers.on_screen.steps", [...tagged, s.id]);
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
      case "advanced-on": setAdvanced(true); break;
      case "preview": ui.previewFile = args.join(":"); break;
      case "download-zip": {
        const files = C.studyFiles(S, ui.content, ui.withCsv);
        download(`${S.id || "study"}.zip`, C.zip(files, S.id || "study"), "application/zip");
        return;
      }
      case "download-yaml": download("study.yaml", C.toYaml(S), "text/yaml"); return;
      case "tab":
        ui.tab = args[0];
        window.scrollTo(0, 0);
        if (ui.tab === "phone" && !ui.phone.result && !ui.busy) { render(); phoneCheck(); return; }
        if (ui.tab === "data" && !ui.busy) { render(); dataRefresh(); return; }
        if (ui.tab === "studies" && !ui.busy) { render(); studiesRefresh(); return; }
        if (ui.tab === "design" && (ui.section === "content" || ui.section === "procedure") && !ui.files.result && !ui.busy) { render(); filesRefresh(); return; }
        break;
      case "studies-refresh": studiesRefresh(); return;
      case "study-open": case "study-goto": case "studies-new-blank": case "studies-copy": studiesAct(name, args); return;
      case "files-refresh": filesRefresh(); return;
      case "open-path": bridge("open_path", null, args.join(":")).catch((e) => { ui.desktopError = e.message; render(); }); return;
      case "data-refresh": dataRefresh(); return;
      case "data-unload": dataUnload(); return;
      case "data-export": dataExport(); return;
      case "data-faces": dataFaces(); return;
      case "data-gaze": dataGaze(); return;
      case "data-clear-phone":
        if (confirm("Delete from the phone the sessions whose copy on this computer (and second copy) still matches it? Anything else stays on the phone.")) dataCall("data_clear", "Clearing the phone…", ui.phone.serial || null).then(() => { ui.data.unload = ui.data.last; render(); });
        return;
      case "data-withdraw": case "data-restore": case "data-delete-withdrawn": dataPeople(name, args.join(":")); return;
      case "data-retention":
        if (confirm(args[0] === "sessions" ? "Delete every session past the study's keep-until date from this computer (and the second copy)? The register keeps their rows. This can't be undone."
          : "Delete the raw face videos that are due (the face measures stay)? This can't be undone.")) dataCall("data_retention_delete", "Deleting…", args[0]);
        return;
      case "data-heatmaps": dataHeatmaps(); return;
      case "aois-draw": aoisDraw(); return;
      case "aois-edit":
        window.AoiEditor.open({ call: bridge, folder: ui.folder, onClose: (saved) => { if (saved) filesRefresh(); } });
        return;
      case "images-pick": imagesPick(); return;
      case "fix": {
        const fix = ui.fixes && ui.fixes[Number(args[0])];
        if (!fix) return;
        C.applyFix(ui.study, ui.content, fix);
        if (fix.op === "insert_step") ui.openStep = null;
        render();
        return;
      }
      case "fix-files": ui.section = "content"; render(); imagesPick(); return;
      case "sources-make":
        bridge("sources_make", "Making sources.csv…", ui.folder).then(filesRefresh).catch((e) => { ui.files.error = e.message; render(); });
        return;
      case "images-copy": imagesCopy(); return;
      case "images-report": imagesReport(); return;
      case "images-resize": imagesResize(); return;
      case "preview-refresh": previewRefresh(); return;
      case "data-open-export": bridge("open_path", null, ui.data.export.out_dir).catch((e) => { ui.data.error = e.message; render(); }); return;
      case "data-pick": dataPick(args[0]); return;
      case "data-clear": case "data-open": dataAct(name, args[0]); return;
      case "phone-check": phoneCheck(); return;
      case "setup-do": setupDo(args[0]); return;
      case "setup-toggle": ui.phone.setupOpen = !ui.phone.setupOpen; render(); return;
      case "phone-load": phoneLoad(); return;
      case "open-folder": openFolder(); return;
      case "save": saveStudy(false); return;
      case "save-new-version": S.version = Number(ui.protect.version) + 1; ui.protect = null; saveStudy(false); return;
      case "protect-cancel": ui.protect = null; break;
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
    } else if (name === "cam-step" || name === "tags-step") {
      const path = name === "cam-step" ? "logging.front_camera.steps" : "markers.on_screen.steps";
      let steps = val(path, name === "cam-step" ? ["feed"] : []);
      steps = Array.isArray(steps) ? steps.slice() : [];
      const id = args.join(":");
      if (el.checked && !steps.includes(id)) steps.push(id);
      if (!el.checked) steps = steps.filter((x) => x !== id);
      const order = S.procedure.map((s) => s.id);
      steps.sort((x, y) => order.indexOf(x) - order.indexOf(y));
      setP(path, steps);
    } else if (name === "part") {
      if (!setPart(args[0], el.checked)) { el.checked = !el.checked; return; }
    } else if (name === "images-assign") {
      const src = ui.images.match && ui.images.match.unmatched[Number(args[0])];
      if (src) ui.images.assign[src] = el.value;
      render();
      return;
    } else if (name === "tags-layout") {
      // each layout with the tags it was tested with: bars 10 mm tag16h5, bands 12 mm tag36h11
      const preset = el.value === "bars" ? { family: "tag16h5", size_mm: 10 } : { family: "tag36h11", size_mm: 12 };
      setP("markers.on_screen.layout", el.value);
      setP("markers.on_screen.family", preset.family);
      setP("markers.on_screen.size_mm", preset.size_mm);
    } else if (name === "exposure-mode") {
      // schema: manual needs exposure_us; exposure_us and gain only go with manual
      const old = getP("neon.scene_exposure") || {};
      if (el.value === "__null__") setP("neon.scene_exposure", undefined);
      else if (el.value === "auto") setP("neon.scene_exposure", { mode: "auto", ...(old.brightness != null ? { brightness: old.brightness } : {}) });
      else setP("neon.scene_exposure", { mode: "manual", exposure_us: old.exposure_us || 4000, ...(old.gain != null ? { gain: old.gain } : {}) });
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
    if (oldId !== null) {   // a renamed step stays chosen for the front camera and on-screen tags
      for (const p of ["logging.front_camera.steps", "markers.on_screen.steps"]) {
        const steps = getP(p);
        if (Array.isArray(steps)) setP(p, steps.map((x) => (x === oldId ? v : x)));
      }
    }
  }

  // ------------------------------------------------------------ wiring

  document.addEventListener("click", (e) => {
    const nav = e.target.closest("#nav button[data-section]");
    if (nav && !nav.disabled) { act(`goto:${nav.dataset.section}`); return; }
    const b = e.target.closest("[data-action]");
    if (b) act(b.dataset.action, b);
  });

  document.addEventListener("input", (e) => {
    const el = e.target;
    if (el.id === "new-study-id") { ui.studies.newId = el.value; return; }
    if (!el.dataset || !el.dataset.path || el.dataset.kind === "bool" || el.tagName === "SELECT") return;
    applyInput(el);
    renderSide();
    save(el.dataset.path);
    syncUndo();
  });

  // Ctrl+Z / Ctrl+Y (Ctrl+Shift+Z) undo and redo changes to the study, in text fields too
  document.addEventListener("keydown", (e) => {
    if (!(e.ctrlKey || e.metaKey) || e.altKey || !ui.study || (ui.desktop && ui.tab !== "design")) return;
    const k = e.key.toLowerCase();
    if (k === "z" && !e.shiftKey) { e.preventDefault(); undo(); }
    else if (k === "y" || (k === "z" && e.shiftKey)) { e.preventDefault(); undo(true); }
  });

  document.addEventListener("change", (e) => {
    const el = e.target;
    if (el.id === "open-file" && el.files && el.files[0]) { openFile(el.files[0]); return; }
    if (el.id === "phone-update") { ui.phone.updateApp = el.checked; return; }
    if (el.id === "aois-overwrite") { ui.aois.overwrite = el.checked; return; }
    if (el.id === "images-replace") { ui.images.replace = el.checked; render(); return; }
    if (el.id === "preview-pid") { ui.preview.pid = el.value; previewRefresh(); return; }
    if (el.id === "preview-conditions") { ui.preview.conditions = el.checked; render(); return; }
    if (el.id === "data-blur") { ui.data.blur = el.checked; render(); return; }
    if (el.id === "data-unblind") {
      if (el.checked && !confirm("Unblinding shows which condition is which. Do it only once your analysis plan is fixed. Unblind the next tables and exploration page?")) { el.checked = false; return; }
      ui.data.unblind = el.checked; return;
    }
    if (el.id === "data-by") { ui.data.by = el.value; return; }
    if (el.id === "advanced-toggle") { setAdvanced(el.checked); render(); return; }
    if (el.id === "files-missing") { ui.files.missingOnly = el.checked; render(); return; }
    if (el.id === "phone-serial") { ui.phone.serial = el.value; ui.phone.result = null; phoneCheck(); return; }
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
    if (ui.section === "start") ui.section = "basics";
    act("tab:studies");
  }
  window.addEventListener("pywebviewready", enterDesktop);

  try { ui.advanced = localStorage.getItem(ADVANCED_STORE) === "1"; } catch (e) { ui.advanced = false; }
  render();
  enterDesktop();
})();
