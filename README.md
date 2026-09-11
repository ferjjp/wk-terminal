# wanikani-tui

WaniKani in your terminal: dashboard, item browser, reviews and lessons, with kanji and
radical images drawn through the kitty graphics protocol (ghostty, kitty, WezTerm…).

## Setup

1. Create a personal access token at
   <https://www.wanikani.com/settings/personal_access_tokens> with the
   `assignments:start` and `reviews:create` permissions enabled.
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

   or run it from the checkout with `uv run wk`.

The first start downloads every subject (~10 requests) into
`~/.local/share/wanikani-tui/cache.sqlite3`. Later starts sync incrementally in the
background.

## Usage

```
wk                 # open the TUI (syncs in the background)
wk --no-sync       # offline browsing of the cache
wk --full-sync     # re-download everything
wk sync            # sync only, print counts (handy in cron)
wk --images tgp    # force kitty graphics if auto-detection fails (e.g. inside tmux)
wk --images none   # plain text, no images
```

Keys on the dashboard: `r` reviews, `l` lessons, `b` browse, `s` sync, `q` quit.
Browse: `/` search, `t` cycle type filter, `Enter` open item. Item view: `g` jump to a
related item, `o` open on wanikani.com. Reviews: type the answer and press `Enter`;
readings convert romaji to kana as you type (`nn` gives ん). `Esc` wraps up the
current batch, `Esc` again quits. `F1` shows the item after you answered.

## tmux

Images reach the real terminal only with passthrough enabled:

```
set -g allow-passthrough on
```

Inside tmux the terminal's capability answer never reaches the app, so `wk` assumes kitty
graphics when it can tell it is running under ghostty, kitty or WezTerm. Elsewhere, or if
images come out as coloured blocks, start with `wk --images tgp`.

## Development

```sh
uv run pytest            # answer checking, SRS math, queue logic
uv run python tests/drive.py out/   # drive every screen headlessly, saves PNG screenshots
```
