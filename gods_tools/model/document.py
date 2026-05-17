from __future__ import annotations

from dataclasses import dataclass

from gods_tools.formats.alfils import AlfilsData
from gods_tools.formats.diagnostics import LevelDiagnostics
from gods_tools.formats.flying_paths import FlyingPathsData
from gods_tools.formats.item_tables import ObjectTable, WeaponTable
from gods_tools.formats.levels import LevelResource
from gods_tools.formats.logic import LogicGraph
from gods_tools.formats.map import GodsMap
from gods_tools.render.sprites import SpriteBank


@dataclass(frozen=True)
class LevelDocument:
    """Immutable, editor-facing snapshot of one decoded GODS level.

    The old GUI grew around a view-specific ``LoadedLevel`` bag.  Future edit mode
    needs a stable document boundary: all decoded source data, the derived logic graph,
    and optional presentation resources live here, while rendering and edit sessions stay
    outside of it.
    """

    resource: LevelResource
    map_data: GodsMap
    alfils_data: AlfilsData | None
    object_table: ObjectTable | None
    weapon_table: WeaponTable | None
    sprite_bank: SpriteBank | None
    flying_paths: FlyingPathsData | None
    logic_graph: LogicGraph | None
    diagnostics: LevelDiagnostics | None

    @property
    def key(self) -> str:
        return self.resource.key

    @property
    def level_number(self) -> int:
        return self.resource.level

    @property
    def world_suffix(self) -> str:
        return self.resource.world

    @property
    def has_logic(self) -> bool:
        return self.alfils_data is not None and self.logic_graph is not None

    @property
    def map_payload_size(self) -> int:
        return len(self.map_data.raw_payload)

    @property
    def alfils_payload_size(self) -> int | None:
        return len(self.alfils_data.raw_payload) if self.alfils_data is not None else None
