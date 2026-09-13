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
   uv tool install --editable .
   ```

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

Dashboard: `r` reviews, `l` lessons, `L` pick lessons, `b` browse, `e` leeches, `t` stats,
`s` sync, `q` quit.
Browse: `/` search, `t` type filter, `f` cycle filter (all, due in 24 h, leeches, SRS group),
`Enter` open.
Item: `a` audio, `s` stroke order (kanji), `y` add synonym, `n` note, `g` related, `o` open
on wanikani.com, `Tab` moves between related-item chips, `Enter` opens one.
Reviews: type and press `Enter`; readings convert romaji to kana as you type (`nn` gives
ん). `Ctrl+Z` undoes the last answer until you continue. `F1` shows the item after you
answered. `Esc` wraps up the current batch, `Esc` again quits. Failed submissions are
queued and sent on the next sync.
Lessons: `←`/`→` (or `h`/`l`) navigate, `Enter` on the last page starts the quiz. Within
a batch, radicals come before the kanji that use them and kanji before their vocabulary;
the footer says what each item builds on.

All keys can be changed under `[keys]` in the config file.

## Config

`wk config` writes `~/.config/wanikani/config.toml` with every option and its default:
lightning mode, review order (`random`, `level`, `back_to_back`), mnemonic on a miss,
audio autoplay, lesson batch size, image height, theme (any Textual theme, e.g.
`textual-light`, `tokyo-night`), colour-blind SRS palette, vim keys, compact layout,
and the daemon's cadence, quiet hours, popup behaviour and terminal command.

## Daemon

`wk daemon` refreshes assignments every 10 minutes and, when reviews are due, sends a
desktop notification (over D-Bus, so clicks work on GNOME, KDE, mako, dunst…) at most
every 30 minutes and not during quiet hours. Clicking the notification, or its
**Review now** button, opens `wk pop` in a small ghostty window with one review, or one
new item when nothing is due. The review is chosen to be the one you most need: leeches,
low SRS stages, long-overdue and weak-accuracy items score highest, kanji slightly above
vocabulary, and anything you answered in the last hour is skipped
(`popup_pick = "oldest"` restores plain oldest-first). Inside that window `F2` opens the full
interface in place. When you finish, a prompt offers one more (`Enter`), close (`Esc`) or the full app (`F2`).
With `popup = "auto"` the window opens without asking; with
`popup = "none"` you only get the notification. `notify_lessons = true` also nudges when
lessons are waiting.

```sh
wk daemon --once        # try one cycle in the foreground
wk daemon install       # ~/.config/systemd/user/wanikani-tui.service, enabled and started
journalctl --user -u wanikani-tui -f
```

The popup command is configurable (`terminal = ...`), so any terminal that can run a
command in a new window works. The daemon reloads `config.toml` whenever it changes.

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
