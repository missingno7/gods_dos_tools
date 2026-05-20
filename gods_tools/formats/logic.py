from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .alfils import AlfilsData, EventRecord
from .map import GodsMap, MapPuzzle, MAP_CELL_HEIGHT, MAP_CELL_WIDTH, MAP_HEIGHT_CELLS, MAP_WIDTH_CELLS
from .item_tables import ObjectTable, WeaponTable

# Names copied from Kroah's Gods Viewer enums. Keeping them in one place makes the
# relationship layer useful both to the GUI and to future write-back/editor work.
CONDITION_TYPE_NAMES: dict[int, str] = {
    0: "True",
    1: "Carrying",
    2: "NotCarrying",
    3: "Holding",
    4: "NotHolding",
    5: "EventTriggered",
    6: "EventNotTriggered",
    7: "HealthGreaterThan",
    8: "HealthLowerThan",
    9: "TimeGreaterThan",
    10: "TimeLowerThan",
    11: "SwitchOn",
    12: "SwitchOff",
    13: "ScoreGreaterThan",
    14: "ScoreLowerThan",
    15: "LivesGreaterThan",
    16: "LivesLowerThan",
}

PUZZLE_EFFECT_NAMES: dict[int, str] = {
    0: "SpawnObject",
    1: "SpawnWeapon",
    2: "OpenDoor",
    3: "OpenBackdoorTeleport",
    4: "OpenBackdoorWorldCompleted",
    5: "TriggerEvent",
    6: "DestroyType4",
    7: "OpenTrapdoor",
    8: "CloseTrapdoor",
    9: "CloseDoor",
    10: "RemoveWeapon",
    11: "EnableRaster",
    12: "DisableRaster",
    13: "NoEffect",
    14: "ResetGlobalTimer",
}


def condition_type_name(index: int) -> str:
    return CONDITION_TYPE_NAMES.get(index, f"UnknownCondition{index}")


def puzzle_effect_name(index: int) -> str:
    return PUZZLE_EFFECT_NAMES.get(index, f"UnknownEffect{index}")


def decode_teleport_target(coded: int) -> tuple[int, int]:
    """Decode GODS' packed teleport target to map pixels.

    Kroah's viewer uses the same formula for backdoor teleport destinations:
      X = high_byte * 32 + 16
      Y = low_byte  * 16
    """

    return ((coded >> 8) * MAP_CELL_WIDTH + MAP_CELL_WIDTH // 2, (coded & 0x00FF) * MAP_CELL_HEIGHT)


def _map_item_point(item, label: str | None = None, kind: str = "map_item") -> "LogicPoint":
    return LogicPoint(
        item.pixel_x,
        item.pixel_y,
        label or f"I{item.index}",
        kind,
        item.index,
    )


def _puzzle_spawn_point(puzzle: MapPuzzle, label: str, kind: str) -> "LogicPoint":
    return LogicPoint(puzzle.pixel_x, puzzle.pixel_y, label, kind, puzzle.index)


def _wave_reward_point(prefix: str, index: int, pixel_x: int, pixel_y: int, reward_index: int, kind: str) -> "LogicPoint":
    return LogicPoint(pixel_x, pixel_y, f"{prefix}{index}/R{reward_index}", kind, index)


def _logical_reward_point(prefix: str, index: int, reward_index: int, kind: str) -> "LogicPoint":
    return LogicPoint(0, 0, f"{prefix}{index}/R{reward_index}", kind, index)


def _object_source_points(
    graph: "LogicGraph",
    object_info_index: int,
    *,
    fallback: bool = False,
) -> tuple["LogicPoint", ...]:
    """Return every known editor-facing source of an object-info index.

    Sources can be initial map items, puzzle-spawned objects, or wave rewards. Ordinary
    flying-wave rewards are real but not tied to one static map position before their trigger
    event resolves a .PAT path, so they stay as non-spatial logic points here.
    """

    points: list[LogicPoint] = []
    for item in graph.map_data.active_items:
        if item.is_object and item.object_or_weapon_info_index == object_info_index:
            points.append(_map_item_point(item, f"I{item.index}/OBJ{object_info_index}", "map_object_source"))

    for puzzle in graph.map_data.active_puzzles:
        if puzzle.effect_function_index == 0 and puzzle.effect_param == object_info_index:
            points.append(_puzzle_spawn_point(puzzle, f"P{puzzle.index}/SPO{object_info_index}", "spawned_object_source"))

    for wave in graph.alfils_data.active_walking_waves:
        if wave.reward_kind == "object" and wave.reward_info_index == object_info_index:
            points.append(_wave_reward_point("WW", wave.index, wave.pixel_x, wave.pixel_y, object_info_index, "walking_reward_object"))
    for wave in graph.alfils_data.active_intel_walking_waves:
        if wave.reward_kind == "object" and wave.reward_info_index == object_info_index:
            points.append(_wave_reward_point("IW", wave.index, wave.pixel_x, wave.pixel_y, object_info_index, "intel_walking_reward_object"))
    for wave in graph.alfils_data.active_intel_flying_waves:
        if wave.reward_kind == "object" and wave.reward_info_index == object_info_index:
            points.append(_wave_reward_point("IF", wave.index, wave.pixel_x, wave.pixel_y, object_info_index, "intel_flying_reward_object"))
    for wave in graph.alfils_data.active_flying_waves:
        if wave.reward_kind == "object" and wave.reward_info_index == object_info_index:
            points.append(_logical_reward_point("FW", wave.index, object_info_index, "flying_reward_object"))

    if points or not fallback:
        return tuple(points)
    return (LogicPoint(0, 0, f"OBJ{object_info_index}", "object_inventory_ref", object_info_index),)


def _object_condition_sources(graph: "LogicGraph", object_info_index: int) -> tuple["LogicPoint", ...]:
    """Return object sources for Carrying / NotCarrying puzzle conditions."""

    return _object_source_points(graph, object_info_index, fallback=True)


def _weapon_condition_sources(graph: "LogicGraph", weapon_info_index: int) -> tuple["LogicPoint", ...]:
    points: list[LogicPoint] = []
    encoded_map_weapon_id = weapon_info_index + 192
    for item in graph.map_data.active_items:
        if item.is_weapon and item.object_or_weapon_info_index == encoded_map_weapon_id:
            points.append(_map_item_point(item, f"I{item.index}/WPN{weapon_info_index}", "map_weapon_source"))

    for puzzle in graph.map_data.active_puzzles:
        if puzzle.effect_function_index == 1 and puzzle.effect_param == weapon_info_index:
            points.append(_puzzle_spawn_point(puzzle, f"P{puzzle.index}/WPN{weapon_info_index}", "spawned_weapon_source"))

    for wave in graph.alfils_data.active_walking_waves:
        if wave.reward_kind == "weapon" and wave.reward_info_index == weapon_info_index:
            points.append(_wave_reward_point("WW", wave.index, wave.pixel_x, wave.pixel_y, weapon_info_index, "walking_reward_weapon"))
    for wave in graph.alfils_data.active_intel_walking_waves:
        if wave.reward_kind == "weapon" and wave.reward_info_index == weapon_info_index:
            points.append(_wave_reward_point("IW", wave.index, wave.pixel_x, wave.pixel_y, weapon_info_index, "intel_walking_reward_weapon"))
    for wave in graph.alfils_data.active_intel_flying_waves:
        if wave.reward_kind == "weapon" and wave.reward_info_index == weapon_info_index:
            points.append(_wave_reward_point("IF", wave.index, wave.pixel_x, wave.pixel_y, weapon_info_index, "intel_flying_reward_weapon"))
    for wave in graph.alfils_data.active_flying_waves:
        if wave.reward_kind == "weapon" and wave.reward_info_index == weapon_info_index:
            points.append(_logical_reward_point("FW", wave.index, weapon_info_index, "flying_reward_weapon"))

    if points:
        return tuple(points)
    return (LogicPoint(0, 0, f"WPN{weapon_info_index}", "weapon_inventory_ref", weapon_info_index),)


def _anchored_puzzle_position(index: int, pixel_x: int, pixel_y: int, *, above: bool = False) -> tuple[int, int]:
    if pixel_x != 0 or pixel_y != 0:
        return pixel_x, max(0, pixel_y - 18) if above else pixel_y
    x, y = 16 + (index % 12) * 48, 16 + (index // 12) * 22
    return x, max(0, y - 18) if above else y


def _state_condition_point(puzzle: MapPuzzle, cond_type: int, cond_param: int) -> "LogicPoint" | None:
    x, y = _anchored_puzzle_position(puzzle.index, puzzle.pixel_x, puzzle.pixel_y, above=True)
    if cond_type == 7:
        return LogicPoint(x, y, f"P{puzzle.index}/HP>{cond_param}/24", "health_condition")
    if cond_type == 8:
        return LogicPoint(x, y, f"P{puzzle.index}/HP<{cond_param}/24", "health_condition")
    if cond_type == 9:
        return LogicPoint(x, y, f"P{puzzle.index}/TIME>{cond_param * 5}s", "time_condition")
    if cond_type == 10:
        return LogicPoint(x, y, f"P{puzzle.index}/TIME<{cond_param * 5}s", "time_condition")
    if cond_type == 13:
        return LogicPoint(x, y, f"P{puzzle.index}/SCORE>{cond_param * 5000}", "score_condition")
    if cond_type == 14:
        return LogicPoint(x, y, f"P{puzzle.index}/SCORE<{cond_param * 5000}", "score_condition")
    if cond_type == 15:
        return LogicPoint(x, y, f"P{puzzle.index}/LIVES>{cond_param}", "lives_condition")
    if cond_type == 16:
        return LogicPoint(x, y, f"P{puzzle.index}/LIVES<{cond_param}", "lives_condition")
    return None


def _non_spatial_effect_point(effect_type: int, effect_param: int) -> tuple["LogicPoint", str] | None:
    if effect_type == 10:
        return LogicPoint(0, 0, f"REMOVE-WPN{effect_param}", "remove_weapon_effect", effect_param), "removes held weapon"
    if effect_type == 11:
        return LogicPoint(0, 0, "RASTER=ON", "raster_effect", 1), "enables raster"
    if effect_type == 12:
        return LogicPoint(0, 0, "RASTER=OFF", "raster_effect", 0), "disables raster"
    if effect_type == 14:
        return LogicPoint(0, 0, "TIMER=RESET", "timer_effect", 0), "resets elapsed time"
    return None


def _teleport_stone_source_points(graph: "LogicGraph", src_pixel_x: int) -> tuple["LogicPoint", ...]:
    if graph.object_table is None:
        return ()
    points: list[LogicPoint] = []

    for item in graph.map_data.active_items:
        if not item.is_object or item.pixel_x != src_pixel_x:
            continue
        info = graph.object_table.get(item.object_or_weapon_info_index)
        if info is not None and info.is_teleport_stone:
            points.append(_map_item_point(item, f"I{item.index}/TP", "teleport_stone"))

    for puzzle in graph.map_data.active_puzzles:
        if puzzle.effect_function_index != 0 or puzzle.pixel_x != src_pixel_x:
            continue
        info = graph.object_table.get(puzzle.effect_param)
        if info is not None and info.is_teleport_stone:
            points.append(_puzzle_spawn_point(puzzle, f"P{puzzle.index}/TP", "spawned_teleport_stone"))

    return tuple(points)


def _hint_point_at_x(graph: "LogicGraph", pixel_x: int) -> "LogicPoint" | None:
    for hint in graph.alfils_data.active_hints:
        if hint.pixel_x == pixel_x:
            return LogicPoint(hint.pixel_x, 8, f"H{hint.index}", "hint", hint.index)
    return None


def _nearest_destructable_item_point(graph: "LogicGraph", puzzle: MapPuzzle) -> tuple["LogicPoint", str] | None:
    """Resolve DestroyType4 to a concrete map/spawned type-4 object when metadata is available."""

    if graph.object_table is None:
        return None

    candidates: list[tuple[int, str, int, int, int, str]] = []
    for item in graph.map_data.active_items:
        if not item.is_object:
            continue
        info = graph.object_table.get(item.object_or_weapon_info_index)
        if info is None or not info.is_destructable:
            continue
        dx = item.pixel_x - puzzle.pixel_x
        dy = item.pixel_y - puzzle.pixel_y
        dist2 = dx * dx + dy * dy
        candidates.append((dist2, "map_item", item.index, item.pixel_x, item.pixel_y, info.full_name))

    # Some GODS scripts first spawn a type-4 destructable object and later destroy it.
    # Those targets are puzzle spawn effects, not entries in the initial map-item table.
    for spawned in graph.map_data.active_puzzles:
        if spawned.effect_function_index != 0:  # SpawnObject
            continue
        info = graph.object_table.get(spawned.effect_param)
        if info is None or not info.is_destructable:
            continue
        dx = spawned.pixel_x - puzzle.pixel_x
        dy = spawned.pixel_y - puzzle.pixel_y
        dist2 = dx * dx + dy * dy
        candidates.append((dist2, "spawned", spawned.index, spawned.pixel_x, spawned.pixel_y, info.full_name))

    if not candidates:
        return None

    dist2, source_kind, source_index, target_x, target_y, full_name = min(candidates, key=lambda row: row[0])
    # DOS data typically points exactly at the object; a small tolerance covers the few cases
    # where positions differ by a handful of pixels in the original tables.
    if dist2 > 16 * 16:
        return None

    pretty = full_name if full_name != "—" else "type-4 object"
    if source_kind == "map_item":
        return (
            LogicPoint(target_x, target_y, f"I{source_index}", "destructable_object", source_index),
            f"destroys destructable map item I{source_index} ({pretty})",
        )
    return (
        LogicPoint(target_x, target_y, f"P{source_index}/SPO", "spawned_destructable_object", source_index),
        f"destroys spawned destructable object from P{source_index} ({pretty})",
    )


def _puzzle_effect_points(graph: "LogicGraph", puzzle: MapPuzzle) -> tuple[tuple["LogicPoint", str], ...]:
    """Return concrete map points touched by a puzzle effect.

    These are intentionally editor-centric abstractions: the raw puzzle stays intact,
    but the graph can point to the actual spatial consequence of the effect.
    """

    effect_type = puzzle.effect_function_index
    effect_param = puzzle.effect_param
    x, y = puzzle.pixel_x, puzzle.pixel_y

    if effect_type == 0:  # SpawnObject
        return ((LogicPoint(x, y, f"SPO{effect_param}", "spawned_object", effect_param), "spawns object"),)
    if effect_type == 1:  # SpawnWeapon
        return ((LogicPoint(x, y, f"WPN{effect_param}", "spawned_weapon", effect_param), "spawns weapon"),)
    if effect_type in (2, 9):  # OpenDoor / CloseDoor; door is 32x48 from puzzle XY.
        verb = "opens door" if effect_type == 2 else "closes door"
        return ((LogicPoint(x + 16, y + 24, f"DOOR{puzzle.index}", "door", puzzle.index), verb),)
    if effect_type == 3:  # OpenBackdoorTeleport
        # Kroah: backdoor rectangle begins at (x-16, y), so its center is (x, y+24).
        target_x, target_y = decode_teleport_target(effect_param)
        return (
            (LogicPoint(x, y + 24, f"BD{puzzle.index}", "backdoor", puzzle.index), "opens backdoor teleport"),
            (LogicPoint(target_x, target_y + 24, f"BD→{effect_param:04X}", "backdoor_destination", effect_param), "backdoor destination"),
        )
    if effect_type == 4:  # OpenBackdoorWorldCompleted
        return ((LogicPoint(x, y + 24, f"WORLD{puzzle.index}", "backdoor_world", puzzle.index), "opens world-complete backdoor"),)
    if effect_type == 6:  # DestroyType4 = destroy the destructable object at/near the puzzle point.
        resolved = _nearest_destructable_item_point(graph, puzzle)
        if resolved is not None:
            return (resolved,)
        # PLEV3A/P27 is a real off-map script record: a map event tests whether the
        # player is carrying the gold treasure chest, then executes DestroyType4 at
        # (0,0). It is not a failed map-object match, so keep it logical/off-map.
        if x == 0 and y == 0:
            return ((LogicPoint(x, y, f"TYPE4∅{puzzle.index}", "destroy_type4_offmap", puzzle.index), "executes off-map DestroyType4 effect"),)
        return ((LogicPoint(x, y, f"TYPE4?{puzzle.index}", "destroy_type4_unresolved", puzzle.index), "destroys type-4 object (unresolved target)"),)
    return ()

@dataclass(frozen=True)
class LogicPoint:
    """A concrete point in the rendered map, expressed in source image pixels."""

    pixel_x: int
    pixel_y: int
    label: str
    kind: str
    index: int | None = None


@dataclass(frozen=True)
class LogicEdge:
    source: LogicPoint
    target: LogicPoint
    label: str
    edge_kind: str
    positive_state: bool | None = None


@dataclass(frozen=True)
class LogicGraph:
    map_data: GodsMap
    alfils_data: AlfilsData
    event_cells: dict[int, tuple[tuple[int, int], ...]]
    all_edges: tuple[LogicEdge, ...]
    object_table: ObjectTable | None = None
    weapon_table: WeaponTable | None = None

    def event(self, index: int) -> EventRecord | None:
        return self.alfils_data.event(index)

    def event_cell_points(self, index: int) -> tuple[LogicPoint, ...]:
        cells = self.event_cells.get(index, ())
        return tuple(
            LogicPoint(
                cell_x * MAP_CELL_WIDTH + MAP_CELL_WIDTH // 2,
                cell_y * MAP_CELL_HEIGHT + MAP_CELL_HEIGHT // 2,
                f"E{index}",
                "event_cell",
                index,
            )
            for cell_x, cell_y in cells
        )

    def preferred_event_point(self, index: int) -> LogicPoint | None:
        points = self.event_cell_points(index)
        return points[0] if points else None

    def point_for_puzzle(self, index: int) -> LogicPoint | None:
        if not (0 <= index < len(self.map_data.puzzles)):
            return None
        puzzle = self.map_data.puzzles[index]
        if puzzle.appears_unused:
            return None
        x, y = _anchored_puzzle_position(index, puzzle.pixel_x, puzzle.pixel_y)
        return LogicPoint(x, y, f"P{index}", "puzzle", index)

    def point_for_switch(self, index: int) -> LogicPoint | None:
        if not (0 <= index < len(self.alfils_data.switches)):
            return None
        record = self.alfils_data.switches[index]
        if not record.appears_used:
            return None
        return LogicPoint(record.pixel_x, record.pixel_y, f"S{index}", "switch", index)

    def outgoing_edges_for_event(self, index: int) -> tuple[LogicEdge, ...]:
        return tuple(edge for edge in self.all_edges if edge.source.kind == "event_cell" and edge.source.index == index)

    def incoming_edges_for_event(self, index: int) -> tuple[LogicEdge, ...]:
        return tuple(edge for edge in self.all_edges if edge.target.kind in {"event_cell", "event_effect"} and edge.target.index == index)

    def related_edges_for_event(self, index: int, recursive: bool = True) -> tuple[LogicEdge, ...]:
        """Return edges relevant to an event, following TriggerEvent / event conditions.

        This mirrors the useful part of Kroah's "recursive events" behavior, but keeps the
        graph model independent from drawing code.
        """

        selected: list[LogicEdge] = []
        seen_edge_ids: set[int] = set()
        event_queue: list[int] = [index]
        seen_events: set[int] = set()

        while event_queue:
            event_index = event_queue.pop(0)
            if event_index in seen_events:
                continue
            seen_events.add(event_index)

            for edge in self.all_edges:
                touches = (
                    (edge.source.kind == "event_cell" and edge.source.index == event_index)
                    or (edge.target.kind in {"event_cell", "event_effect"} and edge.target.index == event_index)
                )
                if not touches:
                    continue
                edge_id = id(edge)
                if edge_id not in seen_edge_ids:
                    seen_edge_ids.add(edge_id)
                    selected.append(edge)
                if recursive:
                    for point in (edge.source, edge.target):
                        if point.kind in {"event_cell", "event_effect"} and point.index is not None:
                            if point.index not in seen_events:
                                event_queue.append(point.index)

            # Follow event -> puzzle -> event and event-condition dependencies via puzzle nodes.
            if recursive:
                puzzle_ids = {
                    edge.target.index
                    for edge in selected
                    if edge.source.kind == "event_cell"
                    and edge.source.index == event_index
                    and edge.target.kind == "puzzle"
                    and edge.target.index is not None
                }
                for edge in self.all_edges:
                    puzzle_touch = (
                        (edge.source.kind == "puzzle" and edge.source.index in puzzle_ids)
                        or (edge.target.kind == "puzzle" and edge.target.index in puzzle_ids)
                    )
                    if not puzzle_touch:
                        continue
                    edge_id = id(edge)
                    if edge_id not in seen_edge_ids:
                        seen_edge_ids.add(edge_id)
                        selected.append(edge)
                    for point in (edge.source, edge.target):
                        if point.kind in {"event_cell", "event_effect"} and point.index is not None:
                            if point.index not in seen_events:
                                event_queue.append(point.index)

        return tuple(selected)

    @staticmethod
    def _point_key(point: LogicPoint) -> tuple[str, int | None, int, int, str]:
        return (point.kind, point.index, point.pixel_x, point.pixel_y, point.label)

    @staticmethod
    def _same_graph_node(left: LogicPoint, right: LogicPoint) -> bool:
        if left.kind != right.kind:
            return False
        if left.index is not None or right.index is not None:
            return left.index == right.index
        return (left.pixel_x, left.pixel_y, left.label) == (right.pixel_x, right.pixel_y, right.label)

    def unique_points(self) -> tuple[LogicPoint, ...]:
        points: list[LogicPoint] = []
        seen: set[tuple[str, int | None, int, int, str]] = set()
        for edge in self.all_edges:
            for point in (edge.source, edge.target):
                key = self._point_key(point)
                if key in seen:
                    continue
                seen.add(key)
                points.append(point)
        return tuple(points)

    def pick_point(self, pixel_x: int, pixel_y: int, max_distance: int = 24) -> LogicPoint | None:
        """Return the nearest concrete logic point near the click position.

        This intentionally ignores purely off-map/logical nodes: they are useful in the
        inspector, but cannot be selected from the rendered level surface.
        """

        non_pickable = {
            "event_effect",
            "flying_wave",
            "checkpoint",
            "guardian",
            "destroy_type4_offmap",
            "object_inventory_ref",
            "weapon_inventory_ref",
            "flying_reward_object",
            "flying_reward_weapon",
            "health_condition",
            "time_condition",
            "score_condition",
            "lives_condition",
            "remove_weapon_effect",
            "raster_effect",
            "timer_effect",
        }
        # When multiple nodes share the same coordinates, prefer the concrete thing the
        # user likely clicked over the abstract puzzle anchor that drives it.
        priority = {
            "destructable_object": 0,
            "spawned_destructable_object": 0,
            "door": 0,
            "backdoor": 0,
            "backdoor_destination": 0,
            "backdoor_world": 0,
            "spawned_object": 0,
            "spawned_weapon": 0,
            "trapdoor": 0,
            "teleport_stone": 0,
            "spawned_teleport_stone": 0,
            "map_object_source": 0,
            "map_weapon_source": 0,
            "spawned_object_source": 0,
            "spawned_weapon_source": 0,
            "walking_reward_object": 1,
            "walking_reward_weapon": 1,
            "intel_walking_reward_object": 1,
            "intel_walking_reward_weapon": 1,
            "intel_flying_reward_object": 1,
            "intel_flying_reward_weapon": 1,
            "walking_wave": 1,
            "intel_walking_wave": 1,
            "intel_flying_wave": 1,
            "moving_block": 1,
            "switch": 1,
            "event_cell": 2,
            "puzzle": 3,
        }
        candidates: list[tuple[int, int, LogicPoint]] = []
        for point in self.unique_points():
            if point.kind in non_pickable:
                continue
            dx = point.pixel_x - pixel_x
            dy = point.pixel_y - pixel_y
            dist2 = dx * dx + dy * dy
            if dist2 <= max_distance * max_distance:
                candidates.append((dist2, priority.get(point.kind, 2), point))
        if not candidates:
            return None
        return min(candidates, key=lambda row: (row[0], row[1]))[2]

    def direct_edges_for_point(self, point: LogicPoint) -> tuple[LogicEdge, ...]:
        return tuple(
            edge
            for edge in self.all_edges
            if self._same_graph_node(edge.source, point) or self._same_graph_node(edge.target, point)
        )

    def related_edges_for_point(self, point: LogicPoint, recursive: bool = True) -> tuple[LogicEdge, ...]:
        """Return a connected logic subgraph centered on a selected point.

        This is the reverse-facing cousin of ``related_edges_for_event``: clicking a
        door, destructible target, spawned object, teleport target, or wave now exposes
        the upstream event/puzzle machinery that drives it.
        """

        selected: list[LogicEdge] = []
        seen_edges: set[int] = set()
        queue: list[LogicPoint] = [point]
        seen_points: set[tuple[str, int | None, int, int, str]] = set()

        while queue:
            current = queue.pop(0)
            current_key = self._point_key(current)
            if current_key in seen_points:
                continue
            seen_points.add(current_key)

            for edge in self.all_edges:
                touches_source = self._same_graph_node(edge.source, current)
                touches_target = self._same_graph_node(edge.target, current)
                if not (touches_source or touches_target):
                    continue
                edge_id = id(edge)
                if edge_id not in seen_edges:
                    seen_edges.add(edge_id)
                    selected.append(edge)
                if not recursive:
                    continue
                other = edge.target if touches_source else edge.source
                if self._point_key(other) not in seen_points:
                    queue.append(other)

        return tuple(selected)

    _MAP_ITEM_POINT_KINDS = {
        "map_item",
        "switch_item",
        "teleport_stone",
        "map_object_source",
        "map_weapon_source",
        "destructable_object",
    }

    def points_for_map_item(self, item_index: int) -> tuple[LogicPoint, ...]:
        """Return logic graph nodes that represent one concrete initial map-item slot.

        A single visible object can play several roles at once. A switch item has a
        physical-item node and a PALFILS switch-state node; a teleport stone binds to a
        teleport record; a key/weapon may be a source for inventory puzzle conditions;
        a destructable may be a concrete DestroyType4 target. The object inspector uses
        this bundle to expose all of those relations without flattening them into one
        lossy synthetic node.
        """

        points: list[LogicPoint] = []
        seen: set[tuple[str, int | None, int, int, str]] = set()
        for point in self.unique_points():
            if point.kind not in self._MAP_ITEM_POINT_KINDS or point.index != item_index:
                continue
            key = self._point_key(point)
            if key in seen:
                continue
            seen.add(key)
            points.append(point)
        return tuple(points)

    def preferred_point_for_map_item(self, item_index: int) -> LogicPoint | None:
        points = self.points_for_map_item(item_index)
        if not points:
            return None
        priority = {
            "switch_item": 0,
            "teleport_stone": 1,
            "destructable_object": 2,
            "map_object_source": 3,
            "map_weapon_source": 3,
            "map_item": 4,
        }
        return min(points, key=lambda point: priority.get(point.kind, 99))

    def direct_edges_for_map_item(self, item_index: int) -> tuple[LogicEdge, ...]:
        points = self.points_for_map_item(item_index)
        selected: list[LogicEdge] = []
        seen_edges: set[int] = set()
        bound_role_points: list[LogicPoint] = []
        for point in points:
            for edge in self.direct_edges_for_point(point):
                edge_id = id(edge)
                if edge_id in seen_edges:
                    continue
                seen_edges.add(edge_id)
                selected.append(edge)
                other = edge.target if self._same_graph_node(edge.source, point) else edge.source
                if edge.edge_kind in {"switch_binding", "teleport_binding"}:
                    bound_role_points.append(other)
        for point in bound_role_points:
            for edge in self.direct_edges_for_point(point):
                edge_id = id(edge)
                if edge_id in seen_edges:
                    continue
                seen_edges.add(edge_id)
                selected.append(edge)
        return tuple(selected)

    def related_edges_for_map_item(self, item_index: int, recursive: bool = True) -> tuple[LogicEdge, ...]:
        points = self.points_for_map_item(item_index)
        selected: list[LogicEdge] = []
        seen_edges: set[int] = set()
        for point in points:
            for edge in self.related_edges_for_point(point, recursive=recursive):
                edge_id = id(edge)
                if edge_id in seen_edges:
                    continue
                seen_edges.add(edge_id)
                selected.append(edge)
        return tuple(selected)

    def describe_point(self, point: LogicPoint, recursive: bool = True) -> str:
        direct = self.direct_edges_for_point(point)
        related = self.related_edges_for_point(point, recursive=recursive)
        incoming = tuple(edge for edge in direct if self._same_graph_node(edge.target, point))
        outgoing = tuple(edge for edge in direct if self._same_graph_node(edge.source, point))

        lines = [
            f"Logic point {point.label}",
            f"  Kind:     {point.kind}",
            f"  Position: ({point.pixel_x}, {point.pixel_y})",
        ]
        if point.index is not None:
            lines.append(f"  Index:    {point.index}")

        lines.extend(["", "Direct incoming links:"])
        if incoming:
            for edge in incoming:
                lines.append(f"  {edge.label}: {edge.source.label} → {edge.target.label}")
        else:
            lines.append("  —")

        lines.extend(["", "Direct outgoing links:"])
        if outgoing:
            for edge in outgoing:
                lines.append(f"  {edge.label}: {edge.source.label} → {edge.target.label}")
        else:
            lines.append("  —")

        upstream_events = sorted({
            edge.source.index
            for edge in related
            if edge.source.kind == "event_cell" and edge.source.index is not None
        })
        if upstream_events:
            lines.extend(["", "Upstream map event indices:", "  " + ", ".join(f"E{index}" for index in upstream_events)])

        lines.extend(["", f"Visible logic links ({'recursive component' if recursive else 'direct'}): {len(related)}"])
        for edge in related[:160]:
            state = ""
            if edge.positive_state is True:
                state = " [state=true]"
            elif edge.positive_state is False:
                state = " [state=false]"
            lines.append(f"  {edge.source.label} → {edge.target.label}: {edge.label}{state}")
        if len(related) > 160:
            lines.append(f"  ... {len(related) - 160} more")
        return "\n".join(lines)

    def describe_event(self, index: int, recursive: bool = True) -> str:
        event = self.event(index)
        if event is None:
            return f"E{index}: layer/map references an unused PALFILS event slot."

        lines = [
            f"Event E{index}",
            f"  Type:  {event.type_name}",
            f"  Param: {event.param}",
        ]
        cells = self.event_cells.get(index, ())
        if cells:
            lines.append("  Map cells: " + ", ".join(f"({x},{y})" for x, y in cells))
        else:
            lines.append("  Map cells: — direct trigger not present; this event is likely effect-triggered")

        direct = self.outgoing_edges_for_event(index)
        incoming = self.incoming_edges_for_event(index)
        lines.extend(["", "Direct outgoing links:"])
        if direct:
            for edge in direct:
                lines.append(f"  {edge.label}: {edge.source.label} → {edge.target.label}")
        else:
            lines.append("  —")

        lines.extend(["", "Incoming event/puzzle links:"])
        if incoming:
            for edge in incoming:
                lines.append(f"  {edge.label}: {edge.source.label} → {edge.target.label}")
        else:
            lines.append("  —")

        related = self.related_edges_for_event(index, recursive=recursive)
        lines.extend(["", f"Visible logic links ({'recursive' if recursive else 'direct'}): {len(related)}"])
        for edge in related[:120]:
            state = ""
            if edge.positive_state is True:
                state = " [state=true]"
            elif edge.positive_state is False:
                state = " [state=false]"
            lines.append(f"  {edge.source.label} → {edge.target.label}: {edge.label}{state}")
        if len(related) > 120:
            lines.append(f"  ... {len(related) - 120} more")
        return "\n".join(lines)


def _iter_event_cells(map_data: GodsMap) -> dict[int, tuple[tuple[int, int], ...]]:
    cells: dict[int, list[tuple[int, int]]] = {}
    for y in range(MAP_HEIGHT_CELLS):
        for x in range(MAP_WIDTH_CELLS):
            value = map_data.layer_b_at(x, y)
            if value < 3:
                continue
            cells.setdefault(value - 3, []).append((x, y))
    return {index: tuple(points) for index, points in cells.items()}


def _event_target_point(graph: LogicGraph, event: EventRecord) -> tuple[LogicPoint | None, str | None]:
    event_type = event.event_type_index
    if event_type is None:
        return None, None
    param = event.param

    if event_type == 0:  # flying waves do not have a single static spawn marker in PALFILS
        return LogicPoint(0, 0, f"FW{param}", "flying_wave", param), "spawns flying wave"
    if event_type == 1 and 0 <= param < len(graph.alfils_data.walking_waves):
        wave = graph.alfils_data.walking_waves[param]
        if wave.appears_used:
            return LogicPoint(wave.pixel_x, wave.pixel_y, f"WW{param}", "walking_wave", param), "spawns walking wave"
    if event_type == 2:
        point = graph.point_for_puzzle(param)
        if point is not None:
            return point, "checks puzzle"
    if event_type == 3 and 0 <= param < len(graph.alfils_data.intel_walking_waves):
        wave = graph.alfils_data.intel_walking_waves[param]
        if wave.appears_used:
            return LogicPoint(wave.pixel_x, wave.pixel_y, f"IW{param}", "intel_walking_wave", param), "spawns intelligent walking wave"
    if event_type == 4 and 0 <= param < len(graph.alfils_data.intel_flying_waves):
        wave = graph.alfils_data.intel_flying_waves[param]
        if wave.appears_used:
            return LogicPoint(wave.pixel_x, wave.pixel_y, f"IF{param}", "intel_flying_wave", param), "spawns intelligent flying wave"
    if 6 <= event_type <= 9 and 0 <= param < len(graph.alfils_data.moving_blocks):
        block = graph.alfils_data.moving_blocks[param]
        if block.appears_used:
            action_index = event_type - 6
            description = block.action_description(action_index)
            return LogicPoint(block.pixel_x, block.pixel_y, f"MB{param}", "moving_block", param), f"activates moving block action {action_index}: {description}"
    if event_type == 5:
        return LogicPoint(0, 0, f"CP{param}", "checkpoint", param), "sets checkpoint"
    if event_type == 10:
        return LogicPoint(0, 0, f"G{param}", "guardian", param), "loads guardian"
    return None, None


def _source_event_points(graph: LogicGraph, event_index: int) -> tuple[LogicPoint, ...]:
    direct_points = graph.event_cell_points(event_index)
    if direct_points:
        return direct_points
    # Effect-triggered events may not own any map cell. Represent them as a logical point at (0,0);
    # the renderer will skip physically meaningless off-map lines but the inspector can still explain them.
    return (LogicPoint(0, 0, f"E{event_index}", "event_effect", event_index),)


def build_logic_graph(
    map_data: GodsMap,
    alfils_data: AlfilsData,
    object_table: ObjectTable | None = None,
    weapon_table: WeaponTable | None = None,
) -> LogicGraph:
    event_cells = _iter_event_cells(map_data)
    seed = LogicGraph(
        map_data=map_data,
        alfils_data=alfils_data,
        event_cells=event_cells,
        all_edges=(),
        object_table=object_table,
        weapon_table=weapon_table,
    )
    edges: list[LogicEdge] = []

    # Direct event targets.
    for event in alfils_data.stored_events:
        target, label = _event_target_point(seed, event)
        if target is None or label is None:
            continue
        for source in _source_event_points(seed, event.index):
            edges.append(LogicEdge(source, target, label, "event_target"))

    # Physical switch item -> PALFILS switch-state record. A full-data DOS cross-check shows
    # that used switch records match exactly one map object at the same (x,y) with the same
    # object-info index. Encoding this explicitly lets a click on the switch sprite expose the
    # same downstream puzzle conditions as a click on the switch record.
    for switch in alfils_data.active_switches:
        switch_point = seed.point_for_switch(switch.index)
        if switch_point is None:
            continue
        for item in map_data.active_items:
            if not item.is_object:
                continue
            if (
                item.pixel_x == switch.pixel_x
                and item.pixel_y == switch.pixel_y
                and item.object_or_weapon_info_index == switch.object_info_index
            ):
                edges.append(
                    LogicEdge(
                        _map_item_point(item, f"I{item.index}/SW", "switch_item"),
                        switch_point,
                        "binds physical switch item to switch-state record",
                        "switch_binding",
                    )
                )

    # Teleport stones are ordinary usable objects whose effect index is 17. PALFILS teleport
    # records match them by source X only (this follows the original viewer/source behavior).
    # If a record has no fixed map/spawn source, it stays visible in the entity browser but does
    # not get a speculative graph edge here.
    for teleport in alfils_data.active_teleports:
        target = LogicPoint(
            teleport.marker_x,
            teleport.marker_y + 24,
            f"T{teleport.index}",
            "teleport",
            teleport.index,
        )
        for source in _teleport_stone_source_points(seed, teleport.src_pixel_x):
            edges.append(
                LogicEdge(source, target, "teleport stone destination", "teleport_binding")
            )

    # Chest keys and chests are a game-specific object relationship, not a generic puzzle
    # condition. Kroah's viewer models it explicitly, and it is invaluable in an editor:
    # a chest may live in the map, be puzzle-spawned, or be rewarded by a wave; the matching
    # key can come from the same set of sources.
    if object_table is not None:
        chest_infos = tuple(info for info in object_table.records if info.is_chest)
        key_infos = tuple(info for info in object_table.records if info.is_chest_key)
        for key_info in key_infos:
            key_sources = _object_source_points(seed, key_info.index, fallback=False)
            if not key_sources:
                continue
            for chest_info in chest_infos:
                if not key_info.opens_chest_object_info(chest_info.index):
                    continue
                chest_sources = _object_source_points(seed, chest_info.index, fallback=False)
                for key_source in key_sources:
                    for chest_source in chest_sources:
                        edges.append(
                            LogicEdge(
                                key_source,
                                chest_source,
                                f"chest key OBJ{key_info.index} opens chest OBJ{chest_info.index}",
                                "chest_key_binding",
                            )
                        )

        # A Reveal Clues usable object reveals the hint record with the same X coordinate.
        # This mirrors World.GetHintAt(pixelX) in the older viewer.
        for info in object_table.records:
            if not info.is_reveal_clues:
                continue
            for source in _object_source_points(seed, info.index, fallback=False):
                hint_point = _hint_point_at_x(seed, source.pixel_x)
                if hint_point is None:
                    continue
                edges.append(
                    LogicEdge(source, hint_point, "reveals clue text at matching X", "hint_binding")
                )

    # Puzzle effects and conditions. These are where GODS starts to look like a graph rather than a list.
    for puzzle in map_data.active_puzzles:
        puzzle_point = seed.point_for_puzzle(puzzle.index)
        if puzzle_point is None:
            continue

        effect_type = puzzle.effect_function_index
        effect_param = puzzle.effect_param
        effect_name = puzzle_effect_name(effect_type)

        if effect_type == 5 and effect_param > 0:  # TriggerEvent stores event index + 1 in Kroah's viewer.
            target_event_index = effect_param - 1
            target_points = seed.event_cell_points(target_event_index)
            if target_points:
                for target in target_points:
                    edges.append(LogicEdge(puzzle_point, target, f"effect {effect_name}", "puzzle_effect"))
            else:
                edges.append(
                    LogicEdge(
                        puzzle_point,
                        LogicPoint(0, 0, f"E{target_event_index}", "event_effect", target_event_index),
                        f"effect {effect_name}",
                        "puzzle_effect",
                    )
                )
        elif effect_type in (7, 8) and 0 <= effect_param < len(alfils_data.trapdoors):
            record = alfils_data.trapdoors[effect_param]
            if record.appears_used:
                edges.append(
                    LogicEdge(
                        puzzle_point,
                        LogicPoint(record.pixel_x, record.pixel_y, f"D{effect_param}", "trapdoor", effect_param),
                        f"effect {effect_name}",
                        "puzzle_effect",
                    )
                )
        else:
            for target, label in _puzzle_effect_points(seed, puzzle):
                edges.append(
                    LogicEdge(
                        puzzle_point,
                        target,
                        f"effect {effect_name}: {label}",
                        "puzzle_effect",
                    )
                )
            extra_non_spatial = _non_spatial_effect_point(effect_type, effect_param)
            if extra_non_spatial is not None:
                target, label = extra_non_spatial
                edges.append(
                    LogicEdge(
                        puzzle_point,
                        target,
                        f"effect {effect_name}: {label}",
                        "puzzle_effect",
                    )
                )

        for cond_type, cond_param in zip(puzzle.condition_function_indices, puzzle.condition_params):
            cond_name = condition_type_name(cond_type)
            if cond_type in (5, 6) and cond_param > 0:  # EventTriggered / EventNotTriggered store event index + 1.
                source_event_index = cond_param - 1
                for source in _source_event_points(seed, source_event_index):
                    edges.append(
                        LogicEdge(
                            source,
                            puzzle_point,
                            f"condition {cond_name}",
                            "puzzle_condition",
                            positive_state=(cond_type == 5),
                        )
                    )
            elif cond_type in (11, 12):  # SwitchOn / SwitchOff use switch index directly.
                source = seed.point_for_switch(cond_param)
                if source is not None:
                    edges.append(
                        LogicEdge(
                            source,
                            puzzle_point,
                            f"condition {cond_name}",
                            "puzzle_condition",
                            positive_state=(cond_type == 11),
                        )
                    )
            elif cond_type in (1, 2):  # Carrying / NotCarrying object-info index.
                for source in _object_condition_sources(seed, cond_param):
                    edges.append(
                        LogicEdge(
                            source,
                            puzzle_point,
                            f"condition {cond_name}",
                            "puzzle_condition",
                            positive_state=(cond_type == 1),
                        )
                    )
            elif cond_type in (3, 4):  # Holding / NotHolding weapon-info index.
                for source in _weapon_condition_sources(seed, cond_param):
                    edges.append(
                        LogicEdge(
                            source,
                            puzzle_point,
                            f"condition {cond_name}",
                            "puzzle_condition",
                            positive_state=(cond_type == 3),
                        )
                    )
            else:
                state_source = _state_condition_point(puzzle, cond_type, cond_param)
                if state_source is not None:
                    edges.append(
                        LogicEdge(
                            state_source,
                            puzzle_point,
                            f"condition {cond_name}",
                            "puzzle_condition",
                            positive_state=True,
                        )
                    )

    return LogicGraph(
        map_data=map_data,
        alfils_data=alfils_data,
        event_cells=event_cells,
        all_edges=tuple(edges),
        object_table=object_table,
        weapon_table=weapon_table,
    )
