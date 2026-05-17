from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import struct

from .compression import load_packed

ALFILS_EXPECTED_SIZE = 8760

FLYING_WAVES_OFFSET = 0x0000
EVENTS_OFFSET = 0x0320
WALKING_WAVES_OFFSET = 0x0718
INTEL_FLYING_WAVES_OFFSET = 0x0D58
INTEL_WALKING_WAVES_OFFSET = 0x11A4  # 0x0D58 + 1100
SWITCHES_OFFSET = 0x15F0
TELEPORTS_OFFSET = 0x1770
TRAPDOORS_OFFSET = 0x1824
MOVING_BLOCKS_OFFSET = 0x189C
HINTS_OFFSET = 0x1B58
TRAILING_ZEROES_OFFSET = 0x21E8

EVENT_TYPE_NAMES: dict[int, str] = {
    0: "SpawnFlyingWave",
    1: "SpawnWalkingWave",
    2: "CheckPuzzle",
    3: "SpawnIntelWalkingWave",
    4: "SpawnIntelFlyingWave",
    5: "Checkpoint",
    6: "ActivateMovingBlockAction0",
    7: "ActivateMovingBlockAction1",
    8: "ActivateMovingBlockAction2",
    9: "ActivateMovingBlockAction3",
    10: "LoadGuardian",
    11: "Inactive",
}
EVENT_ACRONYMS: dict[int, str] = {
    0: "FW",
    1: "WW",
    2: "P",
    3: "IW",
    4: "IF",
    5: "CP",
    6: "MB0",
    7: "MB1",
    8: "MB2",
    9: "MB3",
    10: "G",
    11: "OFF",
}


class AlfilsFormatError(ValueError):
    """Raised when a packed PALFILS payload does not match the known layout."""


@dataclass(frozen=True)
class FlyingWave:
    index: int
    enemy_count: int
    flying_path_index: int
    spawn_delay: int
    health: int
    enemy_info_index: int
    missile_type_speed: int
    reward: int

    @property
    def missile_type(self) -> int:
        return (self.missile_type_speed >> 4) & 0x0F

    @property
    def speed_value(self) -> int:
        return self.missile_type_speed & 0x0F

    @property
    def appears_used(self) -> bool:
        return self.enemy_count != 0


    @property
    def has_reward(self) -> bool:
        return self.reward != 0xFF

    @property
    def reward_kind(self) -> str | None:
        if not self.has_reward:
            return None
        return "weapon" if self.reward <= 10 else "object"

    @property
    def reward_info_index(self) -> int | None:
        if not self.has_reward:
            return None
        return self.reward if self.reward <= 10 else self.reward - 11


@dataclass(frozen=True)
class EventRecord:
    index: int
    function_index_min1: int
    param: int

    @property
    def has_slot_data(self) -> bool:
        # Kroah's viewer stores null for exactly zero. Negative one is a real encoded
        # inactive marker with a specific event enum value.
        return self.function_index_min1 != 0

    @property
    def event_type_index(self) -> int | None:
        if self.function_index_min1 == -1:
            return 11
        if self.function_index_min1 == 0:
            return None
        return self.function_index_min1 - 1

    @property
    def type_name(self) -> str:
        index = self.event_type_index
        if index is None:
            return "Unused"
        return EVENT_TYPE_NAMES.get(index, f"Unknown{index}")

    @property
    def acronym(self) -> str:
        index = self.event_type_index
        if index is None:
            return "—"
        return EVENT_ACRONYMS.get(index, f"E{index}")

    @property
    def is_active_effect(self) -> bool:
        return self.event_type_index is not None and self.event_type_index != 11


@dataclass(frozen=True)
class WalkingWave:
    index: int
    pixel_x: int
    pixel_y: int
    facing: int
    function_index_unknown: int
    spawn_delay: int
    enemy_count: int
    health: int
    enemy_info_index: int
    missile_type: int
    speed_value: int
    reward: int
    padding: int

    @property
    def appears_used(self) -> bool:
        return self.enemy_count != 0 or self.pixel_x != 0 or self.pixel_y != 0


    @property
    def has_reward(self) -> bool:
        return self.reward != 0xFF

    @property
    def reward_kind(self) -> str | None:
        if not self.has_reward:
            return None
        return "weapon" if self.reward <= 10 else "object"

    @property
    def reward_info_index(self) -> int | None:
        if not self.has_reward:
            return None
        return self.reward if self.reward <= 10 else self.reward - 11


@dataclass(frozen=True)
class IntelWave:
    index: int
    kind: str  # "flying" or "walking"
    enemy_count: int
    health: int
    field_2: int
    field_3: int
    flags: int
    shot_velocity_fire_rate: int
    enemy_info_index: int
    objectives: int
    objective_balance: int
    behavior_10: int
    behavior_11: int
    behavior_12: int
    behavior_13: int
    field_14: int
    field_15: int
    reward: int
    cell_xy: int
    spawn_delay: int
    field_21: int

    @property
    def cell_x(self) -> int:
        return (self.cell_xy >> 8) & 0xFF

    @property
    def cell_y(self) -> int:
        return self.cell_xy & 0xFF

    @property
    def pixel_x(self) -> int:
        return self.cell_x * 32

    @property
    def pixel_y(self) -> int:
        return self.cell_y * 16

    @property
    def facing(self) -> int:
        return (self.flags >> 9) & 0x1

    @property
    def appears_used(self) -> bool:
        return self.enemy_count != 0


    @property
    def has_reward(self) -> bool:
        return self.reward != 0xFFFF

    @property
    def reward_kind(self) -> str | None:
        if not self.has_reward:
            return None
        return "weapon" if self.reward <= 10 else "object"

    @property
    def reward_info_index(self) -> int | None:
        if not self.has_reward:
            return None
        return self.reward if self.reward <= 10 else self.reward - 11


@dataclass(frozen=True)
class SwitchRecord:
    index: int
    pixel_x: int
    pixel_y: int
    object_info_index: int

    @property
    def appears_used(self) -> bool:
        values = (self.pixel_x, self.pixel_y, self.object_info_index)
        return values not in ((0, 0, 0), (0xFFFF, 0xFFFF, 0xFFFF))


@dataclass(frozen=True)
class TeleportRecord:
    index: int
    src_pixel_x: int
    dst_pixel_x: int
    dst_pixel_y: int

    @property
    def appears_used(self) -> bool:
        return self.src_pixel_x != 0

    @property
    def normalized_dst_pixel_x(self) -> int:
        return (self.dst_pixel_x // 32) * 32 if self.dst_pixel_x % 32 else self.dst_pixel_x

    @property
    def normalized_dst_pixel_y(self) -> int:
        return (self.dst_pixel_y // 16) * 16 if self.dst_pixel_y % 16 else self.dst_pixel_y

    @property
    def marker_x(self) -> int:
        # Kroah draws the teleport rectangle from dstX+16.
        return self.normalized_dst_pixel_x + 16

    @property
    def marker_y(self) -> int:
        return self.normalized_dst_pixel_y


@dataclass(frozen=True)
class TrapdoorRecord:
    index: int
    pixel_x: int
    pixel_y: int
    is_opened_raw: int

    @property
    def appears_used(self) -> bool:
        return self.pixel_x != 0xFFFF

    @property
    def is_opened(self) -> bool:
        return self.is_opened_raw == 1


@dataclass(frozen=True)
class MovingBlockRecord:
    index: int
    pixel_x: int
    pixel_y: int
    map_sprite_index_min1: int
    speed_min1: int
    target_points: tuple[tuple[int, int], ...]
    actions: tuple[int, int, int, int]
    width_raw: int
    height_min1: int

    @property
    def width_min1(self) -> int:
        return self.width_raw & 0x07

    @property
    def width_pixels(self) -> int:
        return (self.width_min1 + 1) * 32

    @property
    def height_pixels(self) -> int:
        return (self.height_min1 + 1) * 16

    @property
    def appears_used(self) -> bool:
        return self.map_sprite_index_min1 not in (0x00, 0xFF)

    @property
    def map_sprite_index(self) -> int:
        return self.map_sprite_index_min1 + 1

    @property
    def speed_pixels_per_frame(self) -> int:
        return self.speed_min1 + 1

    def action_raw(self, action_index: int) -> int:
        if not (0 <= action_index < len(self.actions)):
            raise IndexError(f"Moving-block action index {action_index} is outside 0..3.")
        return self.actions[action_index]

    def action_kind(self, action_index: int) -> str:
        raw = self.action_raw(action_index)
        if raw == 0:
            return "cycle_forward"
        if raw == 1:
            return "cycle_backward"
        if 2 <= raw <= 5:
            return "move_to_target_then_stop"
        if raw == 0xFF:
            return "disable"
        if raw == 0xFE:
            return "never_used"
        # These values do occur in the raw table, but our full-data cross-check shows
        # that they only live in action slots never referenced by an event. Keep them
        # visible for RE, but do not pretend they are active game semantics.
        return "opaque_unreferenced_raw"

    def action_description(self, action_index: int) -> str:
        raw = self.action_raw(action_index)
        kind = self.action_kind(action_index)
        if kind == "cycle_forward":
            return "move to coord0, then follow later coords, then loop"
        if kind == "cycle_backward":
            return "move to coord0, then traverse later coords in reverse, then loop"
        if kind == "move_to_target_then_stop":
            target_index = raw - 2
            x, y = self.target_points[target_index]
            return f"move to coord{target_index} ({x},{y}) then stop"
        if kind == "disable":
            return "disable moving block"
        if kind == "never_used":
            return "never-used marker"
        return f"opaque raw action byte 0x{raw:02X} in an unreferenced slot"


@dataclass(frozen=True)
class HintRecord:
    index: int
    pixel_x: int
    text: str | None

    @property
    def appears_used(self) -> bool:
        return self.pixel_x != 0xFFFF


@dataclass(frozen=True)
class AlfilsData:
    source_path: Path
    packed_size: int
    raw_payload: bytes
    section_offsets: tuple[int, ...]
    flying_waves: tuple[FlyingWave, ...]
    events: tuple[EventRecord, ...]
    walking_waves: tuple[WalkingWave, ...]
    intel_flying_waves: tuple[IntelWave, ...]
    intel_walking_waves: tuple[IntelWave, ...]
    switches: tuple[SwitchRecord, ...]
    teleports: tuple[TeleportRecord, ...]
    trapdoors: tuple[TrapdoorRecord, ...]
    moving_blocks: tuple[MovingBlockRecord, ...]
    hints: tuple[HintRecord, ...]
    trailing_zero_bytes: bytes

    @property
    def unpacked_size(self) -> int:
        return len(self.raw_payload)

    @property
    def active_flying_waves(self) -> tuple[FlyingWave, ...]:
        return tuple(wave for wave in self.flying_waves if wave.appears_used)

    @property
    def active_events(self) -> tuple[EventRecord, ...]:
        return tuple(event for event in self.events if event.is_active_effect)

    @property
    def stored_events(self) -> tuple[EventRecord, ...]:
        return tuple(event for event in self.events if event.has_slot_data)

    @property
    def active_walking_waves(self) -> tuple[WalkingWave, ...]:
        return tuple(wave for wave in self.walking_waves if wave.appears_used)

    @property
    def active_intel_flying_waves(self) -> tuple[IntelWave, ...]:
        return tuple(wave for wave in self.intel_flying_waves if wave.appears_used)

    @property
    def active_intel_walking_waves(self) -> tuple[IntelWave, ...]:
        return tuple(wave for wave in self.intel_walking_waves if wave.appears_used)

    @property
    def active_switches(self) -> tuple[SwitchRecord, ...]:
        return tuple(record for record in self.switches if record.appears_used)

    @property
    def active_teleports(self) -> tuple[TeleportRecord, ...]:
        return tuple(record for record in self.teleports if record.appears_used)

    @property
    def active_trapdoors(self) -> tuple[TrapdoorRecord, ...]:
        return tuple(record for record in self.trapdoors if record.appears_used)

    @property
    def active_moving_blocks(self) -> tuple[MovingBlockRecord, ...]:
        return tuple(record for record in self.moving_blocks if record.appears_used)

    @property
    def active_hints(self) -> tuple[HintRecord, ...]:
        return tuple(record for record in self.hints if record.appears_used)

    def event(self, index: int) -> EventRecord | None:
        if not (0 <= index < len(self.events)):
            return None
        event = self.events[index]
        return event if event.has_slot_data else None


def _require_offset(actual: int, expected: int, section: str) -> None:
    if actual != expected:
        raise AlfilsFormatError(
            f"PALFILS parser reached offset 0x{actual:04X} before {section}; expected 0x{expected:04X}."
        )


def _read_c_string_fixed(block: bytes) -> str:
    text = block.split(b"\x00", 1)[0]
    return text.decode("latin-1", errors="replace")


def parse_alfils_payload(
    payload: bytes,
    source_path: str | Path = "<memory>",
    packed_size: int | None = None,
) -> AlfilsData:
    if len(payload) != ALFILS_EXPECTED_SIZE:
        raise AlfilsFormatError(
            f"Expected {ALFILS_EXPECTED_SIZE} bytes after unpacking PALFILS, got {len(payload)}."
        )

    offset = 0
    _require_offset(offset, FLYING_WAVES_OFFSET, "flying waves")
    flying_waves: list[FlyingWave] = []
    for index in range(100):
        enemy_count, path_index, delay, health, enemy_info, missile_speed, reward = struct.unpack_from(">BBHBBBB", payload, offset)
        offset += 8
        flying_waves.append(
            FlyingWave(index, enemy_count, path_index, delay, health, enemy_info, missile_speed, reward)
        )

    _require_offset(offset, EVENTS_OFFSET, "events")
    # Kroah's viewer skips four bytes before the 253 4-byte event records.
    event_header = payload[offset : offset + 4]
    offset += 4
    events: list[EventRecord] = []
    for index in range(253):
        function_index_min1, param = struct.unpack_from(">hH", payload, offset)
        offset += 4
        events.append(EventRecord(index, function_index_min1, param))

    _require_offset(offset, WALKING_WAVES_OFFSET, "walking waves")
    walking_waves: list[WalkingWave] = []
    for index in range(100):
        values = struct.unpack_from(">HHBBHBBHBBBB", payload, offset)
        offset += 16
        walking_waves.append(
            WalkingWave(
                index=index,
                pixel_x=values[0],
                pixel_y=values[1],
                facing=values[2],
                function_index_unknown=values[3],
                spawn_delay=values[4],
                enemy_count=values[5],
                health=values[6],
                enemy_info_index=values[7],
                missile_type=values[8],
                speed_value=values[9],
                reward=values[10],
                padding=values[11],
            )
        )

    def parse_intel_waves(kind: str, count: int) -> list[IntelWave]:
        nonlocal offset
        result: list[IntelWave] = []
        for index in range(count):
            values = struct.unpack_from(">BBBBHBBBBBBBBBBHHBB", payload, offset)
            offset += 22
            result.append(
                IntelWave(
                    index=index,
                    kind=kind,
                    enemy_count=values[0],
                    health=values[1],
                    field_2=values[2],
                    field_3=values[3],
                    flags=values[4],
                    shot_velocity_fire_rate=values[5],
                    enemy_info_index=values[6],
                    objectives=values[7],
                    objective_balance=values[8],
                    behavior_10=values[9],
                    behavior_11=values[10],
                    behavior_12=values[11],
                    behavior_13=values[12],
                    field_14=values[13],
                    field_15=values[14],
                    reward=values[15],
                    cell_xy=values[16],
                    spawn_delay=values[17],
                    field_21=values[18],
                )
            )
        return result

    _require_offset(offset, INTEL_FLYING_WAVES_OFFSET, "intelligent flying waves")
    intel_flying = parse_intel_waves("flying", 50)

    _require_offset(offset, INTEL_WALKING_WAVES_OFFSET, "intelligent walking waves")
    intel_walking = parse_intel_waves("walking", 50)

    _require_offset(offset, SWITCHES_OFFSET, "switches")
    switches: list[SwitchRecord] = []
    for index in range(64):
        x, y, object_info = struct.unpack_from(">HHH", payload, offset)
        offset += 6
        switches.append(SwitchRecord(index, x, y, object_info))

    _require_offset(offset, TELEPORTS_OFFSET, "teleports")
    teleports: list[TeleportRecord] = []
    for index in range(30):
        src_x, dst_x, dst_y = struct.unpack_from(">HHH", payload, offset)
        offset += 6
        teleports.append(TeleportRecord(index, src_x, dst_x, dst_y))

    _require_offset(offset, TRAPDOORS_OFFSET, "trapdoors")
    trapdoors: list[TrapdoorRecord] = []
    for index in range(20):
        x, y, opened = struct.unpack_from(">HHH", payload, offset)
        offset += 6
        trapdoors.append(TrapdoorRecord(index, x, y, opened))

    _require_offset(offset, MOVING_BLOCKS_OFFSET, "moving blocks")
    moving_blocks: list[MovingBlockRecord] = []
    for index in range(25):
        x, y, sprite_m1, speed_m1 = struct.unpack_from(">HHBB", payload, offset)
        offset += 6
        points: list[tuple[int, int]] = []
        for _ in range(4):
            px, py = struct.unpack_from(">HH", payload, offset)
            offset += 4
            points.append((px, py))
        actions = struct.unpack_from(">BBBB", payload, offset)
        offset += 4
        width_raw, height_m1 = struct.unpack_from(">BB", payload, offset)
        offset += 2
        moving_blocks.append(
            MovingBlockRecord(
                index=index,
                pixel_x=x,
                pixel_y=y,
                map_sprite_index_min1=sprite_m1,
                speed_min1=speed_m1,
                target_points=tuple(points),
                actions=actions,
                width_raw=width_raw,
                height_min1=height_m1,
            )
        )

    _require_offset(offset, HINTS_OFFSET, "hints")
    hint_x_values = struct.unpack_from(">40H", payload, offset)
    offset += 80
    hints: list[HintRecord] = []
    for index, pixel_x in enumerate(hint_x_values):
        text_block = payload[offset + index * 40 : offset + (index + 1) * 40]
        text = None if pixel_x == 0xFFFF else _read_c_string_fixed(text_block)
        hints.append(HintRecord(index, pixel_x, text))
    offset += 40 * 40

    _require_offset(offset, TRAILING_ZEROES_OFFSET, "trailing zero bytes")
    trailing = payload[offset:]
    if len(trailing) != 80:
        raise AlfilsFormatError(f"Expected 80 trailing zero bytes, got {len(trailing)}.")
    if any(trailing):
        raise AlfilsFormatError("Expected PALFILS trailing 80-byte tail to be all zero.")
    offset += len(trailing)

    if offset != len(payload):
        raise AlfilsFormatError(
            f"Parsed {offset} bytes, but PALFILS payload has {len(payload)} bytes."
        )

    # Keep this local variable alive via the offsets marker; it documents the skipped field
    # and makes debug output easier if we need to expose it later.
    _ = event_header

    return AlfilsData(
        source_path=Path(source_path),
        packed_size=len(payload) if packed_size is None else packed_size,
        raw_payload=payload,
        section_offsets=(
            FLYING_WAVES_OFFSET,
            EVENTS_OFFSET,
            WALKING_WAVES_OFFSET,
            INTEL_FLYING_WAVES_OFFSET,
            INTEL_WALKING_WAVES_OFFSET,
            SWITCHES_OFFSET,
            TELEPORTS_OFFSET,
            TRAPDOORS_OFFSET,
            MOVING_BLOCKS_OFFSET,
            HINTS_OFFSET,
            TRAILING_ZEROES_OFFSET,
        ),
        flying_waves=tuple(flying_waves),
        events=tuple(events),
        walking_waves=tuple(walking_waves),
        intel_flying_waves=tuple(intel_flying),
        intel_walking_waves=tuple(intel_walking),
        switches=tuple(switches),
        teleports=tuple(teleports),
        trapdoors=tuple(trapdoors),
        moving_blocks=tuple(moving_blocks),
        hints=tuple(hints),
        trailing_zero_bytes=bytes(trailing),
    )


def load_packed_alfils(path: str | Path) -> AlfilsData:
    packed = load_packed(path)
    return parse_alfils_payload(
        packed.data,
        source_path=packed.path,
        packed_size=packed.packed_size,
    )
