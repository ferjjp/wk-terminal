# wanikani-tui

Terminal client for WaniKani (Python 3.13, Textual 8, uv). Installed as the `wk` command via
`uv tool install --editable .` — code edits are live, but **new dependencies need
`uv tool install --editable . --reinstall`**.

## Layout (src/wanikani_tui)

- `cli.py` — argparse entry (`tui` default, `sync`, `due`, `today`, `pop`, `read`, `daemon`, `export`, `config`, `keys`, `doctor`)
- `core.py` — service layer shared by every entry point: queues, submissions + retry queue, popup picker, stats, export
- `api.py` / `db.py` / `sync.py` — WaniKani v2 client (rate limit + retry), SQLite cache (WAL), incremental sync
- `models.py` — Subject/Assignment wrappers, SRS math, palettes
- `answers.py` — meaning/reading checking (typo tolerance, IME kana rules: `nn`/`n'` → ん, trailing syllable held)
- `session.py` — review queue logic (active pool, undo, back-to-back)
- `app.py` — Textual app, dashboard, stats screen · `screens.py` — subject, browse, session, lessons, picker, modals
- `widgets.py` — CharDisplay/Chip with kitty-graphics images; `ImageWidget` caches the terminal image per (image,size)
  because textual-image deletes/re-sends on every render (this wiped the kanji on keystrokes)
- `images.py` — Pillow rendering of characters, radical SVGs (resvg), KanjiVG strokes · `audio.py`
- `extdata.py` — Keisei/Niai community datasets (GPL-3, fetched on demand into data_dir/ext, pinned commit);
  `keisei_info()` / `niai_similar()` replicate the userscripts' logic
- `pitch.py` — Kanjium accents table (CC BY-SA 4.0) fetched on demand; `describe()` renders morae + ꜜ
- `analyzer.py` — vocabulary reading breakdown (which kanji reading, rendaku/sokuon/exception, known or not)
- `confusion.py` — "confused with" guess on a wrong answer (subject JSON is ASCII-escaped: match `json.dumps(kana)`)
- `reader.py` — `wk read`: kanji/vocab highlighting by SRS stage + unknown lists · `attention.py` — GNOME idle time
  (org.gnome.Mutter.IdleMonitor) and DND (gsettings show-banners) for the daemon's `good_moment()`
- `keys.py` — ACTIONS map (default key, where, what); every Binding goes through `key(action)`; `wk keys` lists them
- `daemon.py` / `notify.py` — background sync + desktop notifications (D-Bus via jeepney on Linux; terminal-notifier
  on macOS) opening `wk pop` in a terminal window · `platform.py` — OS detection and defaults
- `config.py` — paths, token, `config.toml` → `Settings` (cached; daemon reloads on mtime change) · `keys.py`

## Conventions

- Never print or log the API token. It lives in `~/.config/wanikani/token` or `WANIKANI_API_TOKEN`.
- Under tmux, image mode auto → tgp when the outer terminal is ghostty/kitty/wezterm (tmux answers capability
  queries itself and advertises Sixel, which ghostty can't draw). Never rely on the negotiation inside tmux.
- Rich colours must be 6-digit hex (`#77ffdd`); 3-digit forms crash Textual's style parser.
- Screen callbacks passed to `push_screen` must be plain functions (a `dismiss()` inside a lambda from a
  message handler raises ScreenError).
- Anything that writes to the account goes through `Core` so the retry queue and session history stay consistent.
- SessionScreen modes: review (submits), lesson (starts assignments), study (never writes; `core.record_study`).
  Anki mode (`self.anki`): Input disabled from the start, Space reveals, 1/2 grade via `_apply_verdict(override=True)`.
  While a verdict is shown the Input is disabled so Enter / +/- / ctrl+z reach the screen bindings.
- Do not define `_render` on widgets: it shadows Textual's `Widget._render`.
- WaniKani's GET /reviews returns nothing (server-side); daily counts/streak/heatmap use local `session_items`.
- `Database.conn` is a `_LockedConnection`: one RLock, rows fetched eagerly. Workers and the UI thread share it;
  a raw shared sqlite3 connection corrupts rows under concurrent cursors (seen as `json.loads(None)`).

## Testing

- `uv run pytest` — logic, core (fake API in `tests/fixtures.py`), platform selection, real-cache data shapes
  (skipped when `~/.local/share/wanikani-tui/cache.sqlite3` is absent)
- `uv run python tests/drive.py out/`, `tests/drive2.py out/`, `tests/drive3.py out/` — headless Textual drives that save PNG screenshots
- `uv run python tests/pty_capture.py "r,a,enter" out.bin` — runs the app in a pty and lists kitty-graphics
  commands against painted placeholder cells; use this for any image bug before theorising
- Set `WK_IMAGES=none|unicode` for headless runs.
