"""Grid layout geometry for multi-stream playback."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class GridLayout:
    rows: int
    cols: int
    split: str  # "vertical" | "stacked" | "grid"

    @property
    def count(self) -> int:
        return self.rows * self.cols


@dataclass(frozen=True)
class StreamLayout:
    index: int
    row: int
    col: int
    width: int
    height: int
    font_size: float
    col_span: int = 1
    row_span: int = 1


def compute_grid(count: int) -> GridLayout:
    """Return layout dimensions for *count* simultaneous streams."""
    if count <= 0:
        raise ValueError("count must be positive")
    if count == 1:
        return GridLayout(rows=1, cols=1, split="grid")
    # Full-width stacked rows — much more readable than cramming side-by-side.
    if count in (2, 3):
        return GridLayout(rows=count, cols=1, split="stacked")
    if count == 4:
        return GridLayout(rows=2, cols=2, split="grid")

    cols = math.ceil(math.sqrt(count))
    rows = math.ceil(count / cols)
    return GridLayout(rows=rows, cols=cols, split="grid")


def compute_stream_layouts(
    widths: list[int],
    heights: list[int],
    viewport_w: int = 1920,
    viewport_h: int = 1080,
    chrome_h: int = 118,
) -> list[StreamLayout]:
    """
    Place streams on a grid and pick a readable font size.

    Panes scroll vertically, so we prefer a fixed comfortable font (14px) and
    only shrink when the terminal is too wide to fit the cell.
    """
    count = len(widths)
    grid = compute_grid(count)
    cell_w = viewport_w // grid.cols
    cell_h = (viewport_h - chrome_h) // grid.rows

    max_w = max(widths)

    readable = 14.0
    minimum = 12.0
    # Monospace char width ≈ 0.6 × font-size in px
    font_by_width = cell_w / (max_w * 0.6)
    if font_by_width >= readable:
        font_size = readable
    else:
        font_size = max(minimum, font_by_width)

    layouts: list[StreamLayout] = []
    for i in range(count):
        row = i // grid.cols
        col = i % grid.cols
        layouts.append(
            StreamLayout(
                index=i,
                row=row,
                col=col,
                width=widths[i],
                height=heights[i],
                font_size=round(font_size, 1),
            )
        )
    return layouts
