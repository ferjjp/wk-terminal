from wanikani_tui import images


def _reset():
    for fn in (images.font_paths, images._fonts, images._notdef, images._glyph_font, images.text_image):
        if hasattr(fn, "cache_clear"):
            fn.cache_clear()


def test_glyph_fallback_with_bundled_font_only(monkeypatch):
    # only Pillow's bundled Latin font: ASCII has glyphs, kanji does not, rendering still works
    _reset()
    monkeypatch.setattr(images, "font_paths", lambda: ())
    try:
        assert images.has_glyphs("Water")
        assert not images.has_glyphs("水")
        img = images.text_image("水", "#00aaff", px=40, pad=4)
        assert img.size[1] == 48 and img.size[0] >= 48
    finally:
        _reset()


def test_runs_pick_first_font_with_glyph(monkeypatch):
    _reset()
    monkeypatch.setattr(images, "font_paths", lambda: ())
    try:
        runs = images._runs("ab", 40)
        assert len(runs) == 1 and runs[0][1] == "ab"
    finally:
        _reset()


def test_radical_svg_css_variable_stroke(tmp_path, monkeypatch):
    # WaniKani strokes with var(--color-text, #000); resvg ignores var() so the fallback must be substituted
    monkeypatch.setattr(images, "image_cache_dir", lambda: tmp_path)
    svg = (
        b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><style>.b{fill:none;'
        b'stroke:var(--color-text, #000);stroke-width:20px;}</style><line class="b" x1="0" y1="50" x2="100" y2="50"/></svg>'
    )
    img = images.radical_image("https://example.invalid/rib", "#0000ff", lambda url: svg, px=50, pad=5)
    assert img.getpixel((30, 30)) == (255, 255, 255, 255)
