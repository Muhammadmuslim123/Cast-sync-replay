# Cast Sync Replay

**Time-synced multi-stream replay for asciinema recordings — built for lab notes, tmux workflows, and copy-paste friendly review.**

When you're working through Hack The Box, Proving Grounds, or any hands-on lab, you often run **multiple tmux panes** at once: a shell, nmap, a listener, notes, etc. [asciinema](https://asciinema.org/) is excellent at capturing what you typed and what came back — but replaying several recordings that started at different times is painful, and copying commands/output from the default player never feels like a real terminal.

**Cast Sync Replay** fixes that.

---

## The problem

| Pain point | What happens today |
|------------|-------------------|
| **Multiple panes, multiple recordings** | Each tmux split can produce its own `.cast` file, all starting at slightly different times. |
| **Manual alignment** | You have to guess offsets or open players side-by-side and mentally sync them. |
| **Bad copy/paste** | Native `asciinema play` and some embeds make it awkward to select and copy output into lab writeups. |
| **Lab note workflow** | You want to scroll back, jump to a moment, and copy a command *and* its output — not watch a linear movie. |

---

## The solution

Point the tool at a folder (or a list of `.cast` files). It:

1. **Parses** each file's asciinema v2 header (`timestamp`, `width`, `height`)
2. **Finds** the earliest session (`T_min`) as the primary timeline
3. **Calculates** per-stream delays: `D_i = T_i - T_min`
4. **Plays** everything in a synced layout — web UI by default, with scroll, timeline scrubbing, and normal browser copy/paste

No manual offset configuration. Drop files in a folder, run one command, review your lab session as it actually happened across panes.

---

## Why it was created

This project came out of a personal lab-notes workflow:

- Record sessions with **asciinema** while working in **tmux** on HTB/PG boxes
- Use **per-split recording** so each pane is captured independently
- After the box, **replay all recordings together** to write up methodology — copying commands, output, and timelines into notes

asciinema handles recording well; synchronized multi-stream replay with usable copy/paste did not exist in one small tool. Cast Sync Replay fills that gap.

---

## Features

- **Automatic timeline sync** from cast header timestamps
- **Web player (recommended)** — local HTML/JS via [asciinema-player](https://github.com/asciinema/asciinema-player)
  - Full-width stacked layout for 2–3 streams (readable 14px font)
  - Global timeline + ±10s seek (`←` / `→` keys, `Space` to play/pause)
  - Scroll inside each pane; select and copy text like a normal webpage
- **Native mode** — spawns real terminals with `sleep D_i && asciinema play` (optional)
- **Speed control** — delays scale proportionally so sync is preserved
- **CLI** — `cast-sync` and `cast-sync-here` for replaying the current directory

---

## Requirements

- Python 3.10+
- **Web mode:** modern browser (no extra deps)
- **Native mode:** `asciinema` CLI, `gnome-terminal` or `xterm`, optionally `wmctrl` / `xdotool`

---

## Install

### pipx (recommended — global CLI)

```bash
git clone https://github.com/muslimaamir72/cast-sync-replay.git
cd cast-sync-replay
pipx install -e .
```

### venv

```bash
cd cast-sync-replay
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Add to your shell (`~/.zshrc`):

```bash
export PATH="$HOME/.local/bin:$PATH"
alias cast-sync-here='cast-sync --dir "$PWD"'
```

---

## Usage

### Replay all recordings in the current folder

```bash
cd ~/Documents/PG_Labs/SoSimple
cast-sync-here
```

### Replay a specific folder or files

```bash
cast-sync --dir ~/Documents/HTB_Labs/Unified/
cast-sync pane1.cast pane2.cast pane3.cast
```

### Native terminal mode

```bash
cast-sync --dir ./recordings/ --mode native
```

Stop the server or controller with **Ctrl+C**.

### Web player controls

| Control | Action |
|---------|--------|
| **Play / Pause** | Start or stop synced playback |
| **Timeline** | Drag to any point in the session |
| **−10s / +10s** | Jump backward or forward |
| **← / →** | Seek 10s (Shift + arrow = 30s) |
| **Space** | Toggle play/pause |
| **Scroll** | Inside each pane to read long output |
| **Select text** | Copy commands/output into your notes |

---

## How sync works

Each `.cast` file stores a Unix `timestamp` in line 1 (when recording started).

| Symbol | Meaning |
|--------|---------|
| `T_min` | Lowest timestamp across all files — plays immediately |
| `D_i` | `T_i - T_min` — seconds to wait before stream *i* starts |
| Speed `s` | Virtual timeline runs at `s×` rate; delays stay proportional |

Example: if pane B started 28 seconds after pane A, pane B's playback begins 28 seconds into the synced session.

---

## Typical workflow (tmux + lab recording)

1. Work in tmux on a box; record splits with asciinema (e.g. `lab-on` / per-split prompts)
2. Each pane saves `session_*.cast` in the box folder
3. After the lab: `cd` to that folder → `cast-sync-here`
4. Pause, scrub the timeline, scroll, and copy into your writeup

---

## Project layout

```
cast_sync/
  parser.py       # v2 header validation & metadata
  timeline.py     # T_min / D_i alignment
  layout.py       # grid geometry & font sizing
  web_server.py   # local HTTP server
  native.py       # optional terminal spawner
  web/            # player UI (HTML, CSS, JS)
  cli.py          # entry points: cast-sync, cast-sync-here
```

---

## License

MIT
