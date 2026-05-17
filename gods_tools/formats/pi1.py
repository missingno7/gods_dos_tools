from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import struct

from PIL import Image

from .compression import load_packed

PI1_WIDTH = 320
PI1_HEIGHT = 200
PI1_PALETTE_COLORS = 16
PI1_HEADER_SIZE = 2 + PI1_PALETTE_COLORS * 2
PI1_BITMAP_SIZE = PI1_WIDTH * PI1_HEIGHT // 2  # 4bpp planar
PI1_EXPECTED_SIZE = PI1_HEADER_SIZE + PI1_BITMAP_SIZE


class Pi1FormatError(ValueError):
    """Raised when a decompressed PI1 payload does not match expected layout."""


@dataclass(frozen=True)
class Pi1Image:
    source_path: Path
    resolution: int
    palette_words: tuple[int, ...]
    pixels: bytes  # one palette index per pixel, row-major
    raw_payload: bytes

    @property
    def width(self) -> int:
        return PI1_WIDTH

    @property
    def height(self) -> int:
        return PI1_HEIGHT

    @property
    def rgb_palette(self) -> list[int]:
        palette: list[int] = []
        for word in self.palette_words:
            # Atari ST / DEGAS palette word layout: 0x0RGB, each channel 0..7.
            r = ((word >> 8) & 0x7) * 255 // 7
            g = ((word >> 4) & 0x7) * 255 // 7
            b = (word & 0x7) * 255 // 7
            palette.extend((r, g, b))
        # Pillow palette entries must be padded to 256 colors.
        palette.extend([0, 0, 0] * (256 - PI1_PALETTE_COLORS))
        return palette

    def to_pillow(self) -> Image.Image:
        image = Image.frombytes("P", (self.width, self.height), self.pixels)
        image.putpalette(self.rgb_palette)
        return image


def parse_pi1_payload(payload: bytes, source_path: str | Path = "<memory>") -> Pi1Image:
    if len(payload) != PI1_EXPECTED_SIZE:
        raise Pi1FormatError(
            f"Expected {PI1_EXPECTED_SIZE} bytes after unpacking PI1, got {len(payload)}."
        )

    resolution = struct.unpack_from(">H", payload, 0)[0]
    palette_words = struct.unpack_from(">16H", payload, 2)
    planar = payload[PI1_HEADER_SIZE:]

    pixels = bytearray(PI1_WIDTH * PI1_HEIGHT)
    out_index = 0
    offset = 0
    # DEGAS low-res screen: 20 groups * 16 pixels per line, four 16-bit planes per group.
    for _y in range(PI1_HEIGHT):
        for _group in range(PI1_WIDTH // 16):
            p0, p1, p2, p3 = struct.unpack_from(">4H", planar, offset)
            offset += 8
            for bit in range(15, -1, -1):
                value = (
                    ((p0 >> bit) & 1)
                    | (((p1 >> bit) & 1) << 1)
                    | (((p2 >> bit) & 1) << 2)
                    | (((p3 >> bit) & 1) << 3)
                )
                pixels[out_index] = value
                out_index += 1

    return Pi1Image(
        source_path=Path(source_path),
        resolution=resolution,
        palette_words=tuple(palette_words),
        pixels=bytes(pixels),
        raw_payload=payload,
    )


def load_packed_pi1(path: str | Path) -> Pi1Image:
    packed = load_packed(path)
    return parse_pi1_payload(packed.data, packed.path)
