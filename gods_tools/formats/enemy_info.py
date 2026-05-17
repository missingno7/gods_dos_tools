from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable

@dataclass(frozen=True)
class EnemyInfo:
    level: int
    kind: str
    index: int
    sprite_index_st: int
    sprite_index_dos: int
    draw_sprite_function_index: int
    think_ptr: int
    width: int
    height: int
    timed_action_ptr: int
    action_type: str

    def sprite_index_for_facing(self, facing: int = 0) -> int:
        facing = int(bool(facing))
        if self.sprite_index_st in REVERSED_FACING_ST_SPRITES:
            facing = 1 - facing
        count = FACING_ANIMATION_COUNTS.get((self.level, self.sprite_index_st))
        return self.sprite_index_dos if count is None else self.sprite_index_dos + facing * count

    @property
    def display_name(self) -> str:
        family = "flying" if self.kind == "flying" else "walking"
        return f"{family} enemy #{self.index}"

FACING_ANIMATION_COUNTS: dict[tuple[int, int], int] = {
    (1, 448): 3,
    (1, 454): 3,
    (1, 460): 9,
    (1, 478): 9,
    (1, 496): 9,
    (1, 522): 4,
    (1, 530): 3,
    (2, 448): 9,
    (2, 466): 9,
    (2, 484): 9,
    (2, 502): 4,
    (2, 523): 3,
    (2, 533): 3,
    (3, 448): 9,
    (3, 466): 9,
    (3, 495): 4,
    (3, 503): 4,
    (3, 521): 4,
    (4, 448): 9,
    (4, 466): 9,
    (4, 502): 4,
    (4, 510): 4,
    (4, 545): 4,
}
REVERSED_FACING_ST_SPRITES = frozenset({523, 530, 545})

ENEMY_INFO_DATA: dict[int, dict[str, tuple[EnemyInfo, ...]]] = {
    1: {
        'flying': (
            EnemyInfo(1, 'flying', 0, 448, 450, 1, 34556, 32, 32, 33624, 'Flying_Fire_01'),
            EnemyInfo(1, 'flying', 1, 514, 516, 1, 34690, 32, 32, 34102, 'Flying_NoAction_04'),
            EnemyInfo(1, 'flying', 2, 454, 456, 1, 34564, 32, 32, 33624, 'Flying_Fire_01'),
        ),
        'walking': (
            EnemyInfo(1, 'walking', 0, 460, 462, 1, 32758, 32, 32, 30204, 'Walking_Fire_01'),
            EnemyInfo(1, 'walking', 1, 478, 480, 1, 32778, 32, 32, 30204, 'Walking_Fire_01'),
            EnemyInfo(1, 'walking', 2, 496, 498, 1, 32798, 32, 32, 30204, 'Walking_Fire_01'),
            EnemyInfo(1, 'walking', 3, 496, 498, 1, 32798, 32, 32, 30204, 'Walking_Fire_01'),
            EnemyInfo(1, 'walking', 4, 522, 524, 1, 33320, 24, 24, 30204, 'Walking_Fire_01'),
            EnemyInfo(1, 'walking', 5, 530, 532, 1, 32428, 24, 24, 32550, 'Walking_Fire_02'),
            EnemyInfo(1, 'walking', 6, 530, 532, 1, 32428, 24, 24, 32550, 'Walking_Fire_02'),
            EnemyInfo(1, 'walking', 7, 530, 532, 1, 32428, 24, 24, 32550, 'Walking_Fire_02'),
        ),
    },
    2: {
        'flying': (
            EnemyInfo(2, 'flying', 0, 502, 504, 1, 34544, 32, 32, 33624, 'Flying_Fire_01'),
            EnemyInfo(2, 'flying', 1, 510, 512, 1, 34550, 32, 32, 33624, 'Flying_Fire_01'),
            EnemyInfo(2, 'flying', 2, 502, 504, 1, 34544, 32, 32, 33624, 'Flying_Fire_01'),
            EnemyInfo(2, 'flying', 3, 502, 504, 1, 34544, 32, 32, 33624, 'Flying_Fire_01'),
        ),
        'walking': (
            EnemyInfo(2, 'walking', 0, 448, 450, 1, 32738, 32, 32, 30204, 'Walking_Fire_01'),
            EnemyInfo(2, 'walking', 1, 466, 468, 1, 32788, 32, 32, 30204, 'Walking_Fire_01'),
            EnemyInfo(2, 'walking', 2, 519, 521, 1, 30566, 24, 24, 31012, 'Walking_RewindAnim_03'),
            EnemyInfo(2, 'walking', 3, 523, 525, 1, 32428, 24, 24, 32550, 'Walking_Fire_02'),
            EnemyInfo(2, 'walking', 4, 484, 486, 1, 32728, 32, 32, 30204, 'Walking_Fire_01'),
            EnemyInfo(2, 'walking', 5, 519, 521, 1, 30566, 24, 24, 31012, 'Walking_RewindAnim_03'),
            EnemyInfo(2, 'walking', 6, 519, 521, 1, 30566, 24, 24, 31012, 'Walking_RewindAnim_03'),
            EnemyInfo(2, 'walking', 7, 519, 521, 1, 30566, 24, 24, 31012, 'Walking_RewindAnim_03'),
        ),
    },
    3: {
        'flying': (
            EnemyInfo(3, 'flying', 0, 484, 486, 1, 34722, 32, 32, 33624, 'Flying_Fire_01'),
            EnemyInfo(3, 'flying', 1, 521, 523, 1, 34538, 32, 32, 33624, 'Flying_Fire_01'),
            EnemyInfo(3, 'flying', 2, 484, 486, 1, 34722, 32, 32, 33624, 'Flying_Fire_01'),
        ),
        'walking': (
            EnemyInfo(3, 'walking', 0, 448, 450, 1, 32748, 32, 32, 30204, 'Walking_Fire_01'),
            EnemyInfo(3, 'walking', 1, 448, 450, 1, 32748, 32, 32, 30204, 'Walking_Fire_01'),
            EnemyInfo(3, 'walking', 2, 466, 468, 1, 32718, 32, 32, 30204, 'Walking_Fire_01'),
            EnemyInfo(3, 'walking', 3, 514, 516, 1, 31086, 24, 24, 31134, 'Walking_RewindAnim_04'),
            EnemyInfo(3, 'walking', 4, 448, 450, 1, 32748, 32, 32, 30204, 'Walking_Fire_01'),
            EnemyInfo(3, 'walking', 5, 448, 450, 1, 32748, 32, 32, 30204, 'Walking_Fire_01'),
            EnemyInfo(3, 'walking', 6, 448, 450, 1, 32748, 32, 32, 30204, 'Walking_Fire_01'),
        ),
    },
    4: {
        'flying': (
            EnemyInfo(4, 'flying', 0, 494, 496, 1, 34754, 32, 32, 33624, 'Flying_Fire_01'),
            EnemyInfo(4, 'flying', 1, 522, 524, 1, 34786, 32, 32, 33624, 'Flying_Fire_01'),
            EnemyInfo(4, 'flying', 2, 502, 504, 1, 34410, 32, 48, 34288, 'Flying_AnimUnk_02'),
            EnemyInfo(4, 'flying', 3, 529, 531, 1, 34222, 32, 32, 34174, 'Flying_AnimUnk_03'),
        ),
        'walking': (
            EnemyInfo(4, 'walking', 0, 448, 450, 1, 32708, 32, 32, 30204, 'Walking_Fire_01'),
            EnemyInfo(4, 'walking', 1, 484, 486, 1, 33150, 32, 32, 30204, 'Walking_Fire_01'),
            EnemyInfo(4, 'walking', 2, 466, 468, 1, 32698, 32, 32, 30204, 'Walking_Fire_01'),
            EnemyInfo(4, 'walking', 3, 545, 547, 1, 32388, 24, 24, 32550, 'Walking_Fire_02'),
            EnemyInfo(4, 'walking', 4, 484, 486, 1, 33150, 32, 32, 30204, 'Walking_Fire_01'),
            EnemyInfo(4, 'walking', 5, 484, 486, 1, 33150, 32, 32, 30204, 'Walking_Fire_01'),
            EnemyInfo(4, 'walking', 6, 484, 486, 1, 33150, 32, 32, 30204, 'Walking_Fire_01'),
        ),
    },
}

def get_enemy_info(level: int, kind: str, index: int) -> EnemyInfo | None:
    records = ENEMY_INFO_DATA.get(level, {}).get(kind, ())
    return records[index] if 0 <= index < len(records) else None

def iter_enemy_infos(level: int, kind: str | None = None) -> Iterable[EnemyInfo]:
    if kind is not None:
        yield from ENEMY_INFO_DATA.get(level, {}).get(kind, ())
        return
    yield from ENEMY_INFO_DATA.get(level, {}).get("flying", ())
    yield from ENEMY_INFO_DATA.get(level, {}).get("walking", ())
