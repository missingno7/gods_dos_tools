from __future__ import annotations

from dataclasses import dataclass
import struct

from gods_tools.formats.map import (
    MAP_CELL_HEIGHT,
    MAP_CELL_WIDTH,
    MAP_HEIGHT_CELLS,
    MAP_ITEM_SIZE,
    MAP_LAYER_SIZE,
    MAP_WIDTH_CELLS,
)
from gods_tools.model.document import LevelDocument

from .patches import RawBytePatch, WriteBackPlan


@dataclass(frozen=True)
class MapPayloadLayout:
    """Offsets for in-place map write-back planning."""

    layer_a_offset: int
    layer_b_offset: int
    items_offset: int
    strings_offset: int
    puzzles_offset: int


def map_payload_layout(document: LevelDocument) -> MapPayloadLayout:
    map_data = document.map_data
    raster_palette_bytes = map_data.raster.color_count * 2
    layer_a_offset = 4 + raster_palette_bytes
    layer_b_offset = layer_a_offset + MAP_LAYER_SIZE
    items_offset = layer_b_offset + MAP_LAYER_SIZE
    strings_offset = items_offset + len(map_data.items) * MAP_ITEM_SIZE
    puzzle_pointer_and_text_bytes = 40 * 4 + 40 * 42
    puzzles_offset = strings_offset + puzzle_pointer_and_text_bytes
    return MapPayloadLayout(
        layer_a_offset=layer_a_offset,
        layer_b_offset=layer_b_offset,
        items_offset=items_offset,
        strings_offset=strings_offset,
        puzzles_offset=puzzles_offset,
    )


@dataclass(frozen=True)
class EditSession:
    """Future edit mode nucleus: immutable document + auditable byte patch plan."""

    document: LevelDocument
    plan: WriteBackPlan = WriteBackPlan()

    @property
    def patch_count(self) -> int:
        return len(self.plan.patches)

    def plan_move_map_item(self, item_index: int, *, pixel_x: int, pixel_y: int) -> "EditSession":
        items = self.document.map_data.items
        if not 0 <= item_index < len(items):
            raise IndexError(f"Map item index {item_index} is out of range.")
        if not (0 <= pixel_x <= 0xFFFF and 0 <= pixel_y <= 0xFFFF):
            raise ValueError("Map item pixel coordinates must fit into 16-bit unsigned words.")
        item = items[item_index]
        layout = map_payload_layout(self.document)
        offset = layout.items_offset + item_index * MAP_ITEM_SIZE
        before = struct.pack(">HH", item.pixel_x, item.pixel_y)
        after = struct.pack(">HH", pixel_x, pixel_y)
        patch = RawBytePatch(
            target="map",
            offset=offset,
            before=before,
            after=after,
            reason=f"move map item I{item_index} from ({item.pixel_x},{item.pixel_y}) to ({pixel_x},{pixel_y})",
        )
        return EditSession(self.document, self.plan.with_patch(patch))

    def plan_set_layer_a_tile(self, cell_x: int, cell_y: int, tile_id: int) -> "EditSession":
        return self._plan_set_layer_byte("A", cell_x, cell_y, tile_id)

    def plan_set_layer_b_byte(self, cell_x: int, cell_y: int, value: int) -> "EditSession":
        return self._plan_set_layer_byte("B", cell_x, cell_y, value)

    def _plan_set_layer_byte(self, layer: str, cell_x: int, cell_y: int, value: int) -> "EditSession":
        if not (0 <= cell_x < MAP_WIDTH_CELLS and 0 <= cell_y < MAP_HEIGHT_CELLS):
            raise ValueError(f"Map cell ({cell_x},{cell_y}) is outside the {MAP_WIDTH_CELLS}×{MAP_HEIGHT_CELLS} map.")
        if not 0 <= value <= 0xFF:
            raise ValueError("Layer bytes must fit into 0..255.")
        layout = map_payload_layout(self.document)
        base_offset = layout.layer_a_offset if layer == "A" else layout.layer_b_offset
        offset = base_offset + cell_y * MAP_WIDTH_CELLS + cell_x
        before_value = self.document.map_data.layer_a_at(cell_x, cell_y) if layer == "A" else self.document.map_data.layer_b_at(cell_x, cell_y)
        patch = RawBytePatch(
            target="map",
            offset=offset,
            before=bytes([before_value]),
            after=bytes([value]),
            reason=f"set layer {layer} cell ({cell_x},{cell_y}) from {before_value} to {value}",
        )
        return EditSession(self.document, self.plan.with_patch(patch))

    def preview_patched_map_payload(self) -> bytes:
        return self.plan.apply_to_payload("map", self.document.map_data.raw_payload)

    def render_summary(self) -> str:
        layout = map_payload_layout(self.document)
        lines = [
            "Edit mode preparation",
            "=====================",
            "",
            f"Document: {self.document.resource.display_name}",
            f"Decoded map payload: {self.document.map_payload_size} bytes",
            f"Decoded PALFILS payload: {self.document.alfils_payload_size if self.document.alfils_payload_size is not None else '—'} bytes",
            "",
            "Stable map write-back offsets",
            "-----------------------------",
            f"Layer A: 0x{layout.layer_a_offset:04X}",
            f"Layer B: 0x{layout.layer_b_offset:04X}",
            f"Items:   0x{layout.items_offset:04X}",
            f"Strings: 0x{layout.strings_offset:04X}",
            f"Puzzles: 0x{layout.puzzles_offset:04X}",
            "",
            "First safe edit primitives prepared",
            "-----------------------------------",
            f"• move an existing map item in-place ({MAP_ITEM_SIZE}-byte item rows, x/y patched only)",
            f"• change one Layer A tile byte ({MAP_CELL_WIDTH}×{MAP_CELL_HEIGHT}px cell)",
            "• change one Layer B byte for future trigger/collision editing",
            "",
            "Repack/save status",
            "------------------",
            "The editor currently produces auditable in-memory raw byte patch plans only.",
            "Actual PKWARE recompression and file replacement are intentionally left for the next save-back milestone.",
            "",
            self.plan.render_text(),
        ]
        return "\n".join(lines)
