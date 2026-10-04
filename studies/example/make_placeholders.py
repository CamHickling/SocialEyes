"""Regenerate the placeholder images, avatars and AOI files of the example study.

    python studies/example/make_placeholders.py

Critical posts get a stylised figure in two versions ("original" and a
"retouched" version with a narrower waist and smoother colours) plus an AOI file
(face, waist, legs). Fillers are plain scenes. Replace all of these with real,
rights-cleared images for an actual study.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).parent
W, H = 540, 675  # 4:5 portrait, the usual feed aspect ratio
SW, SH = 540, 960  # 9:16, stories

SKIN = [(224, 172, 140), (198, 140, 105), (141, 96, 70), (241, 194, 160)]
CLOTHES = [(46, 94, 170), (190, 60, 70), (40, 140, 110), (120, 80, 160), (220, 150, 40)]
BACKGROUNDS = [(232, 226, 214), (214, 228, 236), (236, 222, 226), (222, 234, 220)]


def figure(seed: int, retouched: bool) -> tuple[Image.Image, dict]:
    rng = random.Random(seed)
    skin, cloth, bg = rng.choice(SKIN), rng.choice(CLOTHES), rng.choice(BACKGROUNDS)
    im = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(im)
    cx = W // 2 + rng.randint(-30, 30)
    waist = 62 if retouched else 88  # half-width of the waist
    # head, torso (shoulders -> waist -> hips), legs
    head = (cx - 48, 70, cx + 48, 180)
    torso = [(cx - 105, 210), (cx + 105, 210), (cx + waist, 380), (cx + 100, 450), (cx - 100, 450), (cx - waist, 380)]
    legs = (cx - 95, 450, cx + 95, 640)
    d.rectangle((cx - 18, 175, cx + 18, 215), fill=skin)
    d.ellipse(head, fill=skin)
    d.polygon(torso, fill=cloth)
    d.rectangle(legs, fill=tuple(int(c * 0.6) for c in cloth))
    d.line((cx, 455, cx, 640), fill=bg, width=10)
    if retouched:  # "smoothed" look: a soft highlight
        d.ellipse((cx - 30, 95, cx - 5, 120), fill=tuple(min(255, c + 25) for c in skin))
    aois = {
        "width": W,
        "height": H,
        "aois": [
            {"name": "face", "rect": list(head)},
            {"name": "waist", "polygon": [[cx - waist - 20, 330], [cx + waist + 20, 330],
                                          [cx + waist + 20, 420], [cx - waist - 20, 420]]},
            {"name": "legs", "rect": list(legs)},
        ],
    }
    return im, aois


def scene(seed: int) -> Image.Image:
    rng = random.Random(seed)
    sky = (rng.randint(120, 200), rng.randint(170, 220), rng.randint(210, 250))
    ground = (rng.randint(60, 140), rng.randint(110, 170), rng.randint(50, 100))
    im = Image.new("RGB", (W, H), sky)
    d = ImageDraw.Draw(im)
    horizon = rng.randint(380, 480)
    d.rectangle((0, horizon, W, H), fill=ground)
    r = rng.randint(30, 60)
    sx, sy = rng.randint(60, W - 60), rng.randint(60, 200)
    d.ellipse((sx - r, sy - r, sx + r, sy + r), fill=(250, 220, 120))
    for _ in range(rng.randint(2, 5)):
        x, h = rng.randint(0, W), rng.randint(60, 200)
        d.polygon([(x - 70, horizon), (x, horizon - h), (x + 70, horizon)], fill=tuple(c - 30 for c in ground))
    return im


def story(seed: int) -> Image.Image:
    """A 9:16 story: a figure or a scene on a vertical gradient."""
    rng = random.Random(seed)
    top, bottom = rng.choice(BACKGROUNDS), tuple(int(c * 0.75) for c in rng.choice(BACKGROUNDS))
    im = Image.new("RGB", (SW, SH))
    d = ImageDraw.Draw(im)
    for y in range(SH):
        t = y / SH
        d.line((0, y, SW, y), fill=tuple(int(a + (b - a) * t) for a, b in zip(top, bottom)))
    inner = figure(seed, False)[0] if rng.random() < 0.5 else scene(seed)
    im.paste(inner, (0, (SH - H) // 2))
    return im


def avatar(seed: int) -> Image.Image:
    rng = random.Random(seed)
    im = Image.new("RGB", (128, 128), rng.choice(BACKGROUNDS))
    d = ImageDraw.Draw(im)
    c = rng.choice(CLOTHES)
    d.ellipse((34, 18, 94, 78), fill=rng.choice(SKIN))
    d.ellipse((14, 82, 114, 170), fill=c)
    return im


def main() -> None:
    for sub in ("images", "aois", "avatars"):
        (HERE / sub).mkdir(exist_ok=True)
    for n in range(1, 9):
        for version in ("original", "retouched"):
            im, aois = figure(n, version == "retouched")
            im.save(HERE / "images" / f"crit{n:02d}_{version}.png", optimize=True)
            (HERE / "aois" / f"crit{n:02d}_{version}.json").write_text(json.dumps(aois, indent=1) + "\n")
    for n in range(1, 3):
        im, _ = figure(100 + n, False)
        im.save(HERE / "images" / f"foil{n:02d}.png", optimize=True)
    for n in range(1, 13):
        scene(200 + n).save(HERE / "images" / f"fill{n:02d}.png", optimize=True)
    for n in range(1, 7):
        avatar(300 + n).save(HERE / "avatars" / f"acc{n}.png", optimize=True)
    make_stories()


def make_stories() -> None:
    (HERE / "stories").mkdir(exist_ok=True)
    for n, name in enumerate(["acc3_1", "acc3_2", "acc6_1", "acc6_2", "acc5_1", "acc1_1"], start=1):
        story(400 + n).save(HERE / "stories" / f"{name}.png", optimize=True)


if __name__ == "__main__":
    main()
