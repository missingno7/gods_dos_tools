from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import Iterable, Iterator

from gods_tools.formats.logic import LogicPoint
from gods_tools.formats.pc_logic_tables import (
    objective_locations,
    player_start_location,
    special_teleport_destinations,
)

from .document import LevelDocument


@dataclass(frozen=True)
class EntityKey:
    """Stable editor identity for a decoded logical or spatial entity."""

    family: str
    index: int | str
    variant: str = ""

    def display(self) -> str:
        suffix = f":{self.variant}" if self.variant else ""
        return f"{self.family}:{self.index}{suffix}"


@dataclass(frozen=True)
class IndexedEntity:
    """Canonical, GUI-neutral entity reference used by browser and edit prep."""

    key: EntityKey
    group: str
    label: str
    selection_kind: str
    payload: object
    pixel_x: int | None = None
    pixel_y: int | None = None

    @property
    def has_position(self) -> bool:
        return self.pixel_x is not None and self.pixel_y is not None


@dataclass(frozen=True)
class EntityIndex:
    """One normalized index over everything the editor can select/navigate."""

    groups: tuple[tuple[str, tuple[IndexedEntity, ...]], ...]

    def iter_groups(self) -> Iterator[tuple[str, tuple[IndexedEntity, ...]]]:
        return iter(self.groups)

    def iter_entities(self) -> Iterator[IndexedEntity]:
        for _group, entities in self.groups:
            yield from entities

    def by_group(self, group: str) -> tuple[IndexedEntity, ...]:
        for group_name, entities in self.groups:
            if group_name == group:
                return entities
        return ()

    def find(self, family: str, index: int | str, variant: str = "") -> IndexedEntity | None:
        key = EntityKey(family, index, variant)
        for entity in self.iter_entities():
            if entity.key == key:
                return entity
        return None

    @property
    def count(self) -> int:
        return sum(len(entities) for _group, entities in self.groups)

    def counts_by_group(self) -> tuple[tuple[str, int], ...]:
        return tuple((group, len(entities)) for group, entities in self.groups)


def _point_entity(
    *,
    family: str,
    group: str,
    index: int | str,
    label: str,
    kind: str,
    point: LogicPoint,
    variant: str = "",
) -> IndexedEntity:
    return IndexedEntity(
        key=EntityKey(family, index, variant),
        group=group,
        label=label,
        selection_kind=kind,
        payload=point,
        pixel_x=point.pixel_x,
        pixel_y=point.pixel_y,
    )


def _append_group(groups: "OrderedDict[str, list[IndexedEntity]]", name: str, entities: Iterable[IndexedEntity]) -> None:
    materialized = list(entities)
    if materialized:
        groups[name] = materialized


def build_entity_index(document: LevelDocument) -> EntityIndex:
    """Build a normalized selection index from one immutable level document.

    It intentionally stores raw payload objects rather than GUI wrapper classes.  The GUI
    decides how to present an enemy wave vs. a puzzle point; the index owns only identity,
    grouping, stable lookup, and common spatial coordinates.
    """

    groups: OrderedDict[str, list[IndexedEntity]] = OrderedDict()
    graph = document.logic_graph
    alfils = document.alfils_data
    map_data = document.map_data

    if graph is None or alfils is None:
        return EntityIndex(groups=())

    _append_group(
        groups,
        "Events",
        (
            IndexedEntity(
                key=EntityKey("event", event.index),
                group="Events",
                label=f"E{event.index}",
                selection_kind="event",
                payload=event,
                pixel_x=(graph.preferred_event_point(event.index).pixel_x if graph.preferred_event_point(event.index) is not None else None),
                pixel_y=(graph.preferred_event_point(event.index).pixel_y if graph.preferred_event_point(event.index) is not None else None),
            )
            for event in alfils.active_events
        ),
    )

    puzzle_entities: list[IndexedEntity] = []
    for puzzle in map_data.active_puzzles:
        point = graph.point_for_puzzle(puzzle.index)
        if point is None:
            continue
        puzzle_entities.append(_point_entity(
            family="puzzle",
            group="Puzzles",
            index=puzzle.index,
            label=f"P{puzzle.index}",
            kind="point",
            point=point,
        ))
    _append_group(groups, "Puzzles", puzzle_entities)

    switch_entities: list[IndexedEntity] = []
    for record in alfils.active_switches:
        point = graph.point_for_switch(record.index)
        if point is None:
            continue
        switch_entities.append(_point_entity(
            family="switch",
            group="Switches",
            index=record.index,
            label=f"S{record.index}",
            kind="point",
            point=point,
        ))
    _append_group(groups, "Switches", switch_entities)

    teleport_entities: list[IndexedEntity] = []
    for record in alfils.active_teleports:
        point = LogicPoint(record.marker_x, record.marker_y + 24, f"T{record.index}", "teleport", record.index)
        teleport_entities.append(_point_entity(
            family="teleport",
            group="Teleport table records",
            index=record.index,
            label=f"T{record.index}",
            kind="point",
            point=point,
        ))
    _append_group(groups, "Teleport table records", teleport_entities)

    hardcoded_entities: list[IndexedEntity] = []
    for record in special_teleport_destinations(document.level_number):
        point = LogicPoint(record.pixel_x, record.pixel_y + 24, f"HT{record.index}", "hardcoded_teleport_destination", record.index)
        hardcoded_entities.append(_point_entity(
            family="hardcoded_teleport",
            group="Hardcoded teleport destinations",
            index=record.index,
            label=f"HT{record.index}",
            kind="point",
            point=point,
        ))
    _append_group(groups, "Hardcoded teleport destinations", hardcoded_entities)

    objective_entities: list[IndexedEntity] = []
    for record in objective_locations(document.level_number):
        point = LogicPoint(record.pixel_x, record.pixel_y + 24, f"OBJ{record.index}", "objective_location", record.index)
        objective_entities.append(_point_entity(
            family="objective_location",
            group="Objective locations",
            index=record.index,
            label=f"OBJ{record.index}",
            kind="point",
            point=point,
        ))
    _append_group(groups, "Objective locations", objective_entities)

    start = player_start_location(document.level_number)
    if start is not None:
        point = LogicPoint(start.pixel_x + 16, start.pixel_y + 24, "START", "player_start", document.level_number)
        _append_group(groups, "Player start", [_point_entity(
            family="player_start",
            group="Player start",
            index=document.level_number,
            label="START",
            kind="point",
            point=point,
        )])

    hint_entities: list[IndexedEntity] = []
    for record in alfils.active_hints:
        point = LogicPoint(record.pixel_x, 8, f"H{record.index}", "hint", record.index)
        hint_entities.append(_point_entity(
            family="hint",
            group="Hints",
            index=record.index,
            label=f"H{record.index}",
            kind="point",
            point=point,
        ))
    _append_group(groups, "Hints", hint_entities)

    trapdoor_entities: list[IndexedEntity] = []
    for record in alfils.active_trapdoors:
        point = LogicPoint(record.pixel_x, record.pixel_y, f"D{record.index}", "trapdoor", record.index)
        trapdoor_entities.append(_point_entity(
            family="trapdoor",
            group="Trapdoors",
            index=record.index,
            label=f"D{record.index}",
            kind="point",
            point=point,
        ))
    _append_group(groups, "Trapdoors", trapdoor_entities)

    block_entities: list[IndexedEntity] = []
    for record in alfils.active_moving_blocks:
        point = LogicPoint(record.pixel_x, record.pixel_y, f"MB{record.index}", "moving_block", record.index)
        block_entities.append(_point_entity(
            family="moving_block",
            group="Moving blocks",
            index=record.index,
            label=f"MB{record.index}",
            kind="point",
            point=point,
        ))
    _append_group(groups, "Moving blocks", block_entities)

    wave_entities: list[IndexedEntity] = []
    for category, pool, kind in (
        ("WW", alfils.active_walking_waves, "walking_wave"),
        ("IW", alfils.active_intel_walking_waves, "intel_walking_wave"),
        ("IF", alfils.active_intel_flying_waves, "intel_flying_wave"),
    ):
        for wave in pool:
            wave_entities.append(IndexedEntity(
                key=EntityKey("wave", wave.index, category),
                group="Enemy waves",
                label=f"{category}{wave.index}",
                selection_kind="wave",
                payload=wave,
                pixel_x=wave.pixel_x,
                pixel_y=wave.pixel_y,
            ))
    for wave in alfils.active_flying_waves:
        wave_entities.append(IndexedEntity(
            key=EntityKey("wave", wave.index, "FW"),
            group="Enemy waves",
            label=f"FW{wave.index}",
            selection_kind="wave",
            payload=wave,
            pixel_x=None,
            pixel_y=None,
        ))
    _append_group(groups, "Enemy waves", wave_entities)

    if document.flying_paths is not None:
        _append_group(groups, "Flying paths", (
            IndexedEntity(
                key=EntityKey("flying_path", path.index),
                group="Flying paths",
                label=f"FP{path.index}",
                selection_kind="path",
                payload=path,
                pixel_x=None,
                pixel_y=None,
            )
            for path in document.flying_paths.paths
        ))

    target_kinds = {
        "spawned_object",
        "spawned_weapon",
        "door",
        "backdoor",
        "backdoor_destination",
        "backdoor_world",
        "destructable_object",
        "spawned_destructable_object",
        "destroy_type4_unresolved",
        "destroy_type4_offmap",
    }
    target_entities: list[IndexedEntity] = []
    seen_targets: set[tuple[str, int | None, int, int, str]] = set()
    for point in graph.unique_points():
        if point.kind not in target_kinds:
            continue
        target_key = (point.kind, point.index, point.pixel_x, point.pixel_y, point.label)
        if target_key in seen_targets:
            continue
        seen_targets.add(target_key)
        target_entities.append(_point_entity(
            family="logic_target",
            group="Physical logic targets",
            index=point.index if point.index is not None else point.label,
            variant=point.kind,
            label=point.label,
            kind="point",
            point=point,
        ))
    _append_group(groups, "Physical logic targets", target_entities)

    _append_group(groups, "Map items", (
        IndexedEntity(
            key=EntityKey("map_item", item.index),
            group="Map items",
            label=f"I{item.index}",
            selection_kind="item",
            payload=item,
            pixel_x=item.pixel_x,
            pixel_y=item.pixel_y,
        )
        for item in map_data.active_items
    ))

    return EntityIndex(groups=tuple((group, tuple(entities)) for group, entities in groups.items()))
