from __future__ import annotations

"""Small PC-executable-derived logic tables for DOS GODS.

These tables are not PALFILS data. They were verified directly in the unpacked DOS
``GAME.EXE`` payload and mirror the hardcoded tables that Kroah's viewer previously
read from Amiga/ST dumps:

- special / sequential teleport destinations;
- intelligent-enemy objective locations.

The editor keeps them as explicit extracted tables so the normal viewer remains usable
with the original packed executable in ``game_data`` without requiring an EXE unpacker
at startup. Offsets below refer to the unpacked DOS ``GAME.EXE`` payload used during RE.
"""

from dataclasses import dataclass

from .map import MAP_CELL_HEIGHT, MAP_CELL_WIDTH


@dataclass(frozen=True)
class SpecialTeleportDestination:
    level: int
    index: int
    coded: int
    pixel_x: int
    pixel_y: int
    unpacked_game_offset: int | None = None


@dataclass(frozen=True)
class ObjectiveLocation:
    level: int
    index: int
    cell_x: int
    cell_y: int
    pixel_x: int
    pixel_y: int
    unpacked_game_offset: int | None = None


def _decode_teleport(coded: int) -> tuple[int, int]:
    return ((coded >> 8) * MAP_CELL_WIDTH + MAP_CELL_WIDTH // 2, (coded & 0x00FF) * MAP_CELL_HEIGHT)


def _special(level: int, index: int, coded: int, base_offset: int) -> SpecialTeleportDestination:
    pixel_x, pixel_y = _decode_teleport(coded)
    return SpecialTeleportDestination(level, index, coded, pixel_x, pixel_y, base_offset + index * 2)


# Verified in unpacked DOS GAME.EXE:
#   Level 1 sequence begins at 0x1E606.
#   Level 2 sequence continues at 0x1E616.
# The extra Level 2 destination 0x202E is the same one Kroah's viewer had to patch in;
# it is kept explicit rather than assigning a speculative packed offset.
_SPECIAL_CODES: dict[int, tuple[int, ...]] = {
    1: (0x182C, 0x2027, 0x3129, 0x4804, 0x5009, 0x3129, 0x3129, 0x3129),
    2: (0x282C, 0x282C, 0x282C, 0x282C, 0x350C, 0x202E),
}

SPECIAL_TELEPORT_DESTINATIONS_BY_LEVEL: dict[int, tuple[SpecialTeleportDestination, ...]] = {
    1: tuple(_special(1, index, coded, 0x1E606) for index, coded in enumerate(_SPECIAL_CODES[1])),
    2: tuple(
        _special(2, index, coded, 0x1E616) if index < 5 else SpecialTeleportDestination(2, index, coded, *_decode_teleport(coded), None)
        for index, coded in enumerate(_SPECIAL_CODES[2])
    ),
    3: (),
    4: (),
}


def special_teleport_destinations(level: int) -> tuple[SpecialTeleportDestination, ...]:
    return SPECIAL_TELEPORT_DESTINATIONS_BY_LEVEL.get(level, ())


def _objective(level: int, index: int, cell_x: int, cell_y: int, base_offset: int) -> ObjectiveLocation:
    # Matches Kroah's ObjectiveLocation.cs: x = cellX * 32, y = (cellY + 1) * 16.
    return ObjectiveLocation(
        level=level,
        index=index,
        cell_x=cell_x,
        cell_y=cell_y,
        pixel_x=cell_x * MAP_CELL_WIDTH,
        pixel_y=(cell_y + 1) * MAP_CELL_HEIGHT,
        unpacked_game_offset=base_offset + index * 4,
    )


# Exact sequences found in unpacked DOS GAME.EXE:
#   L1 0x1DB00, L2 0x1DB28, L3 0x1DB78, L4 reuses the L3 table at 0x1DB78.
_OBJECTIVE_CELLS: dict[int, tuple[tuple[int, int], ...]] = {
    1: ((8, 25), (6, 31), (36, 51), (43, 58), (72, 38), (83, 19), (91, 25), (99, 11), (99, 5)),
    2: ((121, 6), (125, 17), (125, 55), (86, 58), (100, 56), (36, 43), (35, 52), (45, 59), (50, 59), (52, 59), (55, 59), (55, 25), (73, 36), (72, 49), (75, 49), (73, 59), (68, 59), (85, 12), (40, 4)),
    3: ((4, 23), (12, 23), (15, 23), (6, 42), (10, 60), (17, 60), (22, 60), (24, 49), (32, 49), (30, 16), (38, 16), (36, 10), (39, 27)),
    4: ((4, 23), (12, 23), (15, 23), (6, 42), (10, 60), (17, 60), (22, 60), (24, 49), (32, 49), (30, 16), (38, 16), (36, 10), (39, 27)),
}
_OBJECTIVE_BASE_OFFSETS = {1: 0x1DB00, 2: 0x1DB28, 3: 0x1DB78, 4: 0x1DB78}

OBJECTIVE_LOCATIONS_BY_LEVEL: dict[int, tuple[ObjectiveLocation, ...]] = {
    level: tuple(_objective(level, index, cell_x, cell_y, _OBJECTIVE_BASE_OFFSETS[level]) for index, (cell_x, cell_y) in enumerate(cells))
    for level, cells in _OBJECTIVE_CELLS.items()
}


def objective_locations(level: int) -> tuple[ObjectiveLocation, ...]:
    return OBJECTIVE_LOCATIONS_BY_LEVEL.get(level, ())


@dataclass(frozen=True)
class PlayerStartLocation:
    level: int
    pixel_x: int
    pixel_y: int
    source_note: str = "matches ST/Amiga viewer dumps; kept explicit for editor navigation"


# Kroah's viewer reads these from the hardcoded start-position table. The ST and Amiga
# dumps contain the same values; for editor UX we keep the extracted positions explicit.
# They are world-level starts, so both A/B halves of the same GODS world share one marker.
PLAYER_STARTS_BY_LEVEL: dict[int, PlayerStartLocation] = {
    1: PlayerStartLocation(1, 64, 944),
    2: PlayerStartLocation(2, 3888, 112),
    3: PlayerStartLocation(3, 64, 48),
    4: PlayerStartLocation(4, 384, 496),
}


def player_start_location(level: int) -> PlayerStartLocation | None:
    return PLAYER_STARTS_BY_LEVEL.get(level)
