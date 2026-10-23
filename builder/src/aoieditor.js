/* The AOI editor (desktop app, Design > Content > Edit AOIs): draw, outline and name AOIs on a
   study's images. A full-window layer of its own, so drawing doesn't re-render the builder.

   AoiEditor.open({ call, folder, image, onClose }):
     call(name, busyText, ...args) -> the bridge method's result (throws its message)
     onClose(saved) is called when the editor closes (saved: whether any file was written)

   Tools: Select (drag points; drag a mid-point to add one; double-click a point to remove it),
   Polygon (click points; click the first point or press Enter to finish), Rectangle (drag),
   Outline (click on a thing; Shift+click or right-click for "not this"; then keep an outline). */
(function () {
  "use strict";

  const PRESETS = ["face", "hair", "upper_body", "waist", "legs", "body", "arms", "clothing", "background", "text"];
  const COLOURS = { face: "#ff6347", hair: "#ffc107", upper_body: "#2196f3", waist: "#9c27b0", legs: "#4caf50", body: "#9e9e9e" };
  const SPARE = ["#e91e63", "#00bcd4", "#ff9800", "#795548", "#3f51b5", "#8bc34a", "#607d8b", "#cddc39"];
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

  const CSS = `
.aoied { position: fixed; inset: 0; z-index: 1000; background: var(--bg); color: var(--text); display: grid;
  grid-template-rows: auto 1fr; font-size: 14px; }
.aoied header { display: flex; gap: 8px; align-items: center; padding: 8px 12px; border-bottom: 1px solid var(--line);
  background: var(--surface); flex-wrap: wrap; }
.aoied header h2 { font-size: 16px; margin: 0 8px 0 0; }
.aoied header select { font: inherit; padding: 5px 8px; border-radius: 8px; border: 1px solid var(--line);
  background: var(--surface); color: var(--text); max-width: 340px; }
.aoied header .grow { flex: 1; }
.aoied .state { color: var(--muted); font-size: 13px; }
.aoied .state.unsaved { color: var(--warn); font-weight: 600; }
.aoied .body { display: grid; grid-template-columns: 150px 1fr 300px; min-height: 0; }
.aoied .tools { padding: 10px; border-right: 1px solid var(--line); display: flex; flex-direction: column; gap: 6px; overflow: auto; }
.aoied .tools .btn { text-align: left; border-radius: 8px; padding: 6px 10px; }
.aoied .tools .btn.on { background: var(--accent-soft); border-color: var(--accent); }
.aoied .tools .key { color: var(--muted); font-size: 12px; float: right; }
.aoied .tools hr { border: 0; border-top: 1px solid var(--line); width: 100%; margin: 4px 0; }
.aoied .tools .hint { color: var(--muted); font-size: 12px; line-height: 1.4; }
.aoied .stage { overflow: auto; position: relative; background: repeating-conic-gradient(var(--line) 0 25%, transparent 0 50%) 0 0 / 16px 16px; }
.aoied .canvas { position: relative; margin: 16px; transform-origin: 0 0; }
.aoied .canvas img { display: block; width: 100%; height: 100%; user-select: none; -webkit-user-drag: none; }
.aoied .canvas svg { position: absolute; inset: 0; width: 100%; height: 100%; overflow: visible; }
.aoied svg .shape { fill-opacity: .22; stroke-width: 2; vector-effect: non-scaling-stroke; cursor: pointer; }
.aoied svg .shape.sel { fill-opacity: .35; stroke-width: 3; }
.aoied svg .label { font: 600 13px system-ui, sans-serif; paint-order: stroke; stroke: #fff; stroke-width: 3px; pointer-events: none; }
.aoied svg .pt { fill: #fff; stroke: #000; stroke-width: 1.5; vector-effect: non-scaling-stroke; cursor: move; }
.aoied svg .mid { fill: #000; fill-opacity: .45; stroke: #fff; stroke-width: 1; vector-effect: non-scaling-stroke; cursor: copy; }
.aoied svg .draft { fill: none; stroke: #000; stroke-dasharray: 6 4; stroke-width: 2; vector-effect: non-scaling-stroke; }
.aoied svg .cand { fill: #00e5ff; fill-opacity: .25; stroke: #00b8d4; stroke-width: 2.5; vector-effect: non-scaling-stroke; pointer-events: none; }
.aoied svg .click-yes { fill: #00c853; stroke: #fff; stroke-width: 2; vector-effect: non-scaling-stroke; }
.aoied svg .click-no { fill: #d50000; stroke: #fff; stroke-width: 2; vector-effect: non-scaling-stroke; }
.aoied .side { border-left: 1px solid var(--line); padding: 10px; overflow: auto; display: flex; flex-direction: column; gap: 10px; }
.aoied .side h3 { margin: 4px 0 0; font-size: 14px; }
.aoied .side .hint { color: var(--muted); font-size: 12px; line-height: 1.4; margin: 0; }
.aoied .note { background: var(--warn-soft); border-radius: 8px; padding: 6px 8px; font-size: 13px; }
.aoied .err { background: var(--error-soft); border-radius: 8px; padding: 6px 8px; font-size: 13px; }
.aoied .aoi { display: grid; grid-template-columns: 14px 1fr auto; gap: 6px; align-items: center; padding: 4px;
  border-radius: 8px; border: 1px solid transparent; }
.aoied .aoi.sel { border-color: var(--accent); background: var(--accent-soft); }
.aoied .aoi .sw { width: 14px; height: 14px; border-radius: 3px; }
.aoied .aoi input { font: inherit; padding: 4px 6px; border-radius: 6px; border: 1px solid var(--line); background: var(--surface);
  color: var(--text); min-width: 0; }
.aoied .aoi .ops button { font: inherit; border: 0; background: none; color: var(--muted); cursor: pointer; padding: 2px 4px; }
.aoied .aoi .ops button:hover { color: var(--text); }
.aoied .cands { display: flex; gap: 6px; flex-wrap: wrap; }
.aoied .cands .btn.on { background: var(--accent-soft); border-color: var(--accent); }
.aoied .row { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
.aoied .busy { position: absolute; top: 12px; left: 50%; transform: translateX(-50%); background: var(--surface);
  border: 1px solid var(--line); border-radius: 999px; padding: 4px 12px; box-shadow: var(--shadow); font-size: 13px; }
`;

  let S = null;   // the open editor's state

  function colour(name, i) {
    return COLOURS[name] || SPARE[i % SPARE.length];
  }

  function open(opts) {
    if (S) return;
    if (!document.getElementById("aoied-css")) {
      const st = document.createElement("style");
      st.id = "aoied-css";
      st.textContent = CSS;
      document.head.appendChild(st);
    }
    const root = document.createElement("div");
    root.className = "aoied";
    document.body.appendChild(root);
    S = {
      opts, root, list: [], outline: "download", image: null, data: null, aois: [], sel: -1, tool: "select",
      draft: [], rect: null, clicks: [], cands: [], cand: 0, candNote: null, zoom: 1, fit: true,
      undo: [], redo: [], dirty: false, saved: false, busy: null, error: null, drag: null,
    };
    window.addEventListener("keydown", onKey, true);
    root.addEventListener("click", onClick);
    root.addEventListener("change", onChange);
    root.addEventListener("input", onInput);
    window.addEventListener("resize", layoutCanvas);
    refreshList().then(() => goTo(opts.image || (S.list[0] && S.list[0].image)));
  }

  async function call(name, busy, ...args) {
    S.busy = busy;
    if (busy) paint();
    try { return await S.opts.call(name, null, ...args); } finally { S.busy = null; }
  }

  async function refreshList() {
    try {
      const r = await call("aoi_images", null, S.opts.folder);
      S.list = r.images;
      S.outline = r.outline;
    } catch (e) { S.error = e.message; }
  }

  function close() {
    if (S.dirty && !confirm("Close without saving the changes to this image's AOIs?")) return;
    window.removeEventListener("keydown", onKey, true);
    window.removeEventListener("resize", layoutCanvas);
    S.root.remove();
    const done = S.opts.onClose, saved = S.saved;
    S = null;
    if (done) done(saved);
  }

  async function goTo(image) {
    if (!image) { paint(); return; }
    if (S.dirty && !confirm("Leave this image without saving its AOIs?")) { paint(); return; }
    S.error = null;
    try {
      const d = await call("aoi_load", "Opening the image…", S.opts.folder, image);
      Object.assign(S, { image, data: d, aois: d.aois.map((a) => ({ name: a.name, points: a.points })), sel: -1,
        draft: [], rect: null, clicks: [], cands: [], candNote: null, undo: [], redo: [], dirty: false, fit: true });
    } catch (e) { S.error = e.message; }
    paint();
  }

  // ------------------------------------------------------------ edits (with undo)

  function snapshot() {
    S.undo.push(JSON.stringify(S.aois));
    if (S.undo.length > 100) S.undo.shift();
    S.redo = [];
    S.dirty = true;
  }

  function undo(back) {
    const from = back ? S.undo : S.redo, to = back ? S.redo : S.undo;
    if (!from.length) return;
    to.push(JSON.stringify(S.aois));
    S.aois = JSON.parse(from.pop());
    S.sel = Math.min(S.sel, S.aois.length - 1);
    S.dirty = true;
    paint();
  }

  function freeName() {
    const used = new Set(S.aois.map((a) => a.name));
    const p = PRESETS.find((n) => !used.has(n));
    if (p) return p;
    let i = 1;
    while (used.has(`aoi${i}`)) i++;
    return `aoi${i}`;
  }

  function addAoi(points) {
    snapshot();
    S.aois.push({ name: freeName(), points: points.map(([x, y]) => [Math.round(x * 10) / 10, Math.round(y * 10) / 10]) });
    S.sel = S.aois.length - 1;
    S.tool = S.tool === "outline" ? "outline" : "select";
    paint();
    const input = S.root.querySelector(`input[data-name="${S.sel}"]`);
    if (input) { input.focus(); input.select(); }
  }

  async function save() {
    const names = S.aois.map((a) => a.name.trim());
    if (names.some((n) => !n)) { S.error = "Every AOI needs a name."; paint(); return; }
    const dup = names.find((n, i) => names.indexOf(n) !== i);
    if (dup) { S.error = `Two AOIs are called "${dup}"; each name can be used once per image.`; paint(); return; }
    S.error = null;
    try {
      const r = await call("aoi_save", "Saving…", S.opts.folder, S.image, S.aois);
      S.dirty = false;
      S.saved = true;
      S.savedNote = `Saved ${r.n} AOI${r.n === 1 ? "" : "s"} to ${r.aoi_file}` + (r.kept ? "; the previous file is kept in aoi_history" : "");
      await refreshList();
    } catch (e) { S.error = e.message; }
    paint();
  }

  /** The other versions of this post (original/retouched): their AOIs can be copied here. */
  function siblings() {
    const me = S.list.find((x) => x.image === S.image);
    if (!me || !me.post_id) return [];
    return S.list.filter((x) => x.post_id === me.post_id && x.image !== S.image && x.exists);
  }

  async function copyFrom(image) {
    if (S.aois.length && !confirm("Replace this image's AOIs with the other version's?")) return;
    try {
      const d = await call("aoi_load", "Reading the other version…", S.opts.folder, image);
      const sx = S.data.width / d.width, sy = S.data.height / d.height;
      snapshot();
      S.aois = d.aois.map((a) => ({ name: a.name, points: a.points.map(([x, y]) => [x * sx, y * sy]) }));
      S.sel = -1;
    } catch (e) { S.error = e.message; }
    paint();
  }

  // ------------------------------------------------------------ outlining

  async function outlineNow() {
    if (!S.clicks.length) { S.cands = []; paint(); return; }
    try {
      const busy = S.outline === "download" ? "Downloading the outlining model (45 MB, once)…" : "Outlining…";
      const r = await call("aoi_outline", busy, S.opts.folder, S.image, S.clicks);
      S.outline = r.backend;
      S.candNote = r.note;
      S.cands = r.outlines;
      S.cand = 0;
    } catch (e) { S.error = e.message; }
    paint();
  }

  function keepCandidate() {
    const c = S.cands[S.cand];
    if (!c) return;
    S.clicks = [];
    S.cands = [];
    addAoi(c.polygon);
  }

  // ------------------------------------------------------------ drawing

  function svgPoint(ev) {
    const svg = S.root.querySelector("svg");
    const p = svg.createSVGPoint();
    p.x = ev.clientX;
    p.y = ev.clientY;
    const q = p.matrixTransform(svg.getScreenCTM().inverse());
    return [Math.min(Math.max(q.x, 0), S.data.width), Math.min(Math.max(q.y, 0), S.data.height)];
  }

  function nearFirst(p) {
    if (S.draft.length < 3) return false;
    const [x, y] = S.draft[0];
    const r = 10 / scale();
    return Math.hypot(p[0] - x, p[1] - y) < r;
  }

  function scale() {
    const c = S.root.querySelector(".canvas");
    return c ? c.getBoundingClientRect().width / S.data.width : 1;
  }

  function finishPolygon() {
    if (S.draft.length >= 3) addAoi(S.draft);
    S.draft = [];
    paintSvg();
  }

  function onPointerDown(ev) {
    if (!S.data || ev.button === 1) return;
    const t = ev.target, p = svgPoint(ev);
    if (S.tool === "outline") {
      ev.preventDefault();
      S.clicks.push([Math.round(p[0]), Math.round(p[1]), !(ev.shiftKey || ev.button === 2)]);
      paintSvg();
      outlineNow();
      return;
    }
    if (ev.button !== 0) return;
    if (S.tool === "polygon") {
      if (nearFirst(p)) finishPolygon();
      else { S.draft.push(p); paintSvg(); }
      return;
    }
    if (S.tool === "rect") {
      S.rect = [p, p];
      S.drag = { kind: "rect" };
      ev.currentTarget.setPointerCapture(ev.pointerId);
      return;
    }
    // select: a point, a mid-point or a shape
    if (t.dataset.pt) {
      const [a, i] = t.dataset.pt.split(":").map(Number);
      snapshot();
      S.drag = { kind: "pt", a, i };
    } else if (t.dataset.mid) {
      const [a, i] = t.dataset.mid.split(":").map(Number);
      snapshot();
      S.aois[a].points.splice(i + 1, 0, p);
      S.drag = { kind: "pt", a, i: i + 1 };
    } else if (t.dataset.shape) {
      const a = Number(t.dataset.shape);
      S.sel = a;
      snapshot();
      S.drag = { kind: "move", a, from: p, orig: S.aois[a].points.map((q) => q.slice()), moved: false };
      ev.currentTarget.setPointerCapture(ev.pointerId);
      paint();
      return;
    } else {
      S.sel = -1;
      paint();
      return;
    }
    ev.currentTarget.setPointerCapture(ev.pointerId);   // the svg: its shapes are redrawn while dragging
    paintSvg();
  }

  function onPointerMove(ev) {
    if (!S.data) return;
    const p = svgPoint(ev);
    if (S.drag && S.drag.kind === "pt") {
      S.aois[S.drag.a].points[S.drag.i] = p;
      paintSvg();
    } else if (S.drag && S.drag.kind === "move") {
      const dx = p[0] - S.drag.from[0], dy = p[1] - S.drag.from[1];
      if (Math.hypot(dx, dy) > 1) S.drag.moved = true;
      S.aois[S.drag.a].points = S.drag.orig.map(([x, y]) => [x + dx, y + dy]);
      paintSvg();
    } else if (S.drag && S.drag.kind === "rect") {
      S.rect[1] = p;
      paintSvg();
    } else if (S.tool === "polygon" && S.draft.length) {
      S.hover = p;
      paintSvg();
    }
  }

  function onPointerUp() {
    if (!S || !S.drag) return;
    const d = S.drag;
    S.drag = null;
    if (d.kind === "rect") {
      const [[x0, y0], [x1, y1]] = S.rect;
      S.rect = null;
      if (Math.abs(x1 - x0) > 3 && Math.abs(y1 - y0) > 3) addAoi([[x0, y0], [x1, y0], [x1, y1], [x0, y1]]);
      else paintSvg();
    } else if (d.kind === "move" && !d.moved) {
      S.undo.pop();                  // a click to select, not a move
      S.dirty = S.undo.length > 0 || S.dirty;
    } else {
      S.aois.forEach((a) => { a.points = a.points.map(([x, y]) => [Math.round(x * 10) / 10, Math.round(y * 10) / 10]); });
      paint();
    }
  }

  function onDblClick(ev) {
    const t = ev.target;
    if (S.tool === "select" && t.dataset.pt) {
      const [a, i] = t.dataset.pt.split(":").map(Number);
      if (S.aois[a].points.length <= 3) return;
      snapshot();
      S.aois[a].points.splice(i, 1);
      paintSvg();
    } else if (S.tool === "polygon") {
      S.draft.pop();                 // the double-click's second click added a point
      finishPolygon();
    }
  }

  // ------------------------------------------------------------ events

  function setTool(tool) {
    S.tool = tool;
    S.draft = [];
    S.rect = null;
    if (tool !== "outline") { S.clicks = []; S.cands = []; }
    paint();
  }

  function onKey(ev) {
    if (!S) return;
    const typing = ev.target && (ev.target.tagName === "INPUT" || ev.target.tagName === "SELECT");
    ev.stopPropagation();            // the builder's own shortcuts (its undo) stay out of the editor
    if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "s") { ev.preventDefault(); save(); return; }
    if (typing) { if (ev.key === "Enter") ev.target.blur(); return; }
    if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "z") { ev.preventDefault(); undo(!ev.shiftKey); return; }
    if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "y") { ev.preventDefault(); undo(false); return; }
    const k = ev.key;
    if (k === "Escape") {
      if (S.draft.length || S.clicks.length) { S.draft = []; S.clicks = []; S.cands = []; paint(); } else close();
    } else if (k === "Enter") {
      if (S.tool === "polygon") finishPolygon();
      else if (S.tool === "outline") keepCandidate();
    } else if ((k === "Delete" || k === "Backspace") && S.sel >= 0) {
      snapshot();
      S.aois.splice(S.sel, 1);
      S.sel = -1;
      paint();
    } else if (k === "v" || k === "V") setTool("select");
    else if (k === "p" || k === "P") setTool("polygon");
    else if (k === "r" || k === "R") setTool("rect");
    else if (k === "o" || k === "O") setTool("outline");
    else if (S.tool === "outline" && ["1", "2", "3"].includes(k) && S.cands[Number(k) - 1]) { S.cand = Number(k) - 1; paintSvg(); paintSide(); }
    else if (k === "+" || k === "=") zoomBy(1.25);
    else if (k === "-") zoomBy(0.8);
    else if (k === "0") { S.fit = true; layoutCanvas(); }
  }

  function zoomBy(f) {
    S.fit = false;
    S.zoom = Math.min(8, Math.max(0.1, S.zoom * f));
    layoutCanvas();
  }

  function onClick(ev) {
    const b = ev.target.closest("[data-ed]");
    if (!b) return;
    const [act, arg] = b.dataset.ed.split(/:(.*)/s);
    switch (act) {
      case "close": close(); break;
      case "save": save(); break;
      case "tool": setTool(arg); break;
      case "prev": case "next": {
        const i = S.list.findIndex((x) => x.image === S.image) + (act === "next" ? 1 : -1);
        if (S.list[i]) goTo(S.list[i].image);
        break;
      }
      case "sel": S.sel = Number(arg); paint(); break;
      case "del": snapshot(); S.aois.splice(Number(arg), 1); S.sel = -1; paint(); break;
      case "up": case "down": {
        const i = Number(arg), j = act === "up" ? i - 1 : i + 1;
        if (j < 0 || j >= S.aois.length) break;
        snapshot();
        [S.aois[i], S.aois[j]] = [S.aois[j], S.aois[i]];
        S.sel = j;
        paint();
        break;
      }
      case "cand": S.cand = Number(arg); paint(); break;
      case "keep": keepCandidate(); break;
      case "clear-clicks": S.clicks = []; S.cands = []; paint(); break;
      case "undo-click": S.clicks.pop(); outlineNow(); break;
      case "copy": copyFrom(arg); break;
      case "zoom-in": zoomBy(1.25); break;
      case "zoom-out": zoomBy(0.8); break;
      case "fit": S.fit = true; layoutCanvas(); break;
      case "undo": undo(true); break;
      case "redo": undo(false); break;
    }
  }

  function onChange(ev) {
    if (ev.target.dataset.ed === "image") goTo(ev.target.value);
  }

  function onInput(ev) {
    const i = ev.target.dataset.name;
    if (i === undefined) return;
    const a = S.aois[Number(i)];
    if (!a) return;
    if (!S.typing || S.typing !== i) { snapshot(); S.typing = i; }   // one undo step per name edit
    a.name = ev.target.value.replace(/\s+/g, "_");
    S.dirty = true;
    paintSvg();
    paintState();
  }

  // ------------------------------------------------------------ painting

  function paint() {
    if (!S) return;
    S.typing = null;
    const d = S.data;
    const opt = (x) => `<option value="${esc(x.image)}" ${x.image === S.image ? "selected" : ""}>${x.exists ? "✓" : x.needed ? "✗" : "·"} ${esc(x.what)}${x.names.length ? ` (${x.names.length})` : ""}</option>`;
    const needed = S.list.filter((x) => x.needed), other = S.list.filter((x) => !x.needed);
    const sib = d ? siblings() : [];
    const outlineLabel = S.outline === "mediapipe" ? "simple" : "SAM";
    S.root.innerHTML = `
      <header>
        <h2>AOIs</h2>
        <button class="btn" data-ed="prev" title="Previous image">←</button>
        <select data-ed="image">${needed.length ? `<optgroup label="Critical posts (need AOIs)">${needed.map(opt).join("")}</optgroup>` : ""}
          ${other.length ? `<optgroup label="Other images (optional)">${other.map(opt).join("")}</optgroup>` : ""}</select>
        <button class="btn" data-ed="next" title="Next image">→</button>
        ${sib.map((x) => `<button class="btn" data-ed="copy:${esc(x.image)}" title="Copy the AOIs drawn on ${esc(x.what)}">Copy from ${esc(x.what.replace(/^post \S+ /, ""))}</button>`).join("")}
        <span class="grow"></span>
        <span class="state"></span>
        <button class="btn" data-ed="undo" title="Undo (Ctrl+Z)">↶</button>
        <button class="btn" data-ed="redo" title="Redo (Ctrl+Y)">↷</button>
        <button class="btn primary" data-ed="save" title="Save (Ctrl+S)">Save</button>
        <button class="btn" data-ed="close" title="Close (Esc)">Close</button>
      </header>
      <div class="body">
        <div class="tools">
          ${[["select", "Select", "V"], ["polygon", "Polygon", "P"], ["rect", "Rectangle", "R"], ["outline", `Outline (${outlineLabel})`, "O"]]
            .map(([t, l, k]) => `<button class="btn ${S.tool === t ? "on" : ""}" data-ed="tool:${t}">${l}<span class="key">${k}</span></button>`).join("")}
          <hr>
          <div class="row"><button class="btn" data-ed="zoom-out" title="Zoom out (-)">−</button><button class="btn" data-ed="zoom-in" title="Zoom in (+)">+</button><button class="btn" data-ed="fit" title="Fit (0)">Fit</button></div>
          <hr>
          <div class="hint">${toolHint()}</div>
        </div>
        <div class="stage">${d ? `<div class="canvas"><img src="${d.src}" alt=""><svg viewBox="0 0 ${d.width} ${d.height}"></svg></div>` : ""}
          ${S.busy ? `<div class="busy">${esc(S.busy)}</div>` : ""}</div>
        <div class="side"></div>
      </div>`;
    const svg = S.root.querySelector("svg");
    if (svg) {
      svg.addEventListener("pointerdown", onPointerDown);
      svg.addEventListener("pointermove", onPointerMove);
      svg.addEventListener("pointerup", onPointerUp);
      svg.addEventListener("dblclick", onDblClick);
      svg.addEventListener("contextmenu", (ev) => ev.preventDefault());
    }
    layoutCanvas();
    paintSide();
    paintState();
  }

  function toolHint() {
    return {
      select: "Click an AOI to select it; drag it to move it. Drag a point to move it, drag a small dot between points to add one, double-click a point to remove it. Delete removes the selected AOI.",
      polygon: "Click around the area, point by point. Click the first point (or press Enter, or double-click) to finish. Esc starts again.",
      rect: "Drag a box.",
      outline: "Click on the thing to outline. Click more of it to add to the outline; Shift+click (or right-click) where it went too far. Choose an outline (1, 2, 3), then Keep (Enter).",
    }[S.tool];
  }

  function paintState() {
    const el = S.root.querySelector(".state");
    if (!el) return;
    el.className = "state" + (S.dirty ? " unsaved" : "");
    el.textContent = S.dirty ? "Unsaved changes" : (S.savedNote || (S.data ? S.data.aoi_file : ""));
  }

  function layoutCanvas() {
    if (!S || !S.data) return;
    const stage = S.root.querySelector(".stage"), c = S.root.querySelector(".canvas");
    if (!stage || !c) return;
    if (S.fit) S.zoom = Math.min((stage.clientWidth - 32) / S.data.width, (stage.clientHeight - 32) / S.data.height);
    c.style.width = `${S.data.width * S.zoom}px`;
    c.style.height = `${S.data.height * S.zoom}px`;
    paintSvg();
  }

  function paintSvg() {
    const svg = S && S.root.querySelector("svg");
    if (!svg) return;
    const r = 5 / scale();
    const poly = (pts) => pts.map(([x, y]) => `${x},${y}`).join(" ");
    let h = "";
    S.aois.forEach((a, i) => {
      const c = colour(a.name, i), sel = i === S.sel;
      h += `<polygon class="shape ${sel ? "sel" : ""}" data-shape="${i}" points="${poly(a.points)}" fill="${c}" stroke="${c}"/>`;
    });
    S.aois.forEach((a, i) => {   // labels on top of every shape
      const [x, y] = a.points.reduce(([mx, my], [px, py]) => [Math.min(mx, px), Math.min(my, py)], [Infinity, Infinity]);
      h += `<text class="label" x="${x + 4 / scale()}" y="${y + 16 / scale()}" fill="${colour(a.name, i)}" style="font-size:${13 / scale()}px;stroke-width:${3 / scale()}px">${esc(a.name)}</text>`;
    });
    if (S.tool === "select" && S.sel >= 0 && S.aois[S.sel]) {
      const pts = S.aois[S.sel].points;
      pts.forEach(([x, y], i) => {
        const [nx, ny] = pts[(i + 1) % pts.length];
        h += `<circle class="mid" data-mid="${S.sel}:${i}" cx="${(x + nx) / 2}" cy="${(y + ny) / 2}" r="${r * 0.7}"/>`;
      });
      pts.forEach(([x, y], i) => { h += `<circle class="pt" data-pt="${S.sel}:${i}" cx="${x}" cy="${y}" r="${r}"/>`; });
    }
    if (S.draft.length) {
      const pts = S.hover ? S.draft.concat([S.hover]) : S.draft;
      h += `<polyline class="draft" points="${poly(pts)}"/>`;
      S.draft.forEach(([x, y], i) => { h += `<circle class="pt" cx="${x}" cy="${y}" r="${i === 0 ? r * 1.4 : r}"/>`; });
    }
    if (S.rect) {
      const [[x0, y0], [x1, y1]] = S.rect;
      h += `<rect class="draft" x="${Math.min(x0, x1)}" y="${Math.min(y0, y1)}" width="${Math.abs(x1 - x0)}" height="${Math.abs(y1 - y0)}"/>`;
    }
    if (S.tool === "outline") {
      const c = S.cands[S.cand];
      if (c) h += `<polygon class="cand" points="${poly(c.polygon)}"/>`;
      S.clicks.forEach(([x, y, keep]) => { h += `<circle class="${keep ? "click-yes" : "click-no"}" cx="${x}" cy="${y}" r="${r * 1.3}"/>`; });
    }
    svg.innerHTML = h;
  }

  function paintSide() {
    const side = S.root.querySelector(".side");
    if (!side) return;
    const d = S.data;
    let h = "";
    if (S.error) h += `<div class="err">${esc(S.error)}</div>`;
    if (d && d.note) h += `<div class="note">${esc(d.note)}</div>`;
    if (S.tool === "outline") {
      h += `<h3>Outline <span class="exp" title="The outlines come from segmentation models and haven't been checked on real stimuli: look at every AOI before collecting data.">Experimental</span></h3>`;
      if (S.candNote) h += `<div class="note">${esc(S.candNote)}</div>`;
      if (!S.clicks.length) h += `<p class="hint">Click on the thing to outline${S.outline === "download" ? ". The first click downloads the outlining model (45 MB, once)" : ""}.</p>`;
      else if (!S.cands.length && !S.busy) h += `<p class="hint">No outline here; try clicking somewhere else.</p>`;
      if (S.cands.length) {
        h += `<div class="cands">${S.cands.map((c, i) => `<button class="btn ${i === S.cand ? "on" : ""}" data-ed="cand:${i}" title="${c.area} px">${i + 1}</button>`).join("")}</div>
          <p class="hint">${S.cands.length > 1 ? "The outlines go from a part to the whole thing. " : ""}</p>
          <div class="row"><button class="btn primary" data-ed="keep">Keep as an AOI</button></div>`;
      }
      if (S.clicks.length) h += `<div class="row"><button class="btn" data-ed="undo-click">Undo last click</button><button class="btn" data-ed="clear-clicks">Start again</button></div>`;
    }
    h += `<h3>AOIs on this image</h3>`;
    if (!S.aois.length) h += `<p class="hint">None yet: draw one with the tools on the left.</p>`;
    h += S.aois.map((a, i) => `<div class="aoi ${i === S.sel ? "sel" : ""}">
        <span class="sw" style="background:${colour(a.name, i)}" data-ed="sel:${i}"></span>
        <input data-name="${i}" value="${esc(a.name)}" list="aoied-names" spellcheck="false" aria-label="AOI name">
        <span class="ops"><button data-ed="up:${i}" title="Earlier: wins where AOIs overlap">↑</button><button data-ed="down:${i}" title="Later">↓</button><button data-ed="sel:${i}" title="Select">✎</button><button data-ed="del:${i}" title="Delete">✕</button></span>
      </div>`).join("");
    h += `<datalist id="aoied-names">${PRESETS.map((n) => `<option value="${n}">`).join("")}</datalist>
      <p class="hint">Where AOIs overlap, a gaze point counts for the one higher in this list, so put small ones (face) above the ones around them (body). Use the same names on every version of a post.</p>`;
    side.innerHTML = h;
  }

  window.AoiEditor = { open, isOpen: () => !!S };
})();
