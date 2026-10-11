"""Display calibration (socialeyes.gaze.display_calibration) against a simulated phone and scene camera.

The simulated camera sees the phone in a dim room. Auto exposure meters the whole picture, so the
bright screen is overexposed and its light blooms into the tags' black cells; very short
exposures are dark and noisy. The calibration should find a setting in between."""
from __future__ import annotations

import cv2
import numpy as np

from socialeyes.gaze.display_calibration import (Layout, Measure, calibrate, choose, measure, settings,
                                                 summary)
from socialeyes.gaze.tags import TagDetector
from socialeyes.markers import tag_image

K = np.array([[885.0, 0, 800], [0, 885.0, 600], [0, 0, 1]])
W, H, XDPI, YDPI = 1080, 2400, 397.6, 395.8
TAG_PX = 12 / 25.4 * XDPI * 1.5            # whole 12-cell image of a 12 mm tag
EDGE = 30


def _rect(x, y):
    return [x, y, x + TAG_PX, y + TAG_PX]


TAGS = {0: _rect(EDGE, EDGE), 1: _rect(W - EDGE - TAG_PX, EDGE),
        2: _rect(W - EDGE - TAG_PX, H - EDGE - TAG_PX), 3: _rect(EDGE, H - EDGE - TAG_PX)}
IMAGE = [0, 500, W, 1850]
STATE = {"screen": {"width_px": W, "height_px": H, "xdpi": XDPI, "ydpi": YDPI},
         "tags": {str(k): v for k, v in TAGS.items()}, "image": IMAGE,
         "camera": {"ae_mode": {"current": "auto"}, "man_exp": {"current": 8000, "min": 100, "max": 30000}},
         "calibration": {"K": K.ravel().tolist(), "dist": [0] * 8}}


def screen_luminance() -> np.ndarray:
    """What the screen emits (0-1): white, the tags, and a textured post image."""
    L = np.ones((H, W), np.float32)
    for i, (x0, y0, x1, y1) in TAGS.items():
        img = cv2.resize(tag_image(i, px_per_cell=20), (round(x1 - x0), round(y1 - y0)), interpolation=cv2.INTER_NEAREST)
        L[round(y0):round(y0) + img.shape[0], round(x0):round(x0) + img.shape[1]] = img / 255.0
    rng = np.random.default_rng(1)
    tex = cv2.resize(rng.uniform(0.35, 0.95, (27, 22)).astype(np.float32), (IMAGE[2] - IMAGE[0], IMAGE[3] - IMAGE[1]))
    L[IMAGE[1]:IMAGE[3], IMAGE[0]:IMAGE[2]] = tex
    return L


class FakePhone:
    """The app (brightness) and Companion's scene camera (exposure) as one simulated device."""

    def __init__(self):
        self.brightness, self.camera, self.t = 1.0, {"ae_mode": "auto"}, 0
        self.L = screen_luminance()
        R = cv2.Rodrigues(np.array([0.35, 0.05, 0.0]))[0]
        t = np.array([-34.0, -70.0, 340.0])
        S = np.diag([25.4 / XDPI, 25.4 / YDPI, 1.0])
        self.M = K @ np.column_stack([R[:, 0], R[:, 1], t]) @ S
        self.rng = np.random.default_rng(0)
        self.done_with = None

    # App
    def state(self):
        return STATE

    def apply(self, brightness, camera):
        self.brightness, self.camera = brightness, dict(camera)
        self.t += 10**9
        return self.t

    def done(self, brightness, camera, summary):
        self.done_with = (brightness, camera)

    # Scene
    def frames_after(self, t_unix_ns, n, timeout_s):
        return [self.render() for _ in range(n)]

    def render(self) -> np.ndarray:
        room = 0.15                                                  # the room, relative to a full-white screen
        screen = cv2.warpPerspective(self.L * self.brightness + 0.01, self.M, (1600, 1200), flags=cv2.INTER_AREA,
                                     borderValue=-1)
        lin = np.where(screen < 0, room, screen).astype(np.float32)
        if self.camera["ae_mode"] == "auto":
            gain = 110 / float(np.mean(lin))                         # meters the whole picture
        else:
            gain = 255 / 0.25 * int(self.camera["man_exp"]) / 8000   # 8 ms puts 0.25 at full white
        sig = lin * gain
        sig = sig + 0.15 * cv2.GaussianBlur(sig, (0, 0), 3)          # bloom: bright light spills over
        sig = cv2.GaussianBlur(sig, (0, 0), 0.7)
        sig = sig + self.rng.normal(0, 1, sig.shape) * (2 + np.sqrt(np.maximum(sig, 0)) * 0.6)
        return np.clip(sig, 0, 255).astype(np.uint8)


def test_settings_skip_exposures_outside_companions_range():
    plan = settings(STATE, levels=(1.0, 0.5, 0.2), exposures=("auto", 50, 2000, 40000), min_brightness=0.25)
    assert plan == [(1.0, {"ae_mode": "auto"}), (1.0, {"ae_mode": "manual", "man_exp": "2000"}),
                    (0.5, {"ae_mode": "auto"}), (0.5, {"ae_mode": "manual", "man_exp": "2000"})]


def test_choose_prefers_tags_then_less_blown_out_then_usable_image_then_familiar_brightness():
    a = Measure(1.0, {"ae_mode": "auto"}, 8, tags_read=0.5, blown_out=0.8, image_level=255)
    b = Measure(0.4, {"ae_mode": "manual", "man_exp": "2000"}, 8, tags_read=1.0, margin=40, blown_out=0.3, image_level=240)
    c = Measure(0.55, {"ae_mode": "manual", "man_exp": "1000"}, 8, tags_read=0.95, margin=30, blown_out=0.02, image_level=120)
    d = Measure(0.75, {"ae_mode": "manual", "man_exp": "1000"}, 8, tags_read=0.95, margin=20, blown_out=0.05, image_level=150)
    e = Measure(1.0, {"ae_mode": "manual", "man_exp": "500"}, 8, tags_read=0.95, margin=20, blown_out=0.0, image_level=40)
    assert choose([a, b, c, d, e]) is d       # e: image too dark; c and d: d is brighter
    assert choose([a, b, c, d, e], target_brightness=0.5) is c   # nearest the phone's own brightness
    assert choose([Measure(1.0, {}, 8, tags_read=0.0)]) is None


def test_auto_exposure_blows_out_the_screen():
    phone = FakePhone()
    layout = Layout.from_state(STATE)
    det = TagDetector()
    phone.apply(0.4, {"ae_mode": "manual", "man_exp": "2000"})
    darker, H = measure(phone.frames_after(0, 3, 1), layout, det, 0.4, phone.camera)
    phone.apply(1.0, {"ae_mode": "auto"})
    auto, _ = measure(phone.frames_after(0, 3, 1), layout, det, 1.0, phone.camera, prior_H=H)
    assert darker.tags_read == 1.0 and darker.blown_out < 0.05
    # the tags still read (white saturates, black stays black: margins even rise), but the image is lost
    assert auto.blown_out > 0.5


def test_calibration_finds_a_setting_that_reads_the_tags_without_blowing_out_the_screen():
    phone = FakePhone()
    lines = []
    plan = settings(STATE, levels=(1.0, 0.55, 0.3), exposures=("auto", 500, 2000, 8000))
    best, measures = calibrate(phone, phone, Layout.from_state(STATE), plan, frames=3, log=lines.append)
    assert best is not None
    assert best.tags_read >= 0.9 and best.blown_out < 0.1
    assert (best.brightness, best.camera.get("ae_mode")) != (1.0, "auto")
    assert len(measures) == len(plan) + 3 and any("measuring the best again" in l for l in lines)
    s = summary(best, measures)
    assert s["best"]["brightness"] == best.brightness and s["tried"] == len(measures)


def test_calibrate_display_command_end_to_end(tmp_path, monkeypatch):
    """The laptop command against an HTTP server that answers like the app's step (neon/ControlServer.kt,
    ui/DisplayCalibration.kt), with the simulated phone behind it."""
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from socialeyes import cli
    from socialeyes.gaze import display_calibration as dc

    phone = FakePhone()
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, obj):
            data = json.dumps(obj).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            requests.append(("GET", self.path, None))
            self._send({**STATE, "session_uid": "T01-x", "step_id": "dcal", "system_brightness": 0.6})

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(("POST", self.path, body))
            if self.path == "/apply":
                b = phone.brightness if body["brightness"] is None else body["brightness"]
                self._send({"applied_unix_ns": phone.apply(b, body["camera"] or phone.camera)})
            else:
                phone.done(body["brightness"], body["camera"], body["summary"])
                self._send({"ok": True})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    class Scene:
        def __init__(self, host, port):
            pass

        def frames_after(self, t, n, timeout_s):
            return phone.frames_after(t, n, timeout_s)

        def close(self):
            pass

    monkeypatch.setattr(dc, "NeonScene", Scene)
    try:
        out = tmp_path / "cal.json"
        rc = cli.main(["calibrate-display", "127.0.0.1", "--app-port", str(server.server_port),
                       "--brightness", "1.0,0.55", "--exposures", "auto,2000", "--frames", "2", "-o", str(out)])
        assert rc == 0
        brightness, camera = phone.done_with
        assert camera == {"ae_mode": "manual", "man_exp": "2000"} and brightness in (1.0, 0.55)
        saved = json.loads(out.read_text())
        assert saved["best"]["brightness"] == brightness and saved["state"]["step_id"] == "dcal"
        assert [r[1] for r in requests if r[0] == "POST"][-1] == "/done"

        assert cli.main(["calibrate-display", "127.0.0.1", "--app-port", str(server.server_port), "--check"]) == 0
        assert requests[-1][2] == {"brightness": None, "camera": {}}
    finally:
        server.shutdown()
