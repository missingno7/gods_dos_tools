from __future__ import annotations

from collections import Counter
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gods_tools.formats.alfils import load_packed_alfils
from gods_tools.formats.item_tables import load_packed_object_table, level_object_table_path
from gods_tools.formats.levels import discover_level_resources
from gods_tools.formats.logic import build_logic_graph, condition_type_name, puzzle_effect_name
from gods_tools.formats.diagnostics import build_level_diagnostics
from gods_tools.formats.pc_logic_tables import objective_locations, special_teleport_destinations
from gods_tools.formats.map import load_packed_map


def main() -> None:
    game_dir = ROOT / "game_data" / "Gods"
    conditions: Counter[str] = Counter()
    effects: Counter[str] = Counter()
    events: Counter[str] = Counter()
    moving_action_semantics: Counter[str] = Counter()
    moving_opaque_referenced = 0
    switch_exact_matches = 0
    switch_count = 0
    teleport_bound_records = 0
    teleport_unbound_records = 0
    teleport_records = 0
    special_teleport_destinations_count = 0
    objective_location_count = 0
    counted_pc_levels: set[int] = set()
    checkpoint_events = 0
    guardian_events = 0
    diagnostics_warning_count = 0
    diagnostics_info_count = 0
    diagnostic_codes: Counter[str] = Counter()

    for resource in discover_level_resources(game_dir):
        map_data = load_packed_map(resource.map_path)
        alfils = load_packed_alfils(resource.alfils_path)
        object_table = load_packed_object_table(level_object_table_path(game_dir, resource.level))
        graph = build_logic_graph(map_data, alfils, object_table, None)
        diagnostics = build_level_diagnostics(map_data, alfils, graph)
        diagnostics_warning_count += diagnostics.warning_count
        diagnostics_info_count += diagnostics.info_count
        for item in diagnostics.items:
            diagnostic_codes[item.code] += 1
        if resource.level not in counted_pc_levels:
            counted_pc_levels.add(resource.level)
            special_teleport_destinations_count += len(special_teleport_destinations(resource.level))
            objective_location_count += len(objective_locations(resource.level))

        for event in alfils.active_events:
            events[event.type_name] += 1
            if event.type_name == "Checkpoint":
                checkpoint_events += 1
            if event.type_name == "LoadGuardian":
                guardian_events += 1
            if event.event_type_index is not None and 6 <= event.event_type_index <= 9:
                block = alfils.moving_blocks[event.param]
                action_index = event.event_type_index - 6
                kind = block.action_kind(action_index)
                moving_action_semantics[kind] += 1
                if kind == "opaque_unreferenced_raw":
                    moving_opaque_referenced += 1

        for puzzle in map_data.active_puzzles:
            effects[puzzle_effect_name(puzzle.effect_function_index)] += 1
            for cond_type in puzzle.condition_function_indices:
                conditions[condition_type_name(cond_type)] += 1

        for switch in alfils.active_switches:
            switch_count += 1
            exact = [
                item
                for item in map_data.active_items
                if item.is_object
                and item.pixel_x == switch.pixel_x
                and item.pixel_y == switch.pixel_y
                and item.object_or_weapon_info_index == switch.object_info_index
            ]
            if len(exact) == 1:
                switch_exact_matches += 1

        for teleport in alfils.active_teleports:
            teleport_records += 1
            is_bound = any(
                edge.edge_kind == "teleport_binding" and edge.target.kind == "teleport" and edge.target.index == teleport.index
                for edge in graph.all_edges
            )
            if is_bound:
                teleport_bound_records += 1
            else:
                teleport_unbound_records += 1

    print("EVENT TYPES")
    for name, count in events.most_common():
        print(f"  {name:30s} {count}")

    print("\nPUZZLE CONDITIONS")
    for name, count in conditions.most_common():
        print(f"  {name:30s} {count}")

    print("\nPUZZLE EFFECTS")
    for name, count in effects.most_common():
        print(f"  {name:30s} {count}")

    print("\nCROSS-CHECKS")
    print(f"  switch records with exact physical map-item binding: {switch_exact_matches}/{switch_count}")
    print(f"  referenced moving-block action slots with opaque semantics: {moving_opaque_referenced}")
    print(f"  populated teleport table rows that resolve to a teleport-stone source: {teleport_bound_records}/{teleport_records}")
    print(f"  populated teleport table rows with no source in this world (likely stale rows): {teleport_unbound_records}")
    print(f"  hardcoded special teleport destinations extracted from DOS EXE: {special_teleport_destinations_count}")
    print(f"  objective locations extracted from DOS EXE: {objective_location_count}")
    print(f"  Checkpoint event records: {checkpoint_events}; LoadGuardian event records: {guardian_events}")
    print(f"  diagnostics findings: WARN={diagnostics_warning_count}, INFO={diagnostics_info_count}")

    print("\nDIAGNOSTIC FINDING CODES")
    for name, count in diagnostic_codes.most_common():
        print(f"  {name:45s} {count}")

    print("\nREFERENCED MOVING-BLOCK ACTION SEMANTICS")
    for name, count in moving_action_semantics.most_common():
        print(f"  {name:30s} {count}")


if __name__ == "__main__":
    main()
