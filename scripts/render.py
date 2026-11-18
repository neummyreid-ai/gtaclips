#!/usr/bin/env python3
"""Editor: turns jobs/*.json into 1080x1920 Vice City-style vertical videos in out/.

Job file: {"id", "url", "caption", "emoji", "credit", "dur"}
  id       file name for out/<id>.mp4 (letters, digits, - and _)
  url      Twitch clip URL (anything yt-dlp can download)
  caption  one big caption line (auto-wrapped, max 3 lines)
  emoji    one emoji, e.g. 🔥 😮 😂 (optional)
  credit   credit line, e.g. "Clip: Kai Cenat on Twitch"
  dur      seconds to keep from the start (optional, null = whole clip)
  ad       true for paid campaign clips: adds an on-screen "AD" label (optional)

Usage:
  python scripts/render.py                       # render every job not yet in out/
  python scripts/render.py --job jobs/x.json --input local.mp4   # local test
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT = os.path.join(ROOT, "fonts", "Anton-Regular.ttf")
EMOJI_FONT = os.path.join(ROOT, "fonts", "NotoColorEmoji.ttf")
W, H = 1080, 1920
PINK = (255, 46, 136)
ORANGE = (255, 138, 61)
PURPLE = (74, 20, 140)
TEAL = (51, 240, 224)
DARK = (20, 6, 31)
HEADER = "VICE CITY CLIPPED"
SIDE = 24            # margin around the gameplay frame
VIDEO_CENTER_Y = 1080
CAPTION_TOP = 215
MAX_TEXT_W = 980


# ---------- helpers ----------

def run(cmd):
    print("+", " ".join(cmd[:6]), "...", flush=True)
    subprocess.run(cmd, check=True)


def probe(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height:format=duration", "-of", "json", path],
        capture_output=True, text=True, check=True).stdout
    d = json.loads(out)
    s = d["streams"][0]
    has_audio = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
         "stream=index", "-of", "csv=p=0", path],
        capture_output=True, text=True).stdout.strip() != ""
    return int(s["width"]), int(s["height"]), float(d["format"].get("duration") or 0), has_audio


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def gradient(size, stops, horizontal=False):
    w, h = size
    n = w if horizontal else h
    cols = []
    for i in range(n):
        t = i / max(1, n - 1)
        for k in range(len(stops) - 1):
            t0, c0 = stops[k]
            t1, c1 = stops[k + 1]
            if t0 <= t <= t1:
                cols.append(lerp(c0, c1, (t - t0) / max(1e-6, t1 - t0)))
                break
        else:
            cols.append(stops[-1][1])
    strip = Image.new("RGB", (n, 1) if horizontal else (1, n))
    strip.putdata(cols)
    return strip.resize(size, Image.NEAREST)


def video_box(src_w, src_h):
    vw = W - 2 * SIDE
    vh = round(vw * src_h / src_w / 2) * 2
    if vh > 1180:  # tall/vertical source: limit height instead
        vh = 1180
        vw = round(vh * src_w / src_h / 2) * 2
    x = (W - vw) // 2
    y = VIDEO_CENTER_Y - vh // 2
    y -= y % 2
    return x, y, vw, vh


# ---------- text ----------

def wrap(text, font, max_w):
    words = text.split()
    lines, cur = [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if font.getlength(test) <= max_w or not cur:
            cur = test
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def emoji_image(ch, height):
    try:
        f = ImageFont.truetype(EMOJI_FONT, 109)
    except OSError:
        return None
    im = Image.new("RGBA", (160, 160), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((10, 10), ch, font=f, embedded_color=True)
    bbox = im.getbbox()
    if not bbox:
        return None
    im = im.crop(bbox)
    return im.resize((round(im.width * height / im.height), height), Image.LANCZOS)


def caption_block(text, emoji, max_bottom):
    """Returns an RGBA image of the caption (gradient fill, dark outline, emoji)."""
    text = re.sub(r"\s+", " ", text).strip().upper()
    avail_h = max_bottom - CAPTION_TOP
    for size in range(132, 60, -6):
        font = ImageFont.truetype(FONT, size)
        lines = wrap(text, font, MAX_TEXT_W)
        line_h = int(size * 1.12)
        emo_h = int(size * 0.92)
        emo = emoji_image(emoji, emo_h) if emoji else None
        last_w = font.getlength(lines[-1]) if lines else 0
        emoji_inline = emo is not None and last_w + 24 + emo.width <= MAX_TEXT_W
        n_lines = len(lines) + (1 if emo is not None and not emoji_inline else 0)
        if len(lines) <= 3 and n_lines * line_h <= avail_h:
            break
    stroke = max(6, size // 13)
    block_h = n_lines * line_h + 2 * stroke + 20
    layer = Image.new("RGBA", (W, block_h), (0, 0, 0, 0))
    mask = Image.new("L", (W, block_h), 0)
    d_layer = ImageDraw.Draw(layer)
    d_mask = ImageDraw.Draw(mask)
    y = stroke
    placements = []
    for i, line in enumerate(lines):
        lw = font.getlength(line)
        extra = (24 + emo.width) if (emoji_inline and i == len(lines) - 1) else 0
        x = (W - (lw + extra)) / 2
        # shadow + dark outline
        d_layer.text((x + 6, y + 8), line, font=font, fill=DARK + (170,),
                     stroke_width=stroke, stroke_fill=DARK + (170,))
        d_layer.text((x, y), line, font=font, fill=DARK, stroke_width=stroke, stroke_fill=DARK)
        d_mask.text((x, y), line, font=font, fill=255)
        if extra:
            placements.append((int(x + lw + 24), int(y + (line_h - emo.height) / 2)))
        y += line_h
    if emo is not None and not emoji_inline:
        placements.append(((W - emo.width) // 2, y + 4))
    grad = gradient((W, block_h), [(0, PINK), (1, ORANGE)]).convert("RGBA")
    layer.paste(grad, (0, 0), mask)
    for p in placements:
        layer.alpha_composite(emo, p)
    return layer


def spaced_text(draw, center_x, y, text, font, fill, spacing, stroke=0, stroke_fill=None):
    widths = [font.getlength(c) for c in text]
    total = sum(widths) + spacing * (len(text) - 1)
    x = center_x - total / 2
    for c, cw in zip(text, widths):
        draw.text((x, y), c, font=font, fill=fill, stroke_width=stroke, stroke_fill=stroke_fill)
        x += cw + spacing


# ---------- layers ----------

def make_tint(path):
    g = gradient((W, H), [(0, PURPLE), (0.55, PINK), (1, ORANGE)]).convert("RGBA")
    g.putalpha(150)
    g.save(path)


def make_overlay(path, job, box):
    x, y, vw, vh = box
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    # darken the top so the caption pops
    alpha = Image.new("L", (1, y))
    alpha.putdata([int(150 * (1 - yy / max(1, y)) + 40) for yy in range(y)])
    top = Image.new("RGBA", (W, y), DARK + (0,))
    top.putalpha(alpha.resize((W, y)))
    img.alpha_composite(top, (0, 0))

    # neon frame with glow
    pad, thick = 8, 8
    rect = (x - pad, y - pad, x + vw + pad, y + vh + pad)
    frame_mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(frame_mask).rounded_rectangle(rect, radius=18, outline=255, width=thick)
    glow_mask = frame_mask.filter(ImageFilter.GaussianBlur(14))
    neon = gradient((W, H), [(0, PINK), (1, ORANGE)], horizontal=True).convert("RGBA")
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    glow.paste(neon, (0, 0), glow_mask)
    img.alpha_composite(glow)
    img.alpha_composite(glow)
    img.paste(neon, (0, 0), frame_mask)

    # header
    d = ImageDraw.Draw(img)
    hf = ImageFont.truetype(FONT, 62)
    spaced_text(d, W / 2, 100, HEADER, hf, TEAL, 7, stroke=4, stroke_fill=DARK)

    # paid campaign clips: on-screen ad disclosure at the start of the video
    if job.get("ad"):
        af = ImageFont.truetype(FONT, 44)
        d.rounded_rectangle((40, 40, 150, 104), radius=14, fill=(255, 255, 255, 235))
        d.text((95 - af.getlength("AD") / 2, 44), "AD", font=af, fill=DARK)

    # caption
    cap = caption_block(job.get("caption", ""), job.get("emoji"), y - 40)
    cap_y = CAPTION_TOP + max(0, ((y - 40 - CAPTION_TOP) - cap.height) // 2)
    img.alpha_composite(cap, (0, cap_y))

    # credit
    credit = job.get("credit")
    if credit:
        cf = ImageFont.truetype(FONT, 46)
        cw = cf.getlength(credit)
        d.text(((W - cw) / 2, y + vh + pad + 44), credit, font=cf, fill=(255, 255, 255, 235),
               stroke_width=4, stroke_fill=DARK)
    img.save(path)


# ---------- pipeline ----------

def download(url, dest):
    run(["yt-dlp", "--no-playlist", "-f", "best[ext=mp4]/best", "-o", dest, url])


def render(job, src, out_path):
    sw, sh, sdur, has_audio = probe(src)
    box = video_box(sw, sh)
    x, y, vw, vh = box
    with tempfile.TemporaryDirectory() as tmp:
        tint = os.path.join(tmp, "tint.png")
        ov = os.path.join(tmp, "overlay.png")
        make_tint(tint)
        make_overlay(ov, job, box)
        dur = job.get("dur")
        fc = (
            "[0:v]split=2[a][b];"
            f"[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=28:4[bg];"
            "[bg][1:v]overlay=0:0[bgt];"
            f"[b]scale={vw}:{vh}:flags=lanczos,setsar=1[fg];"
            f"[bgt][fg]overlay={x}:{y}[v1];"
            "[v1][2:v]overlay=0:0,fps=30,format=yuv420p[v]"
        )
        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
        if dur:
            cmd += ["-t", str(dur)]
        cmd += ["-i", src, "-i", tint, "-i", ov, "-filter_complex", fc, "-map", "[v]"]
        if has_audio:
            cmd += ["-map", "0:a:0", "-c:a", "aac", "-b:a", "160k", "-ar", "44100"]
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-profile:v", "high",
                "-movflags", "+faststart", out_path]
        run(cmd)
    size = os.path.getsize(out_path) / 1e6
    print(f"rendered {out_path} ({size:.1f} MB)")
    if size > 95:
        os.remove(out_path)
        raise RuntimeError("output over GitHub's 100 MB file limit; use a shorter dur")


def safe_id(s):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", s or ""):
        raise ValueError(f"bad job id: {s!r}")
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--job")
    ap.add_argument("--input", help="local source video (skips download)")
    ap.add_argument("--out")
    a = ap.parse_args()

    jobs = [a.job] if a.job else sorted(glob.glob(os.path.join(ROOT, "jobs", "*.json")))
    os.makedirs(os.path.join(ROOT, "out"), exist_ok=True)
    failed = 0
    for jp in jobs:
        with open(jp) as f:
            job = json.load(f)
        jid = safe_id(job["id"])
        out_path = a.out or os.path.join(ROOT, "out", f"{jid}.mp4")
        if os.path.exists(out_path) and not a.job:
            continue
        try:
            if a.input:
                render(job, a.input, out_path)
            else:
                with tempfile.TemporaryDirectory() as tmp:
                    src = os.path.join(tmp, "src.mp4")
                    download(job["url"], src)
                    render(job, src, out_path)
        except Exception as exc:
            failed += 1
            print(f"job {jid} failed: {exc}", file=sys.stderr)
    sys.exit(1 if failed and failed == len(jobs) else 0)


if __name__ == "__main__":
    main()
