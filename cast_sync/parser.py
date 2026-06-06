"""Parse and validate asciinema v2 .cast file headers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


class CastValidationError(ValueError):
    """Raised when a .cast file fails validation."""


@dataclass(frozen=True)
class CastMetadata:
    path: Path
    timestamp: int
    width: int
    height: int
    version: int

    @property
    def name(self) -> str:
        return self.path.name


def parse_cast_header(path: Path) -> CastMetadata:
    """Parse line 1 of an asciinema cast file and extract core metadata."""
    path = path.resolve()
    if not path.is_file():
        raise CastValidationError(f"File not found: {path}")
    if path.suffix.lower() != ".cast":
        raise CastValidationError(f"Not a .cast file: {path}")

    try:
        with path.open(encoding="utf-8") as fh:
            header_line = fh.readline()
    except OSError as exc:
        raise CastValidationError(f"Cannot read {path}: {exc}") from exc

    if not header_line.strip():
        raise CastValidationError(f"Empty file: {path}")

    try:
        header = json.loads(header_line)
    except json.JSONDecodeError as exc:
        raise CastValidationError(f"Invalid JSON header in {path}: {exc}") from exc

    version = header.get("version")
    if version != 2:
        raise CastValidationError(
            f"{path.name}: expected asciinema v2 format, got version={version!r}"
        )

    missing = [k for k in ("timestamp", "width", "height") if k not in header]
    if missing:
        raise CastValidationError(f"{path.name}: header missing fields: {', '.join(missing)}")

    try:
        timestamp = int(header["timestamp"])
        width = int(header["width"])
        height = int(header["height"])
    except (TypeError, ValueError) as exc:
        raise CastValidationError(f"{path.name}: invalid numeric header field: {exc}") from exc

    if width <= 0 or height <= 0:
        raise CastValidationError(f"{path.name}: width and height must be positive")

    return CastMetadata(
        path=path,
        timestamp=timestamp,
        width=width,
        height=height,
        version=version,
    )


def collect_cast_files(paths: list[str], directory: str | None) -> list[Path]:
    """Resolve explicit paths or scan a directory for .cast files."""
    if paths and directory:
        raise CastValidationError("Use either file paths or --dir, not both")

    if directory:
        root = Path(directory).resolve()
        if not root.is_dir():
            raise CastValidationError(f"Directory not found: {root}")
        files = sorted(root.glob("*.cast"))
        if not files:
            raise CastValidationError(f"No .cast files found in {root}")
        return files

    if not paths:
        raise CastValidationError("Provide .cast file paths or --dir <folder>")

    files = [Path(p).resolve() for p in paths]
    return files


def load_batch(paths: list[str], directory: str | None) -> list[CastMetadata]:
    """Collect and validate a batch of cast files."""
    files = collect_cast_files(paths, directory)
    return [parse_cast_header(f) for f in files]
