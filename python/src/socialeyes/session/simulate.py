"""Write a realistic fake session for a compiled participant plan.

Used for tests, for developing the analysis before the app exists, and as a
reference for what the app must write (docs/EVENT_LOG.md). The simulated
participant scrolls with swipes and flings, pauses on posts, sometimes
double-taps to like, rests a finger on an image, opens comments, and answers
every procedure step.

    python -m socialeyes.session.simulate build/example P001 data/sim/P001
"""
from __future__ import annotations

import json
import math
import random
import sys
from pathlib import Path
from typing import Optional

from .io import FORMAT_VERSION, write_session

SCREEN_W, SCREEN_H, DPI = 1080, 2400, 420
DP = DPI / 160
FEED_TOP = round((24 + 56) * DP)  # status bar + app bar
TOUCH_HZ, FRAME_HZ = 120, 60
PLACEHOLDER_VIDEO_SIZE = (160, 90)

# card element heights in px (dp * density); the image height follows its aspect ratio
HEADER_H, LABEL_H, ACTIONS_H, CAPTION_H, COMMENT_H = (round(v * DP) for v in (56, 40, 48, 40, 30))


class _Sim:
    def __init__(self, manifest: dict, plan: dict, seed: int, sensors: Optional[bool]):
        self.m, self.plan = manifest, plan
        self.study = manifest["study"]
        self.rng = random.Random(f"{seed}:{plan['participant_id']}")
        self.t0 = 3_600_000_000_000 + self.rng.randrange(10**12)  # elapsed ns at session start
        self.t = self.t0
        self.events: list[dict] = []
        self.viewport: list[dict] = []
        self.touch: list[dict] = []
        self.frame = 0
        self.step_id = ""
        logging = self.study.get("logging", {})
        self.log_touches = logging.get("touches", True)
        self.log_sensors = logging.get("sensors", False) if sensors is None else sensors
        self.camera = logging.get("front_camera", {})
        self._layout()

    # ------------------------------------------------------------ helpers

    def emit(self, type_: str, t: Optional[int] = None, **fields) -> None:
        self.events.append({"t_ns": self.t if t is None else t, "type": type_, **fields})

    def wait(self, seconds: float) -> None:
        self.t += int(seconds * 1e9)

    def _sample(self, action: str, x: float, y: float, t: int, pointer: int = 0) -> None:
        if self.log_touches:
            self.touch.append({"t_ns": t, "action": action, "pointer_id": pointer, "x_px": round(x, 1),
                               "y_px": round(y, 1), "pressure": round(self.rng.uniform(0.3, 0.7), 3),
                               "size": round(self.rng.uniform(0.02, 0.05), 4), "major_px": round(self.rng.uniform(35, 60), 1),
                               "minor_px": round(self.rng.uniform(25, 45), 1), "step_id": self.step_id})

    def tap(self, x: float, y: float, hold_s: Optional[float] = None) -> None:
        hold = hold_s if hold_s is not None else self.rng.uniform(0.06, 0.12)
        n = max(1, int(hold * TOUCH_HZ))
        self._sample("down", x, y, self.t)
        for k in range(1, n):
            jitter = 1.5 * DP
            self._sample("move", x + self.rng.uniform(-jitter, jitter), y + self.rng.uniform(-jitter, jitter),
                         self.t + int(k / TOUCH_HZ * 1e9))
        self.t += int(hold * 1e9)
        self._sample("up", x, y, self.t)

    # ------------------------------------------------------------ feed layout

    def _layout(self) -> None:
        """Card positions in content coordinates (y = 0 at the top of the feed)."""
        self.cards = []
        y = 0
        for e in self.plan["feed"]:
            img = self.m["images"][e["image_id"]]
            img_h = round(SCREEN_W * img["height"] / img["width"])
            parts = {"header": (0, HEADER_H)}
            parts["image"] = (HEADER_H, HEADER_H + img_h)
            if e["label"]:
                parts["label"] = (HEADER_H + img_h - LABEL_H, HEADER_H + img_h)
            a = HEADER_H + img_h
            parts["actions"] = (a, a + ACTIONS_H)
            parts["caption"] = (a + ACTIONS_H, a + ACTIONS_H + CAPTION_H)
            end = a + ACTIONS_H + CAPTION_H
            if e["comments"]:
                parts["comments"] = (end, end + COMMENT_H * len(e["comments"]))
                end += COMMENT_H * len(e["comments"])
            self.cards.append({"post_id": e["post_id"], "role": e["role"], "top": y, "height": end, "parts": parts})
            y += end
        self.max_scroll = max(0, y - (SCREEN_H - FEED_TOP))

    def screen_rect(self, card: dict, part: str, scroll: float) -> tuple[float, float, float, float]:
        top = FEED_TOP + card["top"] - scroll
        if part == "post":
            return 0, top, SCREEN_W, top + card["height"]
        a, b = card["parts"][part]
        return 0, top + a, SCREEN_W, top + b

    def visible_cards(self, scroll: float) -> list[dict]:
        out = []
        for c in self.cards:
            _, top, _, bottom = self.screen_rect(c, "post", scroll)
            if bottom > FEED_TOP and top < SCREEN_H:
                out.append(c)
        return out

    def log_frame(self, t: int, scroll: Optional[float]) -> None:
        self.viewport.append({"t_ns": t, "frame": self.frame, "scroll_y": round(scroll or 0, 1), "post_id": "",
                              "element": "frame"})
        self.frame += 1
        if scroll is None:  # feed closed
            return
        for c in self.visible_cards(scroll):
            for part in ("post", *c["parts"]):
                L, T, R, B = self.screen_rect(c, part, scroll)
                self.viewport.append({"t_ns": t, "frame": self.frame - 1, "scroll_y": None, "post_id": c["post_id"],
                                      "element": part, "left": L, "top": round(T, 1), "right": R, "bottom": round(B, 1)})

    # ------------------------------------------------------------ feed behaviour

    def swipe(self, scroll: float) -> float:
        rng = self.rng
        dist = rng.uniform(500, 1100)
        dur = rng.uniform(0.12, 0.25)
        fling = rng.random() < 0.7
        x0, y0 = rng.uniform(400, 700), rng.uniform(1700, 2050)
        start_scroll, t_start = scroll, self.t
        n = max(2, int(dur * TOUCH_HZ))
        self._sample("down", x0, y0, t_start)
        for k in range(1, n + 1):
            f = k / n
            self._sample("move", x0 + 15 * f, y0 - dist * f, t_start + int(f * dur * 1e9))
        hold = 0.0 if fling else rng.uniform(0.15, 0.3)  # scroll: finger stops before lifting
        t_up = t_start + int((dur + hold) * 1e9)
        if hold:
            for k in range(1, int(hold * TOUCH_HZ)):
                self._sample("move", x0 + 15, y0 - dist, t_start + int((dur + k / TOUCH_HZ) * 1e9))
        self._sample("up", x0 + 15, y0 - dist, t_up)

        # content follows the finger 1:1 while dragging
        frame_dt = 1e9 / FRAME_HZ
        t = t_start
        while t <= t_start + dur * 1e9:
            f = (t - t_start) / (dur * 1e9)
            scroll = min(self.max_scroll, start_scroll + dist * f)
            self.log_frame(int(t), scroll)
            t += frame_dt
        scroll = min(self.max_scroll, start_scroll + dist)
        self.log_frame(int(t_start + dur * 1e9), scroll)
        self.t = t_up
        if fling and scroll < self.max_scroll:
            v0, tau, tt = dist / dur, 0.325, 0.0
            while True:
                tt += 1 / FRAME_HZ
                v = v0 * math.exp(-tt / tau)
                scroll = min(self.max_scroll, scroll + v / FRAME_HZ)
                self.log_frame(t_up + int(tt * 1e9), scroll)
                if v < 50 * DP or scroll >= self.max_scroll:
                    break
            self.t = t_up + int(tt * 1e9)
        return scroll

    def feed(self, step: dict) -> None:
        rng = self.rng
        feed_cfg = self.study["feed"]
        t_feed = self.t
        done_after = feed_cfg.get("done_button_after_s")
        done_t = t_feed + int(done_after * 1e9) if done_after is not None else None
        if done_t is not None:
            self.emit("done_button_shown", t=done_t)
        scroll = 0.0
        self.log_frame(self.t, scroll)
        liked: set[str] = set()
        while True:
            # the post closest to the middle of the screen
            mid = (FEED_TOP + SCREEN_H) / 2
            card = min(self.visible_cards(scroll),
                       key=lambda c: abs(sum(self.screen_rect(c, "image", scroll)[1::2]) / 2 - mid))
            L, T, R, B = self.screen_rect(card, "image", scroll)
            T, B = max(T, FEED_TOP), min(B, SCREEN_H)  # the visible part of the image
            img_on_screen = B - T > 600
            self.wait(rng.uniform(2.0, 6.0) if card["role"] == "critical" else rng.uniform(0.8, 3.0))
            r = rng.random()
            if img_on_screen and r < 0.15 and card["post_id"] not in liked:
                x, y = rng.uniform(L + 150, R - 150), rng.uniform(T + 150, B - 150)
                self.tap(x, y)
                self.wait(rng.uniform(0.08, 0.15))
                self.tap(x + rng.uniform(-10, 10), y + rng.uniform(-10, 10))
                self.emit("like", post_id=card["post_id"], liked=True, via="double_tap")
                liked.add(card["post_id"])
            elif img_on_screen and r < 0.30:
                # finger resting on the lower half of the image (e.g. holding the phone)
                self.tap(rng.uniform(L + 100, R - 100), rng.uniform((T + B) / 2, B - 50), hold_s=rng.uniform(1.0, 2.5))
            elif r < 0.36 and "comments" in card["parts"]:
                cL, cT, cR, cB = self.screen_rect(card, "comments", scroll)
                if cT >= FEED_TOP and cB <= SCREEN_H:
                    self.tap(rng.uniform(100, 900), (cT + cB) / 2)
                    self.emit("comments_open", post_id=card["post_id"])
                    self.wait(rng.uniform(2.0, 4.0))
                    self.emit("comments_close", post_id=card["post_id"])
            elif r < 0.40:
                hL, hT, hR, hB = self.screen_rect(card, "header", scroll)
                if hT >= FEED_TOP:
                    self.tap(150, (hT + hB) / 2)
                    self.emit("profile_tap", post_id=card["post_id"], target="handle")
            if scroll >= self.max_scroll:
                self.wait(rng.uniform(0.3, 1.0))
                break
            self.wait(rng.uniform(0.1, 0.4))
            scroll = self.swipe(scroll)
        if done_t is not None:
            self.t = max(self.t, done_t + int(rng.uniform(0.5, 2.0) * 1e9))
        self.tap(SCREEN_W / 2, SCREEN_H - 100)
        self.log_frame(self.t, None)
        self.emit("step_end", step_id=step["id"], reason="done_button")

    # ------------------------------------------------------------ other steps

    def answer(self, step_id: str, item: dict, trial: Optional[int] = None) -> None:
        rng = self.rng
        t_item = self.t
        extra = {} if trial is None else {"trial": trial}
        self.wait(rng.uniform(1.0, 3.5))
        kind = item["kind"]
        if kind == "vas":
            x0, x1, y = 540, rng.uniform(150, 930), 1300
            n = int(0.4 * TOUCH_HZ)
            self._sample("down", x0, y, self.t)
            for k in range(1, n + 1):
                x = x0 + (x1 - x0) * k / n
                self._sample("move", x, y, self.t + int(k / TOUCH_HZ * 1e9))
                if k % 12 == 0:
                    self.emit("response_change", t=self.t + int(k / TOUCH_HZ * 1e9), step_id=step_id,
                              item_id=item["id"], value=round((x - 108) / 864, 3), **extra)
            self.t += int(0.4 * 1e9)
            self._sample("up", x1, y, self.t)
            value = round(min(1, max(0, (x1 - 108) / 864)), 3)
        elif kind == "likert":
            value = rng.randint(1, item["points"])
            self.tap(108 + (value - 0.5) * 864 / item["points"], 1400)
        elif kind == "choice":
            value = rng.choice(item["options"])
            self.tap(540, 1000 + 150 * item["options"].index(value))
        elif kind == "number":
            value = rng.randint(18, 40)
            self.tap(540, 1200)
        else:
            value = "placeholder answer"
            self.tap(540, 1200)
        self.emit("response", step_id=step_id, item_id=item["id"], value=value,
                  rt_ms=round((self.t - t_item) / 1e6), **extra)

    @property
    def recording_camera(self) -> bool:
        return bool(self.camera.get("enabled"))

    def run(self) -> tuple:
        rng, m = self.rng, self.m
        self.emit("thermal", status="none")
        self.emit("neon", status="connected")
        self.emit("neon", status="recording_start", recording_id=f"sim-{self.plan['participant_id']}")
        self.emit("brightness", value=0.8)
        self.emit("orientation", rotation=0)
        for step in self.study["procedure"]:
            self.step_id = step["id"]
            self.emit("step_start", step_id=step["id"], step_type=step["type"])
            kind = step["type"]
            if kind == "feed":
                self.feed(step)
                continue
            if kind == "instructions":
                self.wait(rng.uniform(4, 8))
                self.tap(540, 2250)
            elif kind == "marker_calibration":
                self.wait(step.get("duration_s", 4.0))
            elif kind == "camera_check":
                face_s = step.get("min_face_s", 3.0) + rng.uniform(0.5, 3.0)
                self.wait(face_s)
                self.emit("camera_check", step_id=step["id"],
                          result="ok", face_s=round(face_s, 2))
                self.tap(540, 2250)
            elif kind == "validation":
                for i, (px, py) in enumerate(m["validation_points"][step["id"]]):
                    x, y = px * SCREEN_W, py * SCREEN_H
                    self.emit("validation_target", step_id=step["id"], index=i, x_px=x, y_px=y)
                    self.wait(rng.uniform(0.6, 1.2))
                    tx, ty = x + rng.gauss(0, 15), y + rng.gauss(0, 15)
                    self.tap(tx, ty)
                    self.emit("validation_tap", step_id=step["id"], index=i, x_px=round(tx, 1), y_px=round(ty, 1))
            elif kind == "questionnaire":
                for item in step["items"]:
                    self.answer(step["id"], item)
                self.wait(rng.uniform(0.3, 1.0))
                self.tap(540, 2250)
            elif kind in ("image_rating", "recognition"):
                for i, trial in enumerate(self.plan["steps"][step["id"]]["trials"]):
                    self.emit("trial_start", step_id=step["id"], trial=i, image_id=trial["image_id"])
                    items = step.get("items") or [{"id": "old_new", "kind": "choice", "options": ["old", "new"]}]
                    if kind == "recognition" and step.get("confidence", True):
                        items = items + [{"id": "confidence", "kind": "likert", "points": 4}]
                    for item in items:
                        self.answer(step["id"], item, trial=i)
            elif kind == "end":
                self.wait(2.0)
            self.emit("step_end", step_id=step["id"], reason="continue")
        self.emit("neon", status="recording_stop", recording_id=f"sim-{self.plan['participant_id']}")
        t_end = self.t + int(0.5e9)
        self._background_events(t_end)
        meta = self._meta(t_end)
        sensors = self._sensors(t_end) if self.log_sensors else None
        camera = self._camera_frames() if self.recording_camera else None
        return meta, self.events, self.viewport, self.touch if self.log_touches else None, sensors, camera

    def _camera_frames(self) -> list[dict]:
        """Frame timestamps for the recorded steps; a new segment per start and every segment_s."""
        fps = self.camera.get("fps", 30)
        steps_cfg = self.camera.get("steps", ["feed"])
        interval = 1e9 / fps
        starts = {e["step_id"]: e["t_ns"] for e in self.events if e["type"] == "step_start"}
        ends = {e["step_id"]: e["t_ns"] for e in self.events if e["type"] == "step_end"}
        rows, segment = [], 0
        for step_id, t_start in starts.items():
            if steps_cfg != "all" and step_id not in steps_cfg:
                continue
            t = t_start + int(self.rng.uniform(0.3, 0.5) * 1e9)  # camera start-up delay
            t_stop = ends.get(step_id, t)
            seg_start, frame = t, 0
            self.emit("camera", t=t, status="started", file=f"camera/front_{segment:03d}.mp4")
            while t < t_stop:
                if t - seg_start >= self.camera.get("segment_s", 60) * 1e9:
                    segment, frame, seg_start = segment + 1, 0, t
                    self.emit("camera", t=t, status="segment", file=f"camera/front_{segment:03d}.mp4")
                if self.rng.random() > 0.002:  # a few dropped frames
                    rows.append({"segment": segment, "frame": frame, "t_ns": int(t),
                                 "exposure_ns": 16_000_000})
                    frame += 1
                t += interval
            self.emit("camera", t=t_stop, status="stopped")
            segment += 1
        return rows

    def _background_events(self, t_end: int) -> None:
        sync = self.m["sync_code"]
        bits, bit_ns = sync["bits"], sync["bit_ms"] * 1_000_000
        last = None
        for k in range((t_end - self.t0) // bit_ns):
            level = bits[k % len(bits)]
            if level != last:
                self.emit("sync_patch", t=self.t0 + k * bit_ns, level=level)
                last = level
        for k in range(int((t_end - self.t0) / 60e9) + 1):
            self.emit("battery", t=self.t0 + int(k * 60e9), level=round(0.9 - 0.01 * k, 2), temp_c=31.0)
        for _ in range(2):
            self.emit("jank", t=self.rng.randrange(self.t0, t_end), frames_dropped=self.rng.randint(1, 3),
                      longest_frame_ms=round(self.rng.uniform(25, 60), 1))

    def _meta(self, t_end: int) -> dict:
        offset = 120_000_000_000  # elapsed - uptime: the phone slept before the session
        return {
            "format": "socialeyes-session",
            "format_version": FORMAT_VERSION,
            "study_id": self.plan["study_id"],
            "study_version": self.plan["study_version"],
            "participant_id": self.plan["participant_id"],
            "session_uid": f"{self.plan['participant_id']}-sim",
            "app_version": "simulated",
            "started_wall": "2026-10-02T10:00:00.000+00:00",
            "clock": {"elapsed_ns": self.t0, "uptime_ns": self.t0 - offset, "wall_ms": 1790000000000},
            "device": {"manufacturer": "Simulated", "model": "Phone", "android_sdk": 34,
                       "screen_width_px": SCREEN_W, "screen_height_px": SCREEN_H, "density_dpi": DPI,
                       "xdpi": 428.6, "ydpi": 427.3, "refresh_hz": float(FRAME_HZ), "font_scale": 1.0},
            "feed_area": [0, FEED_TOP, SCREEN_W, SCREEN_H],
            "logging": {**self.study.get("logging", {}), "touches": self.log_touches, "sensors": self.log_sensors},
            **({"camera": {"lens": "front", **dict(zip(("width", "height"), PLACEHOLDER_VIDEO_SIZE)),
                           "fps": self.camera.get("fps", 30), "timestamp_source": "realtime"}}
               if self.recording_camera else {}),
            "end": {"reason": "completed",
                    "clock": {"elapsed_ns": t_end, "uptime_ns": t_end - offset,
                              "wall_ms": 1790000000000 + (t_end - self.t0) // 1_000_000}},
        }

    def _sensors(self, t_end: int) -> list[dict]:
        hz = self.study.get("logging", {}).get("sensor_hz", 50)
        rows, g = [], self.rng.gauss
        for k in range(int((t_end - self.t0) / 1e9 * hz)):
            t = self.t0 + int(k / hz * 1e9)
            rows.append({"t_ns": t, "sensor": "accel", "x": round(g(0, 0.2), 3), "y": round(6.9 + g(0, 0.2), 3),
                         "z": round(6.9 + g(0, 0.2), 3)})
            rows.append({"t_ns": t, "sensor": "gyro", "x": round(g(0, 0.02), 4), "y": round(g(0, 0.02), 4),
                         "z": round(g(0, 0.02), 4)})
            rows.append({"t_ns": t, "sensor": "rotation", "x": 0.383, "y": 0.0, "z": 0.0, "w": 0.924})
        return rows


def simulate_session(build_dir: Path | str, participant_id: str, out_dir: Path | str, seed: int = 0,
                     sensors: Optional[bool] = None) -> Path:
    """Write a simulated session for ``participant_id`` of a compiled study to ``out_dir``.

    If the study enables the front camera, the video
    segments are tiny grey placeholders with the right number of frames.
    """
    build = Path(build_dir)
    manifest = json.loads((build / "study.json").read_text(encoding="utf-8"))
    plan = json.loads((build / "plans" / f"{participant_id}.json").read_text(encoding="utf-8"))
    meta, events, viewport, touch, sensor_rows, camera = _Sim(manifest, plan, seed, sensors).run()
    out = Path(out_dir)
    write_session(out, meta, events, viewport, touch, sensor_rows, camera)
    if camera:
        _write_placeholder_videos(out, camera, meta["camera"]["fps"])
    return out


def _write_placeholder_videos(out: Path, frames: list[dict], fps: int) -> None:
    import cv2
    import numpy as np

    (out / "camera").mkdir(exist_ok=True)
    counts: dict[int, int] = {}
    for f in frames:
        counts[f["segment"]] = counts.get(f["segment"], 0) + 1
    w, h = PLACEHOLDER_VIDEO_SIZE
    for segment, n in counts.items():
        writer = cv2.VideoWriter(str(out / "camera" / f"front_{segment:03d}.mp4"),
                                 cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
        for k in range(n):
            writer.write(np.full((h, w, 3), 64 + (k % 64), np.uint8))
        writer.release()


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit("usage: python -m socialeyes.session.simulate BUILD_DIR PARTICIPANT_ID OUT_DIR")
    print(simulate_session(*sys.argv[1:]))
