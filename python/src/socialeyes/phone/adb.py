"""A thin wrapper around adb: find it, pick a phone, run commands."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parents[4]  # python/src/socialeyes/phone/adb.py -> repo root
PACKAGE = "org.socialeyes.pictogram"
APP_FILES = f"/sdcard/Android/data/{PACKAGE}/files"


class AdbError(RuntimeError):
    """adb failed or no usable phone; the message says what to do."""


def find_adb() -> Path:
    """adb from the bundled app, the project toolchain or the PATH."""
    exe = "adb.exe" if os.name == "nt" else "adb"
    candidates = [REPO / ".toolchain" / "android-sdk" / "platform-tools" / exe]
    if hasattr(sys, "_MEIPASS"):  # the packaged desktop app bundles adb
        candidates.insert(0, Path(sys._MEIPASS) / "adb" / exe)
    for c in candidates:
        if c.is_file():
            return c
    found = shutil.which("adb")
    if found:
        return Path(found)
    raise AdbError("adb was not found. Run scripts/setup-toolchain.ps1, or install Android platform-tools.")


@dataclass(frozen=True)
class Device:
    serial: str
    state: str          # device, unauthorized, offline, ...
    model: str = ""

    @property
    def ready(self) -> bool:
        return self.state == "device"


class Adb:
    def __init__(self, serial: Optional[str] = None, exe: Optional[Path] = None):
        self.exe = Path(exe) if exe else find_adb()
        self.serial = serial

    def run(self, *args: str, timeout: float = 120, check: bool = True) -> str:
        cmd = [str(self.exe), *(["-s", self.serial] if self.serial else []), *args]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                               timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired as e:
            raise AdbError(f"adb {' '.join(args[:2])} took too long; is the phone still connected?") from e
        out = (r.stdout or "") + (r.stderr or "")
        if check and r.returncode != 0:
            raise AdbError(out.strip() or f"adb {' '.join(args[:2])} failed")
        return out

    def shell(self, command: str, timeout: float = 60, check: bool = False) -> str:
        """Runs `command` in the phone's shell; returns its output (stdout and stderr)."""
        return self.run("shell", command, timeout=timeout, check=check).replace("\r\n", "\n")

    def devices(self) -> list[Device]:
        out = Adb(exe=self.exe).run("devices", "-l", timeout=20)
        found = []
        for line in out.splitlines()[1:]:
            parts = line.split()
            if len(parts) < 2 or parts[0].startswith("*"):
                continue
            model = next((p.split(":", 1)[1].replace("_", " ") for p in parts[2:] if p.startswith("model:")), "")
            found.append(Device(parts[0], parts[1], model))
        return found

    def choose(self) -> Device:
        """Selects the phone to use (the given serial, or the only one connected)."""
        devices = self.devices()
        if self.serial:
            match = [d for d in devices if d.serial == self.serial]
            if not match:
                raise AdbError(f"phone {self.serial} is not connected")
            device = match[0]
        elif not devices:
            raise AdbError("No phone found. Connect it by USB and turn on USB debugging "
                           "(Settings > Developer options).")
        elif len(devices) > 1:
            names = ", ".join(f"{d.serial} ({d.model or d.state})" for d in devices)
            raise AdbError(f"More than one phone is connected ({names}); choose one.")
        else:
            device = devices[0]
        if device.state == "unauthorized":
            raise AdbError("The phone hasn't allowed this computer yet: unlock it and tap Allow on the "
                           "'Allow USB debugging?' prompt.")
        if not device.ready:
            raise AdbError(f"The phone is connected but {device.state}; unplug it and plug it in again.")
        self.serial = device.serial
        return device
