from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


_LEVEL_MAP_RE = re.compile(r"^PLEV(?P<level>[1-4])(?P<world>[AB])\.MAP$", re.IGNORECASE)


@dataclass(frozen=True)
class LevelResource:
    level: int
    world: str
    map_path: Path
    bits_path: Path
    extra_path: Path | None
    alfils_path: Path | None
    flying_paths_path: Path | None

    @property
    def key(self) -> str:
        return f"{self.level}{self.world}"

    @property
    def display_name(self) -> str:
        extra = self.extra_path.name if self.extra_path is not None else "—"
        alfils = self.alfils_path.name if self.alfils_path is not None else "—"
        paths = self.flying_paths_path.name if self.flying_paths_path is not None else "—"
        return f"Level {self.level}{self.world}: {self.map_path.name} | tiles {self.bits_path.name} | extra {extra} | logic {alfils} | paths {paths}"


def _choose_extra_bank(game_dir: Path, level: int, world: str) -> Path | None:
    exact = game_dir / f"PXTRA{level}{world}.PI1"
    if exact.exists():
        return exact

    # The DOS PC data set included here has one XTRA bank per level, not per map half:
    # PXTRA1B, PXTRA2A, PXTRA3A, PXTRA4B. Both A/B halves of a level reference
    # tile ids above 120, so the single available level XTRA bank must be shared.
    matches = sorted(game_dir.glob(f"PXTRA{level}*.PI1"))
    if len(matches) == 1:
        return matches[0]
    return None


def discover_level_resources(game_dir: str | Path) -> list[LevelResource]:
    game_dir = Path(game_dir)
    resources: list[LevelResource] = []
    for map_path in sorted(game_dir.glob("PLEV*.MAP")):
        match = _LEVEL_MAP_RE.match(map_path.name)
        if match is None:
            continue
        level = int(match.group("level"))
        world = match.group("world").upper()
        bits_path = game_dir / f"PBITS{level}{world}.PI1"
        if not bits_path.exists():
            continue
        resources.append(
            LevelResource(
                level=level,
                world=world,
                map_path=map_path,
                bits_path=bits_path,
                extra_path=_choose_extra_bank(game_dir, level, world),
                alfils_path=(game_dir / f"PALFILS.0{world}{level}") if (game_dir / f"PALFILS.0{world}{level}").exists() else None,
                flying_paths_path=(game_dir / f"PGOD0{level}.PAT") if (game_dir / f"PGOD0{level}.PAT").exists() else None,
            )
        )
    return resources
