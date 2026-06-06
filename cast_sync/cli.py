#!/usr/bin/env python3
"""CLI for time-synced multi-stream asciinema replay."""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

from . import __version__
from .native import NativePlaybackError, play_native
from .parser import CastValidationError, load_batch
from .timeline import align_timeline
from .web_server import serve


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cast-sync",
        description=(
            "Play multiple asciinema .cast recordings in time-synced layout. "
            "Timestamps in cast headers determine start delays automatically."
        ),
    )
    parser.add_argument(
        "casts",
        nargs="*",
        help="Paths to .cast files (or use --dir to scan a folder)",
    )
    parser.add_argument(
        "--dir",
        "-d",
        metavar="FOLDER",
        help="Scan a directory for all .cast files",
    )
    parser.add_argument(
        "--mode",
        "-m",
        choices=("web", "native"),
        default="web",
        help="Playback mode: web (asciinema-player, default) or native (terminal spawner)",
    )
    parser.add_argument(
        "--port",
        "-p",
        type=int,
        default=None,
        help="HTTP port for web mode (default: random free port)",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not open a browser automatically in web mode",
    )
    parser.add_argument(
        "--speed",
        "-s",
        type=float,
        default=1.0,
        help="Initial playback speed for native mode (web mode has UI controls)",
    )
    parser.add_argument(
        "--version",
        "-V",
        action="version",
        version=f"cast-sync-replay {__version__}",
    )
    return parser


def _normalize_cast_paths(streams):
    """
    If casts live in different directories, symlink them into a temp folder
    so the web server can serve them under /casts/<name>.
    """
    parents = {s.path.parent.resolve() for s in streams}
    if len(parents) == 1:
        return streams, None

    tmp = Path(tempfile.mkdtemp(prefix="cast-sync-"))
    mapping: dict[str, Path] = {}
    for s in streams:
        dest = tmp / s.path.name
        if dest.exists():
            dest = tmp / f"{s.path.stem}_{hash(s.path) & 0xFFFF}{s.path.suffix}"
        dest.symlink_to(s.path)
        mapping[s.path.name] = dest

    # Rebuild stream list with symlink paths for serving; delays unchanged.
    from .parser import CastMetadata
    from .timeline import SyncedStream

    normalized: list[SyncedStream] = []
    for s in streams:
        link = tmp / s.path.name
        if not link.exists():
            link = next(p for p in tmp.iterdir() if p.resolve() == s.path.resolve())
        meta = CastMetadata(
            path=link,
            timestamp=s.metadata.timestamp,
            width=s.metadata.width,
            height=s.metadata.height,
            version=s.metadata.version,
        )
        normalized.append(
            SyncedStream(metadata=meta, delay=s.delay, is_primary=s.is_primary)
        )
    return normalized, tmp


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv[1:] if argv is not None else None)

    tmp_dir: Path | None = None
    try:
        metadata = load_batch(args.casts, args.dir)
        streams = align_timeline(metadata)
        streams, tmp_dir = _normalize_cast_paths(streams)
    except CastValidationError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    try:
        if args.mode == "web":
            serve(
                streams,
                port=args.port,
                open_browser=not args.no_browser,
            )
        else:
            play_native(streams, speed=args.speed)
    except (NativePlaybackError, OSError, KeyboardInterrupt) as exc:
        if isinstance(exc, KeyboardInterrupt):
            return 0
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        if tmp_dir and tmp_dir.exists():
            import shutil

            shutil.rmtree(tmp_dir, ignore_errors=True)

    return 0


def main_here() -> int:
    """Entry point: replay all .cast files in the current working directory."""
    # Strip a redundant --dir if someone runs: cast-sync-here --dir .
    args = list(sys.argv[1:])
    if args[:2] == ["--dir", "."]:
        args = args[2:]
    return main(["cast-sync", "--dir", os.getcwd(), *args])


if __name__ == "__main__":
    raise SystemExit(main())
