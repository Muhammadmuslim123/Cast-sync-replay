"""Option B: spawn native terminal windows with time-synced asciinema play."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from .layout import compute_grid
from .timeline import SyncedStream


class NativePlaybackError(RuntimeError):
    pass


def _require(cmd: str) -> str:
    path = shutil.which(cmd)
    if not path:
        raise NativePlaybackError(f"Required command not found: {cmd}")
    return path


def _screen_size() -> tuple[int, int]:
    try:
        out = subprocess.check_output(["xdotool", "getdisplaygeometry"], text=True)
        w, h = out.strip().split()
        return int(w), int(h)
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError):
        return 1920, 1080


def _window_rects(count: int, screen_w: int, screen_h: int) -> list[tuple[int, int, int, int]]:
    """Return (x, y, width, height) for each stream window."""
    grid = compute_grid(count)
    margin = 8
    usable_w = screen_w - margin * (grid.cols + 1)
    usable_h = screen_h - margin * (grid.rows + 1) - 40
    cell_w = usable_w // grid.cols
    cell_h = usable_h // grid.rows

    rects: list[tuple[int, int, int, int]] = []
    for i in range(count):
        row = i // grid.cols
        col = i % grid.cols
        x = margin + col * (cell_w + margin)
        y = margin + row * (cell_h + margin)
        rects.append((x, y, cell_w, cell_h))
    return rects


def _spawn_terminal(
    title: str,
    command: str,
    geom: tuple[int, int, int, int] | None,
) -> subprocess.Popen:
    """Launch a terminal running *command* and optionally position it."""
    x, y, w, h = geom or (0, 0, 800, 600)
    cols = max(40, w // 8)
    rows = max(10, h // 16)

    env = os.environ.copy()
    env["CAST_SYNC_TITLE"] = title

    if shutil.which("gnome-terminal"):
        proc = subprocess.Popen(
            [
                "gnome-terminal",
                "--title",
                title,
                "--geometry",
                f"{cols}x{rows}+{x}+{y}",
                "--",
                "bash",
                "-lc",
                command,
            ],
            env=env,
            start_new_session=True,
        )
    elif shutil.which("xterm"):
        proc = subprocess.Popen(
            [
                "xterm",
                "-title",
                title,
                "-geometry",
                f"{cols}x{rows}+{x}+{y}",
                "-e",
                "bash",
                "-lc",
                command,
            ],
            env=env,
            start_new_session=True,
        )
    else:
        raise NativePlaybackError(
            "No supported terminal emulator found (need gnome-terminal or xterm)"
        )

    if shutil.which("wmctrl"):
        # Give the window manager a moment to map the new window.
        time.sleep(0.4)
        subprocess.run(
            ["wmctrl", "-r", title, "-e", f"0,{x},{y},{w},{h}"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    return proc


def play_native(
    streams: list[SyncedStream],
    *,
    speed: float = 1.0,
) -> None:
    """
    Spawn one terminal per stream, sleeping D_i/speed seconds before playback.

    Press Ctrl+C in the controller to terminate all child terminals.
    """
    if not shutil.which("asciinema"):
        raise NativePlaybackError("asciinema CLI not found (install: pip install asciinema)")

    _require("bash")
    screen_w, screen_h = _screen_size()
    rects = _window_rects(len(streams), screen_w, screen_h)

    procs: list[subprocess.Popen] = []
    speed = max(0.25, speed)

    print(f"Spawning {len(streams)} native terminal(s) at {speed}× speed")
    print("Press Ctrl+C to stop all playback.\n")

    for i, stream in enumerate(streams):
        delay = stream.delay / speed
        cast_path = stream.path
        title = f"cast-sync:{stream.name}"
        x, y, w, h = rects[i]

        if delay > 0:
            inner = f"sleep {delay:.3f} && asciinema play -s {speed} {shlex_quote(str(cast_path))}"
        else:
            inner = f"asciinema play -s {speed} {shlex_quote(str(cast_path))}"

        # Keep terminal open after playback ends.
        command = f"{inner}; echo; echo '[cast-sync] finished — press Enter to close'; read"

        proc = _spawn_terminal(title, command, (x, y, w, h))
        procs.append(proc)
        tag = "primary" if stream.is_primary else f"+{stream.delay:.0f}s delay"
        print(f"  [{i + 1}] {stream.name} ({tag})")

    def _cleanup(*_args):
        print("\nTerminating playback terminals...")
        for proc in procs:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        time.sleep(0.3)
        for proc in procs:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        sys.exit(0)

    signal.signal(signal.SIGINT, _cleanup)
    signal.signal(signal.SIGTERM, _cleanup)

    try:
        while True:
            time.sleep(1)
            if all(p.poll() is not None for p in procs):
                print("All terminals closed.")
                break
    except KeyboardInterrupt:
        _cleanup()


def shlex_quote(s: str) -> str:
    """Minimal shell quoting without importing shlex for path safety."""
    if not s:
        return "''"
    if all(c.isalnum() or c in "/._-+:" for c in s):
        return s
    return "'" + s.replace("'", "'\"'\"'") + "'"
