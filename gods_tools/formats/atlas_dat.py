from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import struct

from .compression import load_packed


class AtlasDatFormatError(ValueError):
    """Raised when a GODS atlas `.DAT` payload is malformed."""


@dataclass(frozen=True)
class AtlasRecord:
    index: int
    width_minus_one: int
    height_minus_one: int
    unknown: int
    x: int
    y: int

    @property
    def width(self) -> int:
        return self.width_minus_one + 1

    @property
    def height(self) -> int:
        return self.height_minus_one + 1


@dataclass(frozen=True)
class AtlasDat:
    source_path: Path
    records: tuple[AtlasRecord, ...]
    raw_payload: bytes

    @property
    def count(self) -> int:
        return len(self.records)


def parse_atlas_dat_payload(
    payload: bytes, source_path: str | Path = "<memory>"
) -> AtlasDat:
    if len(payload) < 2:
        raise AtlasDatFormatError("DAT payload is too short for the record count.")

    count = struct.unpack_from(">H", payload, 0)[0]
    expected = 2 + count * 10
    if len(payload) != expected:
        raise AtlasDatFormatError(
            f"DAT record count says {count}, expected {expected} bytes total, got {len(payload)}."
        )

    records: list[AtlasRecord] = []
    offset = 2
    for index in range(count):
        width_m1, height_m1, unknown, x, y = struct.unpack_from(">5H", payload, offset)
        offset += 10
        records.append(
            AtlasRecord(
                index=index,
                width_minus_one=width_m1,
                height_minus_one=height_m1,
                unknown=unknown,
                x=x,
                y=y,
            )
        )

    return AtlasDat(
        source_path=Path(source_path),
        records=tuple(records),
        raw_payload=payload,
    )


def load_packed_atlas_dat(path: str | Path) -> AtlasDat:
    packed = load_packed(path)
    return parse_atlas_dat_payload(packed.data, packed.path)
