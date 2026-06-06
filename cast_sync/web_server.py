"""Local HTTP server for the web-based sync player (Option A)."""

from __future__ import annotations

import json
import mimetypes
import signal
import socket
import threading
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import quote

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
        if self.path == "/api/config":
            body = json.dumps(self.config).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path.startswith("/casts/"):
            return super().do_GET()

        if self.path in ("/", "/index.html", "/player.js", "/styles.css"):
            if self.path == "/":
                self.path = "/index.html"
            return super().do_GET()

        self.send_error(404)

    def do_HEAD(self) -> None:  # noqa: N802
        if self.path.startswith("/casts/"):
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
        if path.startswith("/casts/"):
            rel = path[len("/casts/") :]
            # Path segments were URL-encoded file names; resolve under cast root.
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

    return {
        "cast_root": str(cast_root.resolve()),
        "port": port,
        "grid": {"rows": grid.rows, "cols": grid.cols, "split": grid.split},
        "streams": [
            {
                "id": i,
                "name": s.name,
                "url": f"/casts/{quote(s.path.name)}",
                "delay": s.delay,
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
        ],
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
