"""Reading session folders written by the app (format: docs/EVENT_LOG.md)."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pandas as pd

FORMAT_VERSION = 1
TOUCH_COLUMNS = ["t_ns", "action", "pointer_id", "x_px", "y_px", "pressure", "size", "major_px", "minor_px", "step_id"]
VIEWPORT_COLUMNS = ["t_ns", "frame", "scroll_y", "post_id", "element", "left", "top", "right", "bottom"]
SENSOR_COLUMNS = ["t_ns", "sensor", "x", "y", "z", "w"]
CAMERA_COLUMNS = ["segment", "frame", "t_ns", "exposure_ns"]
ELEMENTS = ("frame", "post", "header", "image", "label", "actions", "caption", "comments", "sheet", "sheet_input",
            "story", "reel")  # story / reel: an open story image or the reel video; post_id holds its id
# comment n of the post in the comments sheet, or the participant's own comment pK
SHEET_COMMENT = re.compile(r"sheet_comment_[A-Za-z0-9_-]+")
TOUCH_ACTIONS = ("down", "move", "up", "cancel")


class SessionFormatError(ValueError):
    pass


@dataclass
class Session:
    path: Path
    meta: dict
    events: pd.DataFrame  # t_ns, type, then one column per event field
    viewport: pd.DataFrame
    touch: Optional[pd.DataFrame]
    sensors: Optional[pd.DataFrame]
    camera_frames: Optional[pd.DataFrame] = None  # one row per front-camera video frame

    @property
    def participant_id(self) -> str:
        return self.meta["participant_id"]

    @property
    def device(self) -> dict:
        return self.meta["device"]

    @property
    def px_per_dp(self) -> float:
        return self.device["density_dpi"] / 160.0

    @property
    def px_per_mm(self) -> float:
        return self.device.get("xdpi", self.device["density_dpi"]) / 25.4

    @property
    def feed_area(self) -> tuple[float, float, float, float]:
        """Screen rectangle the feed scrolls in (whole screen if not recorded)."""
        area = self.meta.get("feed_area")
        if area:
            return tuple(float(v) for v in area)
        return 0.0, 0.0, float(self.device["screen_width_px"]), float(self.device["screen_height_px"])

    @property
    def start_ns(self) -> int:
        return int(self.meta["clock"]["elapsed_ns"])

    @property
    def end_ns(self) -> int:
        end = self.meta.get("end")
        if end and end.get("clock"):
            return int(end["clock"]["elapsed_ns"])
        times = [int(self.events["t_ns"].max())] if len(self.events) else [self.start_ns]
        for df in (self.viewport, self.touch, self.sensors, self.camera_frames):
            if df is not None and len(df):
                times.append(int(df["t_ns"].max()))
        return max(times)

    def events_of(self, *types: str) -> pd.DataFrame:
        return self.events[self.events["type"].isin(types)].dropna(axis=1, how="all")

    def step_windows(self) -> pd.DataFrame:
        """step_id, step_type, start_ns, end_ns (end = session end if the step never ended)."""
        starts = self.events_of("step_start")
        ends = self.events_of("step_end")
        rows = []
        for _, s in starts.iterrows():
            later = ends[(ends["step_id"] == s["step_id"]) & (ends["t_ns"] >= s["t_ns"])] if len(ends) else ends
            end = int(later["t_ns"].iloc[0]) if len(later) else self.end_ns
            rows.append({"step_id": s["step_id"], "step_type": s["step_type"], "start_ns": int(s["t_ns"]), "end_ns": end})
        return pd.DataFrame(rows, columns=["step_id", "step_type", "start_ns", "end_ns"])

    def feed_window(self) -> tuple[int, int]:
        steps = self.step_windows()
        feed = steps[steps["step_type"] == "feed"]
        if len(feed):
            return int(feed["start_ns"].iloc[0]), int(feed["end_ns"].iloc[0])
        if len(self.viewport):
            return int(self.viewport["t_ns"].min()), int(self.viewport["t_ns"].max())
        return self.start_ns, self.start_ns


def _read_csv(path: Path, columns: list[str], dtypes: dict) -> pd.DataFrame:
    try:
        df = pd.read_csv(path, dtype=dtypes, keep_default_na=False, na_values={c: [""] for c in columns
                                                                              if dtypes.get(c) not in (str,)})
    except (pd.errors.ParserError, ValueError) as e:
        raise SessionFormatError(f"{path.name}: {e}") from e
    missing = [c for c in columns if c not in df.columns]
    if missing:
        raise SessionFormatError(f"{path.name}: missing column(s) {missing}")
    return df


def _check_values(df: pd.DataFrame, column: str, allowed, name: str, pattern: Optional[re.Pattern] = None) -> None:
    bad = sorted(v for v in set(df[column]) - set(allowed) if not (pattern and pattern.fullmatch(str(v))))
    if bad:
        raise SessionFormatError(f"{name}: unknown {column} value(s) {bad[:5]}; allowed: {list(allowed)}")


def load_session(path: Path | str) -> Session:
    path = Path(path)
    meta_path = path / "session.json"
    if not meta_path.is_file():
        raise SessionFormatError(f"{path}: no session.json (is this a session folder?)")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if meta.get("format") != "socialeyes-session":
        raise SessionFormatError("session.json: format must be 'socialeyes-session'")
    if meta.get("format_version") != FORMAT_VERSION:
        raise SessionFormatError(f"session.json: format_version {meta.get('format_version')} is not supported "
                                 f"(this version reads {FORMAT_VERSION})")
    for key in ("participant_id", "clock", "device"):
        if key not in meta:
            raise SessionFormatError(f"session.json: missing {key!r}")

    records = []
    events_path = path / "events.jsonl"
    if events_path.is_file():
        with events_path.open(encoding="utf-8") as fh:
            for n, line in enumerate(fh, 1):
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError as e:
                    raise SessionFormatError(f"events.jsonl line {n}: {e}") from e
                if "t_ns" not in rec or "type" not in rec:
                    raise SessionFormatError(f"events.jsonl line {n}: every event needs t_ns and type")
                records.append(rec)
    events = pd.DataFrame.from_records(records) if records else pd.DataFrame(columns=["t_ns", "type"])
    events["t_ns"] = events["t_ns"].astype("int64")
    events = events.sort_values("t_ns", kind="stable").reset_index(drop=True)

    vp_path = path / "viewport.csv"
    if vp_path.is_file():
        viewport = _read_csv(vp_path, VIEWPORT_COLUMNS, {"t_ns": "int64", "post_id": str, "element": str})
        _check_values(viewport, "element", ELEMENTS, "viewport.csv", SHEET_COMMENT)
    else:
        viewport = pd.DataFrame(columns=VIEWPORT_COLUMNS).astype({"t_ns": "int64"})

    logging = meta.get("logging", {})
    touch = None
    if (path / "touch.csv").is_file():
        touch = _read_csv(path / "touch.csv", TOUCH_COLUMNS,
                          {"t_ns": "int64", "action": str, "pointer_id": "int64", "step_id": str})
        _check_values(touch, "action", TOUCH_ACTIONS, "touch.csv")
        touch = touch.sort_values("t_ns", kind="stable").reset_index(drop=True)
    elif logging.get("touches"):
        raise SessionFormatError("logging.touches is on but touch.csv is missing")

    sensors = None
    if (path / "sensors.csv").is_file():
        sensors = _read_csv(path / "sensors.csv", SENSOR_COLUMNS, {"t_ns": "int64", "sensor": str})
        _check_values(sensors, "sensor", ("accel", "gyro", "rotation"), "sensors.csv")

    camera_frames = None
    if (path / "camera_frames.csv").is_file():
        camera_frames = _read_csv(path / "camera_frames.csv", CAMERA_COLUMNS,
                                  {"segment": "int64", "frame": "int64", "t_ns": "int64"})
    elif logging.get("front_camera", {}).get("enabled"):
        raise SessionFormatError("logging.front_camera is enabled but camera_frames.csv is missing")

    return Session(path, meta, events, viewport, touch, sensors, camera_frames)


# ---------------------------------------------------------------- writing (simulator, tests)


def write_session(path: Path, meta: dict, events: list[dict], viewport: list[dict],
                  touch: Optional[list[dict]] = None, sensors: Optional[list[dict]] = None,
                  camera_frames: Optional[list[dict]] = None) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "session.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    events = sorted(events, key=lambda e: e["t_ns"])
    with (path / "events.jsonl").open("w", encoding="utf-8") as fh:
        for e in events:
            fh.write(json.dumps(e, ensure_ascii=False) + "\n")
    _write_rows(path / "viewport.csv", VIEWPORT_COLUMNS, viewport)
    if touch is not None:
        _write_rows(path / "touch.csv", TOUCH_COLUMNS, touch)
    if sensors is not None:
        _write_rows(path / "sensors.csv", SENSOR_COLUMNS, sensors)
    if camera_frames is not None:
        _write_rows(path / "camera_frames.csv", CAMERA_COLUMNS, camera_frames)


def _write_rows(path: Path, columns: list[str], rows: list[dict]) -> None:
    df = pd.DataFrame.from_records(rows, columns=columns)
    for c in df.columns:
        if df[c].dtype == float:
            df[c] = df[c].map(lambda v: "" if pd.isna(v) else (int(v) if float(v).is_integer() else round(v, 3)))
    df.to_csv(path, index=False)
