"""Rendering characters and radical SVGs into images for the terminal."""

from __future__ import annotations

import hashlib
import os
import subprocess
from functools import lru_cache
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .config import image_cache_dir

FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
]


@lru_cache(maxsize=1)
def font_path() -> str | None:
    env = os.environ.get("WK_FONT")
    if env and Path(env).exists():
        return env
    for p in FONT_CANDIDATES:
        if Path(p).exists():
            return p
    try:
        out = subprocess.run(
            ["fc-match", "-f", "%{file}", "Noto Sans CJK JP:lang=ja"], capture_output=True, text=True, timeout=5
        ).stdout.strip()
        if out and Path(out).exists():
            return out
    except Exception:
        pass
    return None


@lru_cache(maxsize=8)
def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    p = font_path()
    if p:
        try:
            return ImageFont.truetype(p, size, index=0)  # index 0 of the CJK ttc is the JP face
        except OSError:
            pass
    return ImageFont.load_default()


def _hex(color: str) -> tuple[int, int, int]:
    c = color.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


@lru_cache(maxsize=256)
def text_image(text: str, color: str, px: int = 160, pad: int = 24) -> Image.Image:
    """The characters in white on a coloured rounded box, WaniKani style."""
    font = _font(px)
    probe = Image.new("RGBA", (1, 1))
    left, top, right, bottom = ImageDraw.Draw(probe).textbbox((0, 0), text, font=font)
    w, h = right - left, bottom - top
    box_w, box_h = max(w, px) + 2 * pad, px + 2 * pad
    img = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((0, 0, box_w - 1, box_h - 1), radius=pad, fill=_hex(color))
    x = (box_w - w) // 2 - left
    y = (box_h - h) // 2 - top
    draw.text((x, y), text, font=font, fill=(255, 255, 255, 255))
    return img


def _svg_to_png(svg: bytes, px: int) -> bytes:
    import resvg_py

    return resvg_py.svg_to_bytes(svg_string=svg.decode("utf-8"), height=px)


def radical_image(url: str, color: str, fetch, px: int = 160, pad: int = 24) -> Image.Image:
    """Rasterise a radical SVG (black strokes) and recolour it white on a coloured box."""
    key = hashlib.sha1(url.encode()).hexdigest()[:16]
    svg_file = image_cache_dir() / f"{key}.svg"
    if svg_file.exists():
        svg = svg_file.read_bytes()
    else:
        svg = fetch(url)
        svg_file.write_bytes(svg)
    png = Image.open(BytesIO(_svg_to_png(svg, px))).convert("RGBA")
    # use luminance as the stroke mask: dark pixels become white strokes
    alpha = png.getchannel("A")
    lum = png.convert("L").point(lambda v: 255 - v)
    mask = Image.composite(lum, Image.new("L", png.size, 0), alpha)
    w, h = png.size
    box_w, box_h = max(w, px) + 2 * pad, px + 2 * pad
    img = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((0, 0, box_w - 1, box_h - 1), radius=pad, fill=_hex(color))
    white = Image.new("RGBA", png.size, (255, 255, 255, 255))
    img.paste(white, ((box_w - w) // 2, (box_h - h) // 2), mask)
    return img


STROKE_COLORS = ["#ff5f5f", "#ffb347", "#ffe66d", "#7be0ad", "#5fc8ff", "#9d8cff", "#ff8ad8", "#c0ff8a", "#ffd18a", "#8affe3"]
KANJIVG_URL = "https://raw.githubusercontent.com/KanjiVG/kanjivg/master/kanji/{code}.svg"


def stroke_image(char: str, fetch, px: int = 320) -> Image.Image | None:
    """Stroke order from KanjiVG (CC BY-SA 3.0): each stroke in its own colour, numbered."""
    import re

    code = f"{ord(char):05x}"
    svg_file = image_cache_dir() / f"kanjivg-{code}.svg"
    if svg_file.exists():
        svg = svg_file.read_text()
    else:
        try:
            svg = fetch(KANJIVG_URL.format(code=code)).decode("utf-8")
        except Exception:  # noqa: BLE001
            return None
        svg_file.write_text(svg)
    counter = {"i": 0}

    def colour(m: "re.Match[str]") -> str:
        c = STROKE_COLORS[counter["i"] % len(STROKE_COLORS)]
        counter["i"] += 1
        return f'<path style="stroke:{c};stroke-width:4;fill:none" '

    svg = re.sub(r"<path ", colour, svg)
    svg = svg.replace("fill:#808080", "fill:#ffffff").replace("font-size:8", "font-size:7")
    png = Image.open(BytesIO(_svg_to_png(svg.encode("utf-8"), px))).convert("RGBA")
    pad = 16
    box = Image.new("RGBA", (png.width + 2 * pad, png.height + 2 * pad), (0, 0, 0, 0))
    ImageDraw.Draw(box).rounded_rectangle((0, 0, box.width - 1, box.height - 1), radius=pad, fill=(40, 40, 48, 255))
    box.alpha_composite(png, (pad, pad))
    return box
