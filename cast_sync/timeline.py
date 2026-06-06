"""Timeline alignment: T_min and per-stream delay offsets."""

from __future__ import annotations

from dataclasses import dataclass

from .parser import CastMetadata


@dataclass(frozen=True)
class SyncedStream:
    metadata: CastMetadata
    delay: float  # D_i = T_i - T_min (seconds)
    is_primary: bool

    @property
    def path(self):
        return self.metadata.path

    @property
    def name(self) -> str:
        return self.metadata.name


def align_timeline(metadata_list: list[CastMetadata]) -> list[SyncedStream]:
    """Compute D_i offsets relative to the earliest session timestamp."""
    if not metadata_list:
        raise ValueError("No cast files to align")

    t_min = min(m.timestamp for m in metadata_list)
    streams: list[SyncedStream] = []

    for meta in sorted(metadata_list, key=lambda m: m.timestamp):
        delay = float(meta.timestamp - t_min)
        streams.append(
            SyncedStream(
                metadata=meta,
                delay=delay,
                is_primary=meta.timestamp == t_min,
            )
        )

    return streams
