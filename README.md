# wanikani-tui

WaniKani in your terminal: dashboard, item browser, reviews and lessons, with kanji and
radical images drawn through the kitty graphics protocol (ghostty, kitty, WezTerm…),
plus a background daemon that nudges you with desktop notifications and opens a small
review window.

## Setup

1. Create a personal access token at
   <https://www.wanikani.com/settings/personal_access_tokens> with
   `assignments:start`, `reviews:create`, `study_materials:create` and
   `study_materials:update` enabled.
2. Store it where the app can find it (never paste it into chat logs):

   ```sh
   mkdir -p ~/.config/wanikani
   printf '%s\n' 'YOUR-TOKEN-HERE' > ~/.config/wanikani/token
   chmod 600 ~/.config/wanikani/token
   ```

   `WANIKANI_API_TOKEN` in the environment also works.
3. Install the `wk` command:

   ```sh
   uv tool install git+https://github.com/ferjjp/wk-terminal.git
   ```

   or, from a clone, `uv tool install --editable .` so edits are picked up live.

The first start downloads every subject (~10 requests) into
`~/.local/share/wanikani-tui/cache.sqlite3`. Later starts sync incrementally in the
background.

## Commands

```
wk                    # the full interface (syncs in the background)
wk --no-sync          # offline: browse the cache, reviews are queued until you are back online
wk --full-sync        # re-download everything
wk sync               # sync only, print counts; also sends queued submissions
wk due                # "12 reviews, 3 lessons"      (--format tmux|short|json, --sync)
wk pop                # one review (or one lesson) in a small window, then exit
wk daemon             # background sync + desktop notifications (foreground)
wk daemon install     # run it as a systemd user service, started with your session
wk daemon status | uninstall
wk export stats       # CSV: per-item accuracy + leech score (also: sessions, items, reviews; -o file.csv)
wk config             # write ~/.config/wanikani/config.toml with all defaults
wk doctor             # what image protocol the terminal negotiates
wk --images tgp       # force kitty graphics (auto | tgp | sixel | halfcell | unicode | none)
```

## Keys

Every key below can be changed under `[keys]` in the config file.

### Dashboard

| Key | Action |
|---|---|
| `r` | Start reviews |
| `l` | Start lessons (next batch) |
| `L` | Pick which lessons to take |
| `b` | Browse items by level |
| `e` | Your leeches |
| `t` | Stats |
| `s` | Sync now |
| `q` | Quit |

### Browse

| Key | Action |
|---|---|
| `↑` `↓` | Move through the list |
| `Tab` | Switch between the level column and the list |
| `Enter` | Open the item |
| `/` | Search characters, meaning or slug |
| `t` | Cycle type: all, radicals, kanji, vocabulary |
| `f` | Cycle filter: all, due in 24 h, leeches, apprentice … burned |
| `Esc` | Back |

### Item

| Key | Action |
|---|---|
| `a` | Play audio (vocabulary) |
| `s` | Stroke order (kanji) |
| `y` | Add a meaning synonym to your account |
| `n` | Edit your note |
| `g` | Jump to a related item from a list |
| `Tab` / `Enter` | Move between related-item chips and open one |
| `o` | Open on wanikani.com |
| `j` `k` | Scroll (vim keys, on by default) |
| `Esc` | Back |

### Reviews

Type the answer and press `Enter`. Readings convert romaji to kana as you type:
`nn` or `n'` gives ん, so 女 is `onnna` and 単位 is `tanni`.

| Key | Action |
|---|---|
| `Enter` | Check the answer, then continue |
| `Ctrl+Z` | Undo the last answer (until you continue) |
| `F1` | Item details, after you answered |
| `Esc` | Wrap up: finish the items already started, then quit. Press again to quit now |
| `F2` | In the popup window: open the full app in place |

A submission that fails to reach WaniKani is queued and sent on the next sync.

### Lessons

| Key | Action |
|---|---|
| `→` `←` (or `l` `h`) | Next / previous item |
| `Enter` | On the last item: start the quiz |
| `a` | Play audio |
| `s` | Stroke order |
| `Esc` | Leave lessons (nothing is recorded until the quiz) |

Within a batch, radicals come before the kanji that use them and kanji before their
vocabulary; the footer says what each item builds on.

### Lesson picker

| Key | Action |
|---|---|
| `Space` | Select or deselect |
| `a` | Select all / none |
| `t` | Cycle type filter |
| `Enter` | Start with the selection (or the highlighted item) |

## Config

`wk config` writes `~/.config/wanikani/config.toml` with every option and its default:
lightning mode, review order (`random`, `level`, `back_to_back`), mnemonic on a miss,
audio autoplay, lesson batch size, image height, theme (any Textual theme, e.g.
`textual-light`, `tokyo-night`), colour-blind SRS palette, vim keys, compact layout,
and the daemon's cadence, quiet hours, popup behaviour and terminal command.

## Daemon

`wk daemon` syncs every 10 minutes and, when reviews are due, sends a desktop
notification showing the next item. Clicking it opens a small terminal window with that
one review; when you finish, press `Enter` for one more, `Esc` to close, or `F2` for
the full app. Notifications come at most every 30 minutes and never during quiet hours
(23:00 to 08:00). The item is chosen to be the one you most need: leeches, low SRS
stages, long-overdue and weak items first, skipping anything answered in the last hour.

```sh
wk daemon --once        # try one cycle in the foreground
wk daemon install       # start it with your session (systemd user service / launchd agent)
wk daemon status
```

Cadence, quiet hours, popup behaviour and the terminal command live under `[daemon]`
in the config file; the daemon picks up changes without a restart.

## macOS

Everything works the same on macOS with ghostty, kitty or WezTerm (all three support the
kitty graphics protocol). Differences, all detected automatically:

- Notifications use `terminal-notifier` when installed (`brew install terminal-notifier`);
  a click then opens the popup. Without it, plain `osascript` notifications are shown and
  clicks do nothing.
- The popup opens in ghostty, kitty or WezTerm if found, otherwise in Terminal.app
  (no images there). `terminal = "..."` in the config overrides the choice.
- `wk daemon install` writes a launchd agent in `~/Library/LaunchAgents/` instead of a
  systemd unit; logs go to `~/.local/state/wanikani-tui/`.
- Audio plays through `afplay`; the CJK font comes from the system Hiragino faces.

`wk doctor` prints which backends were picked.

## tmux

Images reach the real terminal only with passthrough enabled:

```
set -g allow-passthrough on
```

Inside tmux the terminal's capability answers come from tmux itself, so `wk` assumes
kitty graphics when it can tell it is running under ghostty, kitty or WezTerm.
Elsewhere, or if images come out wrong, start with `wk --images tgp`.

For a due counter in the tmux status line:

```
set -g status-right '#(wk due --format tmux) %H:%M'
```

## Fonts

Kanji images are drawn with a system Japanese font (Noto Sans CJK on Linux, Hiragino on
macOS). The font is not bundled: it is 16 MB per weight, and your terminal needs its own
Japanese font anyway to show kana and kanji in text. `wk doctor` reports which font was
found and prints the install command for your system, e.g. `sudo apt install fonts-noto-cjk`
or `brew install --cask font-noto-sans-cjk-jp`. `WK_FONT=/path/to/font.ttc` overrides it.

## Development

```sh
uv run pytest                        # answer checking, SRS math, queue, core/retry queue, real-cache shapes
uv run python tests/drive.py out/    # drive the main screens headlessly, saves PNG screenshots
uv run python tests/drive2.py out/   # stats, picker, filters, synonyms, strokes, undo, popup
uv run python tests/pty_capture.py "r,a,enter" out.bin   # kitty-graphics traffic vs painted cells
```

## Licence and credits

MIT licence, see `LICENSE`. This is an unofficial client; WaniKani and its content belong to
Tofugu LLC and are used through the official API under your own account. Stroke-order
diagrams come from [KanjiVG](http://kanjivg.tagaini.net) by Ulrich Apel (CC BY-SA 3.0),
fetched on demand and cached locally. Kana conversion by
[wanakana-python](https://github.com/Starwort/wanakana-python); terminal images by
[textual-image](https://github.com/lnqs/textual-image).
