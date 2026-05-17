from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .compression import load_packed


PATH_TABLE_BYTES = 0x190
RELATIVE_VIEWPORT_X = -320 // 2
RELATIVE_VIEWPORT_Y = -192 // 2


class FlyingPathsFormatError(ValueError):
    """Raised when a GODS .PAT flying-path resource has an invalid layout."""


@dataclass(frozen=True)
class FlyingPath:
    index: int
    kind: str  # "absolute" or "relative"
    base_x: int
    base_y: int
    deltas: tuple[tuple[int, int], ...]
    table_tag: int
    byte_size: int

    @property
    def is_absolute(self) -> bool:
        return self.kind == "absolute"

    @property
    def is_relative(self) -> bool:
        return self.kind == "relative"

    def points_for_event_center(self, center_x: int, center_y: int) -> tuple[tuple[int, int], ...]:
        """Return path polyline points in map pixels.

        Kroah's viewer established the same rule used here:
        - absolute paths start directly at their map coordinate,
        - relative paths start in a 320x192 viewport centered on the trigger cell.
        """

        if self.is_absolute:
            x = self.base_x
            y = self.base_y
        else:
            x = center_x + RELATIVE_VIEWPORT_X + self.base_x
            y = center_y + RELATIVE_VIEWPORT_Y + self.base_y

        points: list[tuple[int, int]] = [(x, y)]
        for dx, dy in self.deltas:
            x += dx
            y += dy
            points.append((x, y))
        return tuple(points)


@dataclass(frozen=True)
class FlyingPathsData:
    path: Path
    packed_size: int
    unpacked_size: int
    paths: tuple[FlyingPath, ...]

    def get(self, index: int) -> FlyingPath | None:
        return self.paths[index] if 0 <= index < len(self.paths) else None


def _read_u16be(data: bytes, offset: int) -> int:
    if offset + 2 > len(data):
        raise FlyingPathsFormatError(f"unexpected EOF while reading u16 at 0x{offset:X}")
    return int.from_bytes(data[offset:offset+2], "big", signed=False)


def _read_s16be(data: bytes, offset: int) -> int:
    if offset + 2 > len(data):
        raise FlyingPathsFormatError(f"unexpected EOF while reading s16 at 0x{offset:X}")
    return int.from_bytes(data[offset:offset+2], "big", signed=True)


def _read_s32be(data: bytes, offset: int) -> int:
    if offset + 4 > len(data):
        raise FlyingPathsFormatError(f"unexpected EOF while reading s32 at 0x{offset:X}")
    return int.from_bytes(data[offset:offset+4], "big", signed=True)


def _read_u32be(data: bytes, offset: int) -> int:
    if offset + 4 > len(data):
        raise FlyingPathsFormatError(f"unexpected EOF while reading u32 at 0x{offset:X}")
    return int.from_bytes(data[offset:offset+4], "big", signed=False)


def _signed_nibble(value: int) -> int:
    value &= 0x0F
    return value - 16 if value & 0x08 else value


def parse_flying_paths(data: bytes, path: Path | None = None, packed_size: int | None = None) -> FlyingPathsData:
    if len(data) < PATH_TABLE_BYTES:
        raise FlyingPathsFormatError(f"flying path payload too short: {len(data)} bytes")

    records: list[tuple[int, int]] = []
    table_offset = 0
    while True:
        tag = _read_s32be(data, table_offset)
        size = _read_u32be(data, table_offset + 4)
        table_offset += 8
        if tag < 0:
            break
        records.append((tag, size))
        if table_offset > PATH_TABLE_BYTES:
            raise FlyingPathsFormatError("flying path record table overruns 0x190-byte header")

    payload_offset = PATH_TABLE_BYTES
    paths: list[FlyingPath] = []
    for index, (tag, size) in enumerate(records):
        if size < 4:
            raise FlyingPathsFormatError(f"path #{index} has impossible size {size}")
        end = payload_offset + size
        if end > len(data):
            raise FlyingPathsFormatError(f"path #{index} overruns payload: 0x{end:X} > 0x{len(data):X}")
        magic = _read_u16be(data, payload_offset)
        if magic == 0x2345:
            if size < 6:
                raise FlyingPathsFormatError(f"absolute path #{index} has impossible size {size}")
            kind = "absolute"
            base_x = _read_u16be(data, payload_offset + 2)
            base_y = _read_u16be(data, payload_offset + 4)
            delta_offset = payload_offset + 6
        else:
            kind = "relative"
            base_x = _read_s16be(data, payload_offset)
            base_y = _read_s16be(data, payload_offset + 2)
            delta_offset = payload_offset + 4

        deltas = tuple(
            (_signed_nibble(byte >> 4), _signed_nibble(byte))
            for byte in data[delta_offset:end]
        )
        paths.append(FlyingPath(index, kind, base_x, base_y, deltas, tag, size))
        payload_offset = end

    if payload_offset != len(data):
        raise FlyingPathsFormatError(
            f"flying path payload has {len(data) - payload_offset} trailing bytes after last path"
        )

    resolved_path = path or Path("<memory>.PAT")
    return FlyingPathsData(
        path=resolved_path,
        packed_size=packed_size if packed_size is not None else len(data),
        unpacked_size=len(data),
        paths=tuple(paths),
    )


def load_packed_flying_paths(path: str | Path) -> FlyingPathsData:
    packed = load_packed(path)
    return parse_flying_paths(packed.data, packed.path, packed.packed_size)
