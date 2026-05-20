from __future__ import annotations

from dataclasses import dataclass
import struct

from gods_tools.formats.map import (
    MAP_CELL_HEIGHT,
    MAP_CELL_WIDTH,
    MAP_HEIGHT_CELLS,
    MAP_ITEM_SIZE,
    MAP_LAYER_SIZE,
    MAP_PUZZLE_SIZE,
    MAP_WIDTH_CELLS,
)
from gods_tools.formats.alfils import EVENTS_OFFSET, SWITCHES_OFFSET, WALKING_WAVES_OFFSET
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

    def plan_set_event(self, event_index: int, *, event_type_index: int, param: int) -> "EditSession":
        alfils = self.document.alfils_data
        if alfils is None:
            raise ValueError("This level has no PALFILS event table.")
        if not 0 <= event_index < len(alfils.events):
            raise IndexError(f"Event index {event_index} is out of range.")
        if not 0 <= param <= 0xFFFF:
            raise ValueError("Event param must fit into 16-bit unsigned word.")
        if event_type_index == 11:
            encoded_type = -1
        elif event_type_index < 0:
            encoded_type = 0
        else:
            encoded_type = event_type_index + 1
        event = alfils.events[event_index]
        before = struct.pack(">hH", event.function_index_min1, event.param)
        after = struct.pack(">hH", encoded_type, param)
        offset = EVENTS_OFFSET + 4 + event_index * 4
        patch = RawBytePatch(
            target="alfils",
            offset=offset,
            before=before,
            after=after,
            reason=f"set event E{event_index} type={event_type_index} param={param}",
        )
        return EditSession(self.document, self.plan.with_patch(patch))

    def plan_set_map_item(self, item_index: int, *, pixel_x: int, pixel_y: int, raw_id: int) -> "EditSession":
        items = self.document.map_data.items
        if not 0 <= item_index < len(items):
            raise IndexError(f"Map item index {item_index} is out of range.")
        if not (0 <= pixel_x <= 0xFFFF and 0 <= pixel_y <= 0xFFFF and 0 <= raw_id <= 0xFFFF):
            raise ValueError("Map item fields must fit into 16-bit unsigned words.")
        item = items[item_index]
        layout = map_payload_layout(self.document)
        offset = layout.items_offset + item_index * MAP_ITEM_SIZE
        before = struct.pack(">HHH", item.pixel_x, item.pixel_y, item.object_or_weapon_info_index)
        after = struct.pack(">HHH", pixel_x, pixel_y, raw_id)
        patch = RawBytePatch(
            target="map",
            offset=offset,
            before=before,
            after=after,
            reason=f"set map item I{item_index} fields",
        )
        return EditSession(self.document, self.plan.with_patch(patch))

    def plan_set_switch(self, switch_index: int, *, pixel_x: int, pixel_y: int, object_info_index: int) -> "EditSession":
        alfils = self.document.alfils_data
        if alfils is None:
            raise ValueError("This level has no PALFILS switch table.")
        if not 0 <= switch_index < len(alfils.switches):
            raise IndexError(f"Switch index {switch_index} is out of range.")
        if not (0 <= pixel_x <= 0xFFFF and 0 <= pixel_y <= 0xFFFF and 0 <= object_info_index <= 0xFFFF):
            raise ValueError("Switch fields must fit into 16-bit unsigned words.")
        switch = alfils.switches[switch_index]
        before = struct.pack(">HHH", switch.pixel_x, switch.pixel_y, switch.object_info_index)
        after = struct.pack(">HHH", pixel_x, pixel_y, object_info_index)
        patch = RawBytePatch(
            target="alfils",
            offset=SWITCHES_OFFSET + switch_index * 6,
            before=before,
            after=after,
            reason=f"set switch S{switch_index} fields",
        )
        return EditSession(self.document, self.plan.with_patch(patch))

    def plan_set_walking_wave(
        self,
        wave_index: int,
        *,
        pixel_x: int,
        pixel_y: int,
        facing: int,
        function_index_unknown: int,
        spawn_delay: int,
        enemy_count: int,
        health: int,
        enemy_info_index: int,
        missile_type: int,
        speed_value: int,
        reward: int,
        padding: int,
    ) -> "EditSession":
        alfils = self.document.alfils_data
        if alfils is None:
            raise ValueError("This level has no PALFILS walking wave table.")
        if not 0 <= wave_index < len(alfils.walking_waves):
            raise IndexError(f"Walking wave index {wave_index} is out of range.")
        word_values = (pixel_x, pixel_y, spawn_delay, enemy_info_index)
        byte_values = (facing, function_index_unknown, enemy_count, health, missile_type, speed_value, reward, padding)
        if any(not 0 <= value <= 0xFFFF for value in word_values):
            raise ValueError("Walking wave word fields must fit into 16-bit unsigned words.")
        if any(not 0 <= value <= 0xFF for value in byte_values):
            raise ValueError("Walking wave byte fields must fit into 8-bit unsigned bytes.")
        wave = alfils.walking_waves[wave_index]
        before = struct.pack(
            ">HHBBHBBHBBBB",
            wave.pixel_x,
            wave.pixel_y,
            wave.facing,
            wave.function_index_unknown,
            wave.spawn_delay,
            wave.enemy_count,
            wave.health,
            wave.enemy_info_index,
            wave.missile_type,
            wave.speed_value,
            wave.reward,
            wave.padding,
        )
        after = struct.pack(
            ">HHBBHBBHBBBB",
            pixel_x,
            pixel_y,
            facing,
            function_index_unknown,
            spawn_delay,
            enemy_count,
            health,
            enemy_info_index,
            missile_type,
            speed_value,
            reward,
            padding,
        )
        patch = RawBytePatch(
            target="alfils",
            offset=WALKING_WAVES_OFFSET + wave_index * 16,
            before=before,
            after=after,
            reason=f"set walking wave WW{wave_index} fields",
        )
        return EditSession(self.document, self.plan.with_patch(patch))

    def plan_set_puzzle(
        self,
        puzzle_index: int,
        *,
        condition_types: tuple[int, int, int],
        condition_params: tuple[int, int, int],
        pixel_x: int,
        pixel_y: int,
        effect_type: int,
        effect_param: int,
        remove_after_effect: bool,
        string_index: int | None = None,
        trailing_word: int | None = None,
    ) -> "EditSession":
        puzzles = self.document.map_data.puzzles
        if not 0 <= puzzle_index < len(puzzles):
            raise IndexError(f"Puzzle index {puzzle_index} is out of range.")
        values = (*condition_types, *condition_params, pixel_x, pixel_y, effect_type, effect_param)
        if any(not 0 <= value <= 0xFFFF for value in values):
            raise ValueError("Puzzle fields must fit into 16-bit unsigned words.")
        puzzle = puzzles[puzzle_index]
        function_remove = effect_type | (0x8000 if remove_after_effect else 0)
        before_words = (
            puzzle.condition_function_indices[0],
            puzzle.condition_params[0],
            puzzle.condition_function_indices[1],
            puzzle.condition_params[1],
            puzzle.condition_function_indices[2],
            puzzle.condition_params[2],
            puzzle.pixel_x,
            puzzle.pixel_y,
            puzzle.effect_function_index_remove,
            puzzle.effect_param,
            puzzle.string_index,
            puzzle.trailing_word,
        )
        after_words = (
            condition_types[0],
            condition_params[0],
            condition_types[1],
            condition_params[1],
            condition_types[2],
            condition_params[2],
            pixel_x,
            pixel_y,
            function_remove,
            effect_param,
            puzzle.string_index if string_index is None else string_index,
            puzzle.trailing_word if trailing_word is None else trailing_word,
        )
        offset = map_payload_layout(self.document).puzzles_offset + puzzle_index * MAP_PUZZLE_SIZE
        patch = RawBytePatch(
            target="map",
            offset=offset,
            before=struct.pack(">12H", *before_words),
            after=struct.pack(">12H", *after_words),
            reason=f"set puzzle P{puzzle_index} fields",
        )
        return EditSession(self.document, self.plan.with_patch(patch))

    def plan_set_event_trigger_cells(self, event_index: int, cells: tuple[tuple[int, int], ...]) -> "EditSession":
        alfils = self.document.alfils_data
        if alfils is None:
            raise ValueError("This level has no PALFILS event table.")
        if not 0 <= event_index < len(alfils.events):
            raise IndexError(f"Event index {event_index} is out of range.")
        session: EditSession = self
        old_cells = tuple(
            (index % MAP_WIDTH_CELLS, index // MAP_WIDTH_CELLS)
            for index, value in enumerate(self.document.map_data.layer_b)
            if value == event_index + 3
        )
        new_cells = tuple(dict.fromkeys(cells))
        for cell_x, cell_y in old_cells:
            if (cell_x, cell_y) not in new_cells:
                session = session.plan_set_layer_b_byte(cell_x, cell_y, 0)
        for cell_x, cell_y in new_cells:
            session = session.plan_set_layer_b_byte(cell_x, cell_y, event_index + 3)
        return session

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
