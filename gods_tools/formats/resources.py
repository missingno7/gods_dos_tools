from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class GraphicsResource:
    stem: str
    pi1_path: Path
    dat_path: Path | None

    @property
    def display_name(self) -> str:
        if self.dat_path is not None:
            return f"{self.pi1_path.name}  +  {self.dat_path.name}"
        return self.pi1_path.name


def _resource_key(path: Path) -> str:
    # Packaged resources keep the original PC naming, e.g. PLEVEL1A.PI1.
    return path.stem.upper()


def discover_graphics_resources(game_dir: str | Path) -> list[GraphicsResource]:
    game_dir = Path(game_dir)
    pi1_files = sorted(game_dir.glob("P*.PI1"))
    dat_files = {_resource_key(path): path for path in game_dir.glob("P*.DAT")}

    resources: list[GraphicsResource] = []
    for pi1_path in pi1_files:
        stem = _resource_key(pi1_path)
        resources.append(
            GraphicsResource(
                stem=stem,
                pi1_path=pi1_path,
                dat_path=dat_files.get(stem),
            )
        )
    return resources


def iter_packed_game_files(game_dir: str | Path) -> Iterable[Path]:
    game_dir = Path(game_dir)
    yield from sorted(path for path in game_dir.iterdir() if path.is_file() and path.name.startswith("P"))
