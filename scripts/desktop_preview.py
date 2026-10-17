"""Development helper: the desktop app's page in an ordinary browser, for testing and screenshots.

    python scripts/desktop_preview.py [--port 8765]

Serves builder/index.html on http://127.0.0.1:<port>/ with a stand-in for pywebview's bridge:
each window.pywebview.api.<name>(...) call goes to the real socialeyes.desktop.app.Api over HTTP,
so every tab works as in the app (with the phone, folders and data of this computer). Folder
dialogs can't open from a browser: pick_folder returns localStorage "previewPick" if set, else
asks with a prompt. ``?do=pick:<folder>;click:<data-action>;wait:<ms>`` steps through the page
after it loads, for screenshots with a headless browser. Listens on 127.0.0.1 only; not for participants or other people's machines.
"""
from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "python" / "src"))
from socialeyes.desktop.app import Api, builder_page  # noqa: E402

SHIM = """<script>
window.pywebview = {api: new Proxy({}, {get: (_, name) => async (...args) => {
  if (name === "pick_folder") {
    let p = null;
    try { p = localStorage.getItem("previewPick"); } catch (e) {}
    return {ok: p || window.prompt("Folder (preview: type a path)", args[0] || "") || null};
  }
  const r = await fetch("/api/" + name, {method: "POST", body: JSON.stringify(args)});
  return r.json();
}})};
// ?do=pick:<folder>;click:<data-action>;wait:<ms>;... steps through the page after it loads,
// for headless screenshots (e.g. chrome --headless --screenshot --virtual-time-budget=20000)
window.addEventListener("load", async () => {
  const steps = new URLSearchParams(location.search).get("do");
  if (!steps) return;
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  await sleep(500);
  for (const step of steps.split(";")) {
    const i = step.indexOf(":"), kind = step.slice(0, i), arg = step.slice(i + 1);
    if (kind === "pick") localStorage.setItem("previewPick", arg);
    if (kind === "wait") await sleep(Number(arg));
    if (kind === "click") {
      const el = [...document.querySelectorAll("[data-action]")].find((e) => e.dataset.action === arg);
      if (el) el.click(); else console.warn("preview: nothing to click for", arg);
      await sleep(800);
    }
  }
});
</script>"""


class Handler(BaseHTTPRequestHandler):
    api = Api()

    def _send(self, code: int, body: bytes, kind: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path.split("?")[0] not in ("/", "/index.html"):
            return self._send(404, b"not found", "text/plain")
        page = builder_page().read_text(encoding="utf-8").replace("<head>", "<head>" + SHIM, 1)
        self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")

    def do_POST(self):  # noqa: N802
        name = self.path.removeprefix("/api/")
        method = getattr(self.api, name, None)
        if name.startswith("_") or not callable(method):
            return self._send(404, b'{"error": "no such call"}', "application/json")
        args = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"[]")
        self._send(200, json.dumps(method(*args)).encode("utf-8"), "application/json")

    def log_message(self, fmt, *args):
        sys.stderr.write("  " + fmt % args + "\n")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=8765)
    port = ap.parse_args().port
    print(f"Desktop app preview: http://127.0.0.1:{port}/  (Ctrl+C to stop)", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
