from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import struct

from .compression import load_packed


class ItemTableFormatError(ValueError):
    """Raised when GODS object/weapon metadata tables are malformed."""


_OBJECT_RECORD_SIZE = 48
_OBJECT_COUNT = 132
_WEAPON_RECORD_SIZE = 80
_WEAPON_COUNT = 11

_OBJECT_TYPE_NAMES = {
    0: "USABLE ITEM",
    1: "TREASURE",
    2: "PICKABLE ITEM",
    3: "SWITCH",
    4: "DESTRUCTABLE",
    5: "DECORATION",
}


_OBJECT_EFFECT_NAMES = {
    0: "Restore half health",
    1: "Increase power by 1",
    2: "Increase power by 2",
    3: "Restore full health",
    4: "Starburst",
    5: "Shield: reduce damage",
    6: "Shield: invulnerability",
    7: "Familiar",
    8: "Familiar: magic wings",
    9: "Familiar: power claws",
    10: "Extra life",
    11: "Slow monsters / trigger scroll",
    12: "Freeze aliens",
    13: "Giant jump",
    14: "Weapon arc: standard",
    15: "Weapon arc: intense",
    16: "Weapon arc: wide",
    17: "Teleport stone",
    18: "Reveal clues",
    19: "Food: restore energy A",
    20: "Food: restore energy B",
    21: "Food: restore energy C",
    22: "Summon shopkeeper",
}


def _read_fixed_c_string(payload: bytes, offset: int, size: int) -> str:
    raw = payload[offset : offset + size]
    return raw.split(b"\x00", 1)[0].decode("latin-1", errors="replace").strip()


@dataclass(frozen=True)
class ObjectInfo:
    index: int
    sprite_index: int
    unknown_always_zero: int
    type_index: int
    value: int
    name: str
    description: str
    effect_index: int | None

    @property
    def type_name(self) -> str:
        return _OBJECT_TYPE_NAMES.get(self.type_index, f"TYPE {self.type_index}")

    @property
    def full_name(self) -> str:
        if self.name and self.description:
            return f"{self.name} ({self.description})"
        return self.name or self.description or "—"

    @property
    def is_destructable(self) -> bool:
        return self.type_index == 4

    @property
    def effect_name(self) -> str | None:
        if self.effect_index is None:
            return None
        return _OBJECT_EFFECT_NAMES.get(self.effect_index, f"Effect {self.effect_index}")

    @property
    def is_teleport_stone(self) -> bool:
        return self.effect_index == 17

    @property
    def is_reveal_clues(self) -> bool:
        return self.effect_index == 18

    @property
    def is_chest_key(self) -> bool:
        # Exact GODS table ranges mirrored from Kroah's viewer ObjectInfo.cs.
        return 18 <= self.index <= 23

    @property
    def is_special_key(self) -> bool:
        return 127 <= self.index <= 129

    @property
    def is_chest(self) -> bool:
        return 12 <= self.index <= 17

    def opens_chest_object_info(self, chest_object_info_index: int) -> bool:
        if not self.is_chest_key:
            return False
        if not (12 <= chest_object_info_index <= 17):
            return False
        # Original viewer formula: (key - 21) == ((chest - 12) / 2).
        # C# integer division is truncating, matching Python // here.
        return (self.index - 21) == ((chest_object_info_index - 12) // 2)


@dataclass(frozen=True)
class WeaponInfo:
    index: int
    used_in_slot_1_or_2: int
    update2_function_index: int
    ingame_anim_index: int
    base_power: int
    current_power: int
    field_a: int
    sprite_index_first_right: int
    ingame_facing: int
    use_left_function_index: int
    use_right_function_index: int
    update_function_index: int
    anim_index_max: int
    sprite_index_first_left: int
    name: str
    description: str
    remove_on_wall_hit: int
    remove_on_enemy_hit: int
    value: int

    @property
    def full_name(self) -> str:
        if self.name and self.description:
            return f"{self.name} ({self.description})"
        return self.name or self.description or "—"


@dataclass(frozen=True)
class ObjectTable:
    source_path: Path
    packed_size: int
    raw_payload: bytes
    records: tuple[ObjectInfo, ...]

    def get(self, index: int) -> ObjectInfo | None:
        if 0 <= index < len(self.records):
            return self.records[index]
        return None


@dataclass(frozen=True)
class WeaponTable:
    source_path: Path
    packed_size: int
    raw_payload: bytes
    records: tuple[WeaponInfo, ...]

    def get(self, index: int) -> WeaponInfo | None:
        if 0 <= index < len(self.records):
            return self.records[index]
        return None


def parse_object_table_payload(payload: bytes, source_path: str | Path = "<memory>", packed_size: int | None = None) -> ObjectTable:
    expected = _OBJECT_COUNT * _OBJECT_RECORD_SIZE
    if len(payload) != expected:
        raise ItemTableFormatError(f"Expected {expected} object-table bytes, got {len(payload)}.")

    records: list[ObjectInfo] = []
    offset = 0
    effect_index = 0
    for index in range(_OBJECT_COUNT):
        sprite_index, unknown, type_index, value = struct.unpack_from(">4H", payload, offset)
        name = _read_fixed_c_string(payload, offset + 8, 16)
        description = _read_fixed_c_string(payload, offset + 24, 24)
        record_effect_index: int | None = effect_index if type_index == 0 else None
        if type_index == 0:
            effect_index += 1
        records.append(
            ObjectInfo(
                index=index,
                sprite_index=sprite_index,
                unknown_always_zero=unknown,
                type_index=type_index,
                value=value,
                name=name,
                description=description,
                effect_index=record_effect_index,
            )
        )
        offset += _OBJECT_RECORD_SIZE

    return ObjectTable(
        source_path=Path(source_path),
        packed_size=len(payload) if packed_size is None else packed_size,
        raw_payload=payload,
        records=tuple(records),
    )


def parse_weapon_table_payload(payload: bytes, source_path: str | Path = "<memory>", packed_size: int | None = None) -> WeaponTable:
    expected = _WEAPON_COUNT * _WEAPON_RECORD_SIZE
    if len(payload) != expected:
        raise ItemTableFormatError(f"Expected {expected} weapon-table bytes, got {len(payload)}.")

    records: list[WeaponInfo] = []
    offset = 0
    for index in range(_WEAPON_COUNT):
        words = struct.unpack_from(">8H", payload, offset)
        use_left, use_right, update = struct.unpack_from(">3I", payload, offset + 16)
        anim_index_max, sprite_index_first_left = struct.unpack_from(">2H", payload, offset + 28)
        name = _read_fixed_c_string(payload, offset + 32, 16)
        description = _read_fixed_c_string(payload, offset + 48, 16)
        remove_on_wall_hit = payload[offset + 72]
        remove_on_enemy_hit = payload[offset + 73]
        value = struct.unpack_from(">H", payload, offset + 74)[0]
        records.append(
            WeaponInfo(
                index=index,
                used_in_slot_1_or_2=words[0],
                update2_function_index=words[1],
                ingame_anim_index=words[2],
                base_power=words[3],
                current_power=words[4],
                field_a=words[5],
                sprite_index_first_right=words[6],
                ingame_facing=words[7],
                use_left_function_index=use_left,
                use_right_function_index=use_right,
                update_function_index=update,
                anim_index_max=anim_index_max,
                sprite_index_first_left=sprite_index_first_left,
                name=name,
                description=description,
                remove_on_wall_hit=remove_on_wall_hit,
                remove_on_enemy_hit=remove_on_enemy_hit,
                value=value,
            )
        )
        offset += _WEAPON_RECORD_SIZE

    return WeaponTable(
        source_path=Path(source_path),
        packed_size=len(payload) if packed_size is None else packed_size,
        raw_payload=payload,
        records=tuple(records),
    )


def load_packed_object_table(path: str | Path) -> ObjectTable:
    packed = load_packed(path)
    return parse_object_table_payload(packed.data, packed.path, packed.packed_size)


def load_packed_weapon_table(path: str | Path) -> WeaponTable:
    packed = load_packed(path)
    return parse_weapon_table_payload(packed.data, packed.path, packed.packed_size)


def level_object_table_path(game_dir: str | Path, level: int) -> Path:
    return Path(game_dir) / f"POBJECTS.00{level}"


def level_weapon_table_path(game_dir: str | Path, level: int) -> Path:
    return Path(game_dir) / f"PWEAPONS.00{level}"
