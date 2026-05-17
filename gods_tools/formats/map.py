from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import struct

from .compression import load_packed

MAP_WIDTH_CELLS = 128
MAP_HEIGHT_CELLS = 64
MAP_CELL_WIDTH = 32
MAP_CELL_HEIGHT = 16
MAP_LAYER_SIZE = MAP_WIDTH_CELLS * MAP_HEIGHT_CELLS
MAP_ITEM_COUNT = 200
MAP_ITEM_SIZE = 6
PUZZLE_STRING_COUNT = 40
PUZZLE_STRING_POINTER_TABLE_SIZE = PUZZLE_STRING_COUNT * 4
PUZZLE_STRING_TEXT_AREA_SIZE = PUZZLE_STRING_COUNT * 42
MAP_PUZZLE_COUNT = 100
MAP_PUZZLE_SIZE = 24


class MapFormatError(ValueError):
    """Raised when a packed DOS GODS map payload is malformed."""


@dataclass(frozen=True)
class RasterInfo:
    color_count: int
    height: int
    palette_words: tuple[int, ...]


@dataclass(frozen=True)
class MapItem:
    index: int
    pixel_x: int
    pixel_y: int
    object_or_weapon_info_index: int

    @property
    def is_empty(self) -> bool:
        return self.object_or_weapon_info_index == 0xFFFF

    @property
    def is_weapon(self) -> bool:
        return (not self.is_empty) and self.object_or_weapon_info_index >= 192

    @property
    def is_object(self) -> bool:
        return (not self.is_empty) and not self.is_weapon


@dataclass(frozen=True)
class MapPuzzle:
    index: int
    condition_function_indices: tuple[int, int, int]
    condition_params: tuple[int, int, int]
    pixel_x: int
    pixel_y: int
    effect_function_index_remove: int
    effect_param: int
    string_index: int
    trailing_word: int

    @property
    def effect_function_index(self) -> int:
        return self.effect_function_index_remove & 0x7FFF

    @property
    def remove_after_effect(self) -> bool:
        return bool(self.effect_function_index_remove & 0x8000)

    @property
    def appears_unused(self) -> bool:
        return (
            self.condition_function_indices == (0, 0, 0)
            and self.condition_params == (0, 0, 0)
            and self.pixel_x == 0
            and self.pixel_y == 0
            and self.effect_function_index_remove == 0
            and self.effect_param == 0
            and self.string_index == 0
            and self.trailing_word == 0
        )


@dataclass(frozen=True)
class GodsMap:
    source_path: Path
    packed_size: int
    raw_payload: bytes
    raster: RasterInfo
    layer_a: bytes
    layer_b: bytes
    items: tuple[MapItem, ...]
    puzzle_strings: tuple[str | None, ...]
    puzzles: tuple[MapPuzzle, ...]

    @property
    def unpacked_size(self) -> int:
        return len(self.raw_payload)

    @property
    def layer_a_max_tile(self) -> int:
        return max(self.layer_a, default=0)

    @property
    def layer_a_nonzero_count(self) -> int:
        return sum(value != 0 for value in self.layer_a)

    @property
    def active_items(self) -> tuple[MapItem, ...]:
        return tuple(item for item in self.items if not item.is_empty)

    @property
    def active_puzzles(self) -> tuple[MapPuzzle, ...]:
        return tuple(puzzle for puzzle in self.puzzles if not puzzle.appears_unused)

    def layer_a_at(self, x: int, y: int) -> int:
        return self.layer_a[y * MAP_WIDTH_CELLS + x]

    def layer_b_at(self, x: int, y: int) -> int:
        return self.layer_b[y * MAP_WIDTH_CELLS + x]


def _read_c_string(payload: bytes, offset: int) -> str:
    if offset < 0 or offset >= len(payload):
        raise MapFormatError(f"Puzzle string offset {offset} is outside payload.")
    end = payload.find(b"\x00", offset)
    if end == -1:
        end = len(payload)
    return payload[offset:end].decode("latin-1", errors="replace")


def parse_map_payload(
    payload: bytes,
    source_path: str | Path = "<memory>",
    packed_size: int | None = None,
) -> GodsMap:
    if len(payload) < 4:
        raise MapFormatError("Map payload is too short for the raster header.")

    offset = 0
    raster_color_count, raster_height = struct.unpack_from(">HH", payload, offset)
    offset += 4

    palette_bytes = raster_color_count * 2
    if offset + palette_bytes > len(payload):
        raise MapFormatError("Map payload ends inside the raster palette.")
    raster_palette = struct.unpack_from(f">{raster_color_count}H", payload, offset)
    offset += palette_bytes

    if offset + MAP_LAYER_SIZE > len(payload):
        raise MapFormatError("Map payload ends inside layer A.")
    layer_a = payload[offset : offset + MAP_LAYER_SIZE]
    offset += MAP_LAYER_SIZE

    if offset + MAP_LAYER_SIZE > len(payload):
        raise MapFormatError("Map payload ends inside layer B.")
    layer_b = payload[offset : offset + MAP_LAYER_SIZE]
    offset += MAP_LAYER_SIZE

    items: list[MapItem] = []
    for index in range(MAP_ITEM_COUNT):
        if offset + MAP_ITEM_SIZE > len(payload):
            raise MapFormatError("Map payload ends inside item table.")
        pixel_x, pixel_y, object_or_weapon = struct.unpack_from(">HHH", payload, offset)
        offset += MAP_ITEM_SIZE
        items.append(
            MapItem(
                index=index,
                pixel_x=pixel_x,
                pixel_y=pixel_y,
                object_or_weapon_info_index=object_or_weapon,
            )
        )

    strings_base = offset
    strings_block_size = PUZZLE_STRING_POINTER_TABLE_SIZE + PUZZLE_STRING_TEXT_AREA_SIZE
    if strings_base + strings_block_size > len(payload):
        raise MapFormatError("Map payload ends inside puzzle string block.")

    puzzle_strings: list[str | None] = []
    for index in range(PUZZLE_STRING_COUNT):
        pointer_offset = strings_base + index * 4
        relative_offset = struct.unpack_from(">i", payload, pointer_offset)[0]
        if relative_offset <= 0:
            puzzle_strings.append(None)
            continue
        absolute_offset = strings_base + relative_offset
        if absolute_offset >= len(payload) or payload[absolute_offset] == 0:
            puzzle_strings.append(None)
            continue
        puzzle_strings.append(_read_c_string(payload, absolute_offset))

    offset = strings_base + strings_block_size

    puzzles: list[MapPuzzle] = []
    for index in range(MAP_PUZZLE_COUNT):
        if offset + MAP_PUZZLE_SIZE > len(payload):
            raise MapFormatError("Map payload ends inside puzzle table.")
        words = struct.unpack_from(">12H", payload, offset)
        offset += MAP_PUZZLE_SIZE
        puzzles.append(
            MapPuzzle(
                index=index,
                condition_function_indices=(words[0], words[2], words[4]),
                condition_params=(words[1], words[3], words[5]),
                pixel_x=words[6],
                pixel_y=words[7],
                effect_function_index_remove=words[8],
                effect_param=words[9],
                string_index=words[10],
                trailing_word=words[11],
            )
        )

    if offset != len(payload):
        raise MapFormatError(
            f"Parsed {offset} bytes, but map payload has {len(payload)} bytes."
        )

    return GodsMap(
        source_path=Path(source_path),
        packed_size=len(payload) if packed_size is None else packed_size,
        raw_payload=payload,
        raster=RasterInfo(
            color_count=raster_color_count,
            height=raster_height,
            palette_words=tuple(raster_palette),
        ),
        layer_a=bytes(layer_a),
        layer_b=bytes(layer_b),
        items=tuple(items),
        puzzle_strings=tuple(puzzle_strings),
        puzzles=tuple(puzzles),
    )


def load_packed_map(path: str | Path) -> GodsMap:
    packed = load_packed(path)
    return parse_map_payload(
        packed.data,
        source_path=packed.path,
        packed_size=packed.packed_size,
    )
