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

from .platform import font_candidates

FONT_CANDIDATES = font_candidates()


@lru_cache(maxsize=1)
def font_paths() -> tuple[str, ...]:
    """Every usable CJK font, best first; later ones only supply glyphs the earlier ones lack."""
    paths: list[str] = []
    env = os.environ.get("WK_FONT")
    if env and Path(env).exists():
        paths.append(env)
    paths += [p for p in FONT_CANDIDATES if Path(p).exists()]
    import shutil

    if shutil.which("fc-match"):
        try:
            out = subprocess.run(
                ["fc-match", "-f", "%{file}", ":lang=ja"], capture_output=True, text=True, timeout=5
            ).stdout.strip()
            if out and Path(out).exists():
                paths.append(out)
        except Exception:
            pass
    return tuple(dict.fromkeys(paths))


def font_path() -> str | None:
    paths = font_paths()
    return paths[0] if paths else None


@lru_cache(maxsize=8)
def _fonts(size: int) -> tuple[ImageFont.FreeTypeFont, ...]:
    fonts = []
    for p in font_paths():
        try:
            fonts.append(ImageFont.truetype(p, size, index=0))  # index 0 of the CJK ttc is the JP face
        except OSError:
            pass
    return tuple(fonts) or (ImageFont.load_default(size),)


def _mask_bytes(font: ImageFont.FreeTypeFont, text: str) -> tuple[tuple[int, int], bytes]:
    mask = font.getmask(text)
    img = Image.new("L", mask.size)
    img.im.paste(mask, (0, 0, *mask.size))
    return mask.size, img.tobytes()


@lru_cache(maxsize=64)
def _notdef(font: ImageFont.FreeTypeFont) -> tuple[tuple[int, int], bytes]:
    return _mask_bytes(font, "\u0378")  # unassigned code point -> the font's .notdef box


@lru_cache(maxsize=4096)
def _glyph_font(size: int, ch: str) -> ImageFont.FreeTypeFont | None:
    """The first font in the chain that has a real glyph for ch (FreeType draws .notdef for missing ones)."""
    for font in _fonts(size):
        if _mask_bytes(font, ch) != _notdef(font):
            return font
    return None


def has_glyphs(text: str, px: int = 160) -> bool:
    return all(_glyph_font(px, ch) is not None for ch in text if not ch.isspace())


def _runs(text: str, px: int) -> list[tuple[ImageFont.FreeTypeFont, str]]:
    """Split text into (font, chunk) runs, falling back per character when the main font lacks the glyph."""
    primary = _fonts(px)[0]
    runs: list[tuple[ImageFont.FreeTypeFont, str]] = []
    for ch in text:
        font = _glyph_font(px, ch) or primary
        if runs and runs[-1][0] is font:
            runs[-1] = (font, runs[-1][1] + ch)
        else:
            runs.append((font, ch))
    return runs


def _hex(color: str) -> tuple[int, int, int]:
    c = color.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


@lru_cache(maxsize=256)
def text_image(text: str, color: str, px: int = 160, pad: int = 24) -> Image.Image:
    """The characters in white on a coloured rounded box, WaniKani style."""
    # lay the runs out on one baseline so mixed fonts line up, then centre the tight bbox
    placed: list[tuple[ImageFont.FreeTypeFont, str, int]] = []
    left = top = right = bottom = 0
    cursor = 0
    for i, (font, chunk) in enumerate(_runs(text, px)):
        l, t, r, b = font.getbbox(chunk, anchor="ls")
        l, r = l + cursor, r + cursor
        left, top, right, bottom = (l, t, r, b) if i == 0 else (min(left, l), min(top, t), max(right, r), max(bottom, b))
        placed.append((font, chunk, cursor))
        cursor += round(font.getlength(chunk))
    w, h = right - left, bottom - top
    box_w, box_h = max(w, px) + 2 * pad, px + 2 * pad
    img = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((0, 0, box_w - 1, box_h - 1), radius=pad, fill=_hex(color))
    x = (box_w - w) // 2 - left
    y = (box_h - h) // 2 - top
    for font, chunk, offset in placed:
        draw.text((x + offset, y), chunk, font=font, fill=(255, 255, 255, 255), anchor="ls")
    return img


def _svg_to_png(svg: bytes, px: int) -> bytes:
    import re

    import resvg_py

    # resvg has no CSS variables; WaniKani strokes with var(--color-text, #000), so keep the fallback
    text = re.sub(r"var\(--[\w-]+\s*,\s*([^)]+)\)", r"\1", svg.decode("utf-8"))
    return resvg_py.svg_to_bytes(svg_string=text, height=px)


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


def strokes_for_word(word: str, fetch, px: int = 320, gap: int = 24) -> Image.Image | None:
    """Stroke diagrams for every kanji in a word, side by side (vocabulary pages)."""
    chars = [c for c in word if 0x4E00 <= ord(c) <= 0x9FFF or 0x3400 <= ord(c) <= 0x4DBF]
    panels = []
    for c in chars:
        img = stroke_image(c, fetch, px=px)
        if img is not None:
            panels.append(img)
    if not panels:
        return None
    if len(panels) == 1:
        return panels[0]
    w = sum(p.width for p in panels) + gap * (len(panels) - 1)
    h = max(p.height for p in panels)
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    x = 0
    for p in panels:
        out.alpha_composite(p, (x, (h - p.height) // 2))
        x += p.width + gap
    return out
