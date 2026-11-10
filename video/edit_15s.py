"""Edit the 15-second silent SocialEyes clip (video/shotlist-15s.md).

Reads the raw material in video/build/raw15/ (feed strip and bars from the
emulator, the like take, builder frames, the simulated heatmap) and renders
every frame with Pillow: a headline over a phone frame or app window on the
SocialEyes brand background, with short fade-and-rise transitions. No zooms.

Outputs:
    video/socialeyes-15s.mp4    1920x1080, 30 fps, exactly 15.000 s, no audio
    video/socialeyes-15s.gif    960 px wide, 12 fps, palettegen, checked < 10 MB
    video/socialeyes-thumb.png  1920x1080 still (the results frame)

Usage (from the repo root, with opencv-python, numpy and Pillow):

    python video/edit_15s.py [--preview]
"""

import argparse
import json
import subprocess
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

REPO = Path(__file__).resolve().parent.parent
RAW = REPO / "video" / "build" / "raw15"
OUT_MP4 = REPO / "video" / "socialeyes-15s.mp4"
OUT_GIF = REPO / "video" / "socialeyes-15s.gif"
OUT_THUMB = REPO / "video" / "socialeyes-thumb.png"
LOGO = REPO / "docs" / "assets" / "socialeyes-logo-dark.png"

W, H, FPS = 1920, 1080, 30
TOTAL = 15.0
FONTS = Path("C:/Windows/Fonts")
TRANS = 0.35

# SocialEyes brand
BG = (20, 4, 52)
GLOW = (103, 80, 164)
LAVENDER = (208, 188, 255)
WHITE = (255, 255, 255)
GREY = (190, 182, 214)
FOOT = (226, 220, 240)
AMBER = (255, 196, 84)

WIN_CY = 655            # centre of the area under the headline
PHONE_H = 650           # phone frame height on the canvas

HEADLINES = [
    (0.0, 3.0, "THE PROBLEM", "Body-image studies: control or realism, pick one"),
    (3.0, 7.0, "THE FIX", "Researchers control every post, label and comment"),
    (7.0, 11.0, "ON THE PHONE", "A realistic feed, synced with Neon eye tracking"),
    (11.0, 15.0, "THE RESULT", "Built in 2 months, not 2 years"),
]
STATS = [("10", "UBC researchers"), ("2", "months to build, to spec"), ("3", "pilots running soon")]
FOOTER = "Built for UBC researchers studying attention on social media"
TAG = "SIMULATED DATA  ·  EXPERIMENTAL FEATURE"

# Shots: (start, end, kind)
SHOTS = [(0.0, 3.0, "feed"), (3.0, 7.0, "builder"), (7.0, 11.0, "like"), (11.0, 15.0, "stats")]


# --- Helpers ---

def vfont(size, style):
    f = ImageFont.truetype(str(FONTS / "SegUIVar.ttf"), size)
    f.set_variation_by_name(style)
    return f


def ease_out(p):
    p = min(max(p, 0.0), 1.0)
    return 1 - (1 - p) ** 3


def ease_in_out(p):
    p = min(max(p, 0.0), 1.0)
    return p * p * (3 - 2 * p)


def background():
    bg = Image.new("RGB", (W, H), BG)
    glow = Image.new("L", (W, H), 0)
    ImageDraw.Draw(glow).ellipse((W * 0.15, H * 0.35, W * 1.0, H * 1.5), fill=255)
    glow = glow.filter(ImageFilter.GaussianBlur(240)).point(lambda v: int(v * 0.55))
    bg.paste(GLOW, (0, 0), glow)
    return bg


@lru_cache(maxsize=None)
def logo(width):
    im = Image.open(LOGO).convert("RGBA")
    return im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)


def paste_logo(canvas, width, x, y, alpha=1.0):
    if alpha <= 0:
        return
    im = logo(width)
    mask = im.getchannel("A")
    if alpha < 1:
        mask = mask.point(lambda v: int(v * alpha))
    canvas.paste(im, (int(x), int(y)), mask)


def corner_logo(canvas, alpha=1.0):
    im = logo(230)
    paste_logo(canvas, 230, W - im.width - 48, H - im.height - 34, alpha)


@lru_cache(maxsize=None)
def frame_masks(w, h, radius, shadow_alpha=170):
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius, fill=255)
    pad = 90
    shadow = Image.new("L", (w + 2 * pad, h + 2 * pad), 0)
    ImageDraw.Draw(shadow).rounded_rectangle((pad, pad + 26, pad + w, pad + h + 26), radius,
                                             fill=shadow_alpha)
    shadow = shadow.filter(ImageFilter.GaussianBlur(38))
    border = Image.new("L", (w, h), 0)
    ImageDraw.Draw(border).rounded_rectangle((0, 0, w - 1, h - 1), radius, outline=60, width=2)
    return mask, shadow, border, pad


def place(canvas, content, cx, cy, radius, alpha=1.0, dy=0.0, border=True):
    """Paste content with rounded corners and a soft shadow, centred at (cx, cy + dy)."""
    if alpha <= 0:
        return
    w, h = content.size
    x, y = int(cx - w / 2), int(cy - h / 2 + dy)
    mask, shadow, edge, pad = frame_masks(w, h, radius)
    a = (lambda m: m) if alpha >= 1 else (lambda m: m.point(lambda v: int(v * alpha)))
    canvas.paste((0, 0, 0), (x - pad, y - pad), a(shadow))
    canvas.paste(content, (x, y), a(mask))
    if border:
        canvas.paste((255, 255, 255), (x, y), a(edge))


def paste_fade(canvas, layer, alpha, xy=(0, 0)):
    if alpha <= 0:
        return
    if alpha < 1:
        layer = layer.copy()
        layer.putalpha(layer.getchannel("A").point(lambda v: int(v * alpha)))
    canvas.paste(layer, (int(xy[0]), int(xy[1])), layer)


# --- Phone ---

class Phone:
    """Composes phone screens from the feed strip and renders them in a phone frame."""

    def __init__(self):
        self.strip = Image.open(RAW / "feed_strip.png").convert("RGB")
        self.top_plain = Image.open(RAW / "topbar_plain.png").convert("RGB")
        self.top_done = Image.open(RAW / "topbar_done.png").convert("RGB")
        self.bot_bar = Image.open(RAW / "botbar.png").convert("RGB")
        self.pos = json.loads((RAW / "phone.json").read_text())   # measured by record_15s.py
        self.top, self.bot = self.pos["top"], self.pos["bot"]
        cap = cv2.VideoCapture(str(RAW / "like.mp4"))
        self.like = []   # (time, frame) - screenrecord is variable frame rate
        while True:
            ok, f = cap.read()
            if not ok:
                break
            self.like.append((cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0,
                              Image.fromarray(cv2.cvtColor(f, cv2.COLOR_BGR2RGB))))
        self.screen_h = PHONE_H - 2 * 16
        self.screen_w = round(self.screen_h / 2)

    def screen_at(self, offset, top="plain"):
        scr = Image.new("RGB", (1080, 2160), WHITE)
        scr.paste(self.top_plain if top == "plain" else self.top_done, (0, 0))
        o = int(round(offset))
        scr.paste(self.strip.crop((0, o, 1080, o + self.bot - self.top)), (0, self.top))
        scr.paste(self.bot_bar, (0, self.bot))
        return scr

    def like_at(self, t):
        frame = self.like[0][1]
        for ts, f in self.like:
            if ts <= t:
                frame = f
            else:
                break
        return frame

    def framed(self, screen):
        """Phone body with the screen inset; returns an RGB image."""
        sw, sh = self.screen_w, self.screen_h
        body = Image.new("RGB", (sw + 32, sh + 32), (16, 16, 20))
        scr = screen.resize((sw, sh), Image.LANCZOS)
        m = Image.new("L", (sw, sh), 0)
        ImageDraw.Draw(m).rounded_rectangle((0, 0, sw - 1, sh - 1), 26, fill=255)
        body.paste(scr, (16, 16), m)
        return body


# --- Cards ---

def heatmap_card(height):
    hm = Image.open(RAW / "heatmap.png").convert("RGB")
    w = round(hm.width * height / hm.height)
    return hm.resize((w, height), Image.LANCZOS)


def tag_layer():
    f = vfont(26, "Semibold Text")
    d0 = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    tw = d0.textlength(TAG, font=f)
    layer = Image.new("RGBA", (int(tw) + 44, 50), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.rounded_rectangle((0, 0, layer.width - 1, 49), 25, fill=(30, 20, 10, 235), outline=AMBER, width=2)
    d.text((22, 9), TAG, font=f, fill=AMBER)
    return layer


def draw_stats(canvas, t_local):
    d = ImageDraw.Draw(canvas)
    num_f, lab_f, foot_f = vfont(150, "Bold Display"), vfont(38, "Regular"), vfont(38, "Regular")
    col_w = 560
    x0 = (W - col_w * len(STATS)) / 2
    for i, (num, label) in enumerate(STATS):
        p = ease_out((t_local - 0.15 - 0.15 * i) / TRANS)
        if p <= 0:
            continue
        layer = Image.new("RGBA", (col_w, 280), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        ld.text(((col_w - ld.textlength(num, font=num_f)) / 2, 0), num, font=num_f, fill=WHITE)
        ld.text(((col_w - ld.textlength(label, font=lab_f)) / 2, 200), label, font=lab_f, fill=LAVENDER)
        paste_fade(canvas, layer, p, (x0 + col_w * i, 345 + 30 * (1 - p)))
    p = ease_out((t_local - 0.7) / TRANS)
    if p > 0:
        lw = 440
        paste_logo(canvas, lw, (W - lw) / 2, 715 + 20 * (1 - p), p)
        fw = d.textlength(FOOTER, font=foot_f)
        shade = tuple(int(BG[k] + (FOOT[k] - BG[k]) * p) for k in range(3))
        d.text(((W - fw) / 2, 870 + 20 * (1 - p)), FOOTER, font=foot_f, fill=shade)
    d.line(((W - 120) / 2, 278, (W + 120) / 2, 278), fill=GLOW, width=4)


def headline_layer(kicker, text):
    layer = Image.new("RGBA", (W, 260), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    size = 78
    while True:
        h_f = vfont(size, "Bold Display")
        if d.textlength(text, font=h_f) <= W - 200 or size <= 56:
            break
        size -= 2
    k_f, track = vfont(28, "Semibold Text"), 5
    kw = sum(d.textlength(c, font=k_f) + track for c in kicker) - track
    x = (W - kw) / 2
    for c in kicker:
        d.text((x, 80), c, font=k_f, fill=LAVENDER)
        x += d.textlength(c, font=k_f) + track
    d.text(((W - d.textlength(text, font=h_f)) / 2, 122), text, font=h_f, fill=WHITE)
    return layer


# --- Render ---

def render():
    bg = background()
    phone = Phone()
    builder = sorted((RAW / "builder").glob("f*.png"))
    bw_h = 620
    heads = [(a, b, headline_layer(k, t)) for a, b, k, t in HEADLINES]
    tag = tag_layer()
    hm = heatmap_card(560)
    target = phone.pos["target"]

    def builder_img(local):
        i = min(int(local * FPS), len(builder) - 1)
        im = Image.open(builder[i]).convert("RGB")
        return im.resize((round(im.width * bw_h / im.height), bw_h), Image.LANCZOS)

    def feed_screen(local):
        # a slow participant scroll through the top of the feed
        return phone.screen_at(820 * ease_in_out((local - 0.3) / 2.6))

    def like_screen(local):
        if local < 0.9:          # scroll onto the labelled post
            off = target - 1300 * (1 - ease_out(local / 0.9))
            return phone.screen_at(off, top="done")
        return phone.like_at(0.8 + (local - 0.9))   # the recorded double-tap like

    for i in range(int(TOTAL * FPS)):
        t = i / FPS
        canvas = bg.copy()
        k = next(n for n, s in enumerate(SHOTS) if s[0] <= t < s[1])
        start, end, kind = SHOTS[k]
        local = t - start
        p = ease_out(local / TRANS) if k > 0 else 1.0

        # outgoing shot fades out underneath
        if p < 1 and k > 0:
            ps, pe, pk = SHOTS[k - 1]
            pl = pe - ps - 1e-3
            if pk == "feed":
                place(canvas, phone.framed(feed_screen(pl)), W / 2, WIN_CY, 40, alpha=1 - p, border=False)
            elif pk == "builder":
                place(canvas, builder_img(pl), W / 2, WIN_CY, 18, alpha=1 - p)
            elif pk == "like":
                place(canvas, phone.framed(like_screen(pl)), W / 2 - 300, WIN_CY, 40, alpha=1 - p,
                      border=False)
                place(canvas, hm, W / 2 + 300, WIN_CY + 25, 18, alpha=1 - p)

        if kind == "stats":
            corner_logo(canvas, 1 - p)
            draw_stats(canvas, local)
        else:
            corner_logo(canvas)
            rise = 18 * (1 - p)
            if kind == "feed":
                place(canvas, phone.framed(feed_screen(local)), W / 2, WIN_CY, 40, alpha=p, dy=rise,
                      border=False)
            elif kind == "builder":
                place(canvas, builder_img(local), W / 2, WIN_CY, 18, alpha=p, dy=rise)
            elif kind == "like":
                # 7.0-9.5 s: phone centred; 9.5-11 s: phone slides left, heatmap card comes in
                hp = ease_out((local - 2.5) / 0.45)
                px = W / 2 - 300 * hp
                place(canvas, phone.framed(like_screen(local)), px, WIN_CY, 40, alpha=p, dy=rise,
                      border=False)
                if hp > 0:
                    place(canvas, hm, W / 2 + 300, WIN_CY + 25 + 20 * (1 - hp), 18, alpha=hp)
                    tp = ease_out((local - 2.75) / 0.35)
                    paste_fade(canvas, tag, tp, (W / 2 + 300 - tag.width / 2,
                                                 WIN_CY + 25 - hm.height / 2 - 70))

        for a, b, layer in heads:
            if a <= t < b:
                hp_ = ease_out((t - a) / TRANS) if a > 0 else 1.0
                paste_fade(canvas, layer, hp_, (0, 16 * (1 - hp_)))
            elif b <= t < b + 0.15 and b < TOTAL:
                paste_fade(canvas, layer, 1 - (t - b) / 0.15)
        yield canvas


def run(cmd):
    subprocess.run(cmd, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--preview", action="store_true", help="write a contact sheet too")
    args = parser.parse_args()

    enc = subprocess.Popen(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
         "-an", "-c:v", "libx264", "-preset", "slow", "-crf", "16", "-tune", "animation",
         "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(OUT_MP4)],
        stdin=subprocess.PIPE)
    thumb_frame = int(14.5 * FPS)
    sheet = []
    for i, frame in enumerate(render()):
        enc.stdin.write(np.asarray(frame).tobytes())
        if i == thumb_frame:
            frame.save(OUT_THUMB)
        if args.preview and i % 15 == 0:
            sheet.append(frame.resize((480, 270), Image.LANCZOS))
    enc.stdin.close()
    if enc.wait() != 0:
        raise SystemExit("ffmpeg failed")

    palette = RAW / "palette.png"
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(OUT_MP4), "-vf",
         "fps=12,scale=960:-1:flags=lanczos,palettegen=max_colors=256:stats_mode=full", str(palette)])
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(OUT_MP4), "-i", str(palette),
         "-lavfi", "fps=12,scale=960:-1:flags=lanczos[v];[v][1:v]paletteuse=dither=bayer:bayer_scale=3:"
         "diff_mode=rectangle", str(OUT_GIF)])

    if args.preview:
        cols = 6
        rows = (len(sheet) + cols - 1) // cols
        cs = Image.new("RGB", (480 * cols, 270 * rows))
        for k, f in enumerate(sheet):
            cs.paste(f, ((k % cols) * 480, (k // cols) * 270))
        cs.save(RAW / "contact_sheet.png")

    gif_mb = OUT_GIF.stat().st_size / 1e6
    print(f"{OUT_MP4.name}: {OUT_MP4.stat().st_size / 1e6:.1f} MB")
    print(f"{OUT_GIF.name}: {gif_mb:.1f} MB" + ("  (OVER 10 MB)" if gif_mb >= 10 else ""))
    print(f"{OUT_THUMB.name}: frame at 14.5 s")


if __name__ == "__main__":
    main()
