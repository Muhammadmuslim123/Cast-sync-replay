"""Local HTTP server for the web-based sync player (Option A)."""

from __future__ import annotations

import json
import mimetypes
import signal
import socket
import threading
import webbrowser
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlparse

from .layout import GridLayout, compute_grid, compute_stream_layouts
from .timeline import SyncedStream

_PKG_DIR = Path(__file__).resolve().parent
_STATIC_DIR = _PKG_DIR / "web"

# asciinema-player fetches casts via XHR; ndjson MIME helps some browsers.
mimetypes.add_type("application/x-ndjson", ".cast")
mimetypes.add_type("application/json", ".cast")


class _ReplayHandler(SimpleHTTPRequestHandler):
    config: dict[str, Any] = {}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(_STATIC_DIR), **kwargs)

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        if self.path.startswith("/api/"):
            super().log_message(format, *args)

    def do_GET(self) -> None:  # noqa: N802
        route = urlparse(self.path).path
        if route == "/api/config":
            body = json.dumps(self.config).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if route.startswith("/casts/"):
            return super().do_GET()

        if route in ("/", "/index.html", "/player.js", "/styles.css"):
            if route == "/":
                self.path = "/index.html"
            else:
                self.path = route
            return super().do_GET()

        self.send_error(404)

    def do_HEAD(self) -> None:  # noqa: N802
        if urlparse(self.path).path.startswith("/casts/"):
            self._serve_cast_head()
            return
        super().do_HEAD()

    def _serve_cast_head(self) -> None:
        path = self.translate_path(self.path)
        target = Path(path)
        if not target.is_file():
            self.send_error(404)
            return
        ctype = mimetypes.guess_type(str(target))[0] or "application/x-ndjson"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(target.stat().st_size))
        self.end_headers()

    def translate_path(self, path: str) -> str:
        route = urlparse(path).path
        if route.startswith("/casts/"):
            rel = unquote(route[len("/casts/") :])
            cast_root = Path(self.config.get("cast_root", ""))
            target = (cast_root / rel).resolve()
            if not str(target).startswith(str(cast_root.resolve())):
                return str(_STATIC_DIR / "__missing__")
            return str(target)
        return super().translate_path(path)


def build_config(
    streams: list[SyncedStream],
    cast_root: Path,
    port: int,
) -> dict[str, Any]:
    grid: GridLayout = compute_grid(len(streams))
    layouts = compute_stream_layouts(
        [s.metadata.width for s in streams],
        [s.metadata.height for s in streams],
    )

    stream_configs = [
        {
            "id": i,
            "name": s.name,
            "url": f"/casts/{quote(s.path.name, safe='')}",
            "delay": s.delay,
            "timestamp": s.metadata.timestamp,
            "started_at": datetime.fromtimestamp(s.metadata.timestamp).strftime(
                "%Y-%m-%d %H:%M"
            ),
            "is_primary": s.is_primary,
            "width": s.metadata.width,
            "height": s.metadata.height,
            "row": layouts[i].row,
            "col": layouts[i].col,
            "col_span": layouts[i].col_span,
            "row_span": layouts[i].row_span,
            "font_size": layouts[i].font_size,
        }
        for i, s in enumerate(streams)
    ]

    return {
        "cast_root": str(cast_root.resolve()),
        "port": port,
        "grid": {"rows": grid.rows, "cols": grid.cols, "split": grid.split},
        "streams": stream_configs,
        "sessions": build_sessions(stream_configs),
    }


def build_sessions(streams: list[dict[str, Any]], gap_seconds: int = 6 * 60 * 60) -> list[dict[str, Any]]:
    """Group recordings into review sessions when their start times are far apart."""
    sessions: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []

    for stream in sorted(streams, key=lambda s: s["timestamp"]):
        if current and stream["timestamp"] - current[-1]["timestamp"] > gap_seconds:
            sessions.append(_session_config(len(sessions), current))
            current = []
        current.append(stream)

    if current:
        sessions.append(_session_config(len(sessions), current))

    return sessions


def _session_config(index: int, streams: list[dict[str, Any]]) -> dict[str, Any]:
    start = streams[0]["timestamp"]
    end = streams[-1]["timestamp"]
    start_label = datetime.fromtimestamp(start).strftime("%a %b %-d, %Y %H:%M")
    if start == end:
        label = f"Session {index + 1}: {start_label}"
    else:
        end_label = datetime.fromtimestamp(end).strftime("%H:%M")
        label = f"Session {index + 1}: {start_label} to {end_label}"
    return {
        "id": index,
        "label": label,
        "start": start,
        "end": end,
        "stream_ids": [s["id"] for s in streams],
        "count": len(streams),
    }


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def serve(
    streams: list[SyncedStream],
    *,
    port: int | None = None,
    open_browser: bool = True,
) -> None:
    """Start the web player and block until interrupted."""
    if not streams:
        raise ValueError("No streams to serve")

    cast_root = streams[0].path.parent
    chosen_port = port or _free_port()
    config = build_config(streams, cast_root, chosen_port)

    handler = _ReplayHandler
    handler.config = config

    server = ThreadingHTTPServer(("127.0.0.1", chosen_port), handler)
    server.daemon_threads = True

    url = f"http://127.0.0.1:{chosen_port}/"
    print(f"Serving cast-sync replay at {url}")
    print(f"  Streams: {len(streams)}  |  T_min primary: {streams[0].name}")
    for s in streams:
        tag = " (primary)" if s.is_primary else ""
        print(f"    {s.name}: delay {s.delay:.0f}s{tag}")

    stop = threading.Event()

    def _shutdown(*_args):
        if stop.is_set():
            return
        stop.set()
        print("\nShutting down web server...")
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    if open_browser:
        webbrowser.open(url)

    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        server.server_close()
