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
