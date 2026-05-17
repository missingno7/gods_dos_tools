from pathlib import Path

from gods_tools.formats.alfils import load_packed_alfils
from gods_tools.formats.levels import discover_level_resources
from gods_tools.formats.logic import build_logic_graph
from gods_tools.formats.item_tables import level_object_table_path, level_weapon_table_path, load_packed_object_table, load_packed_weapon_table
from gods_tools.formats.map import load_packed_map


GAME_DIR = Path(__file__).resolve().parents[1] / "game_data" / "Gods"


def test_logic_graph_decodes_relationships_for_level_1a() -> None:
    resource = discover_level_resources(GAME_DIR)[0]
    map_data = load_packed_map(resource.map_path)
    alfils = load_packed_alfils(resource.alfils_path)
    graph = build_logic_graph(map_data, alfils)

    assert graph.event_cells
    assert len(graph.all_edges) > 100
    assert graph.describe_event(0)
    assert graph.related_edges_for_event(0)


def test_logic_graph_exposes_spatial_puzzle_effect_targets() -> None:
    resource = discover_level_resources(GAME_DIR)[0]
    map_data = load_packed_map(resource.map_path)
    alfils = load_packed_alfils(resource.alfils_path)
    objects = load_packed_object_table(level_object_table_path(GAME_DIR, resource.level))
    weapons = load_packed_weapon_table(level_weapon_table_path(GAME_DIR, resource.level))
    graph = build_logic_graph(map_data, alfils, objects, weapons)

    target_kinds = {edge.target.kind for edge in graph.all_edges}
    assert "spawned_object" in target_kinds
    assert "door" in target_kinds
    assert "destructable_object" in target_kinds


def test_logic_graph_marks_offmap_destroy_type4_and_supports_reverse_pick() -> None:
    resource = next(resource for resource in discover_level_resources(GAME_DIR) if resource.key == "3A")
    map_data = load_packed_map(resource.map_path)
    alfils = load_packed_alfils(resource.alfils_path)
    objects = load_packed_object_table(level_object_table_path(GAME_DIR, resource.level))
    weapons = load_packed_weapon_table(level_weapon_table_path(GAME_DIR, resource.level))
    graph = build_logic_graph(map_data, alfils, objects, weapons)

    offmap = [edge.target for edge in graph.all_edges if edge.target.kind == "destroy_type4_offmap"]
    assert len(offmap) == 1
    assert offmap[0].label == "TYPE4∅27"

    level_1a = discover_level_resources(GAME_DIR)[0]
    map_1a = load_packed_map(level_1a.map_path)
    alfils_1a = load_packed_alfils(level_1a.alfils_path)
    objects_1a = load_packed_object_table(level_object_table_path(GAME_DIR, level_1a.level))
    weapons_1a = load_packed_weapon_table(level_weapon_table_path(GAME_DIR, level_1a.level))
    graph_1a = build_logic_graph(map_1a, alfils_1a, objects_1a, weapons_1a)

    physical = next(edge.target for edge in graph_1a.all_edges if edge.target.kind == "destructable_object")
    picked = graph_1a.pick_point(physical.pixel_x, physical.pixel_y)
    assert picked is not None
    assert picked.kind == "destructable_object"
    assert graph_1a.describe_point(picked)
    assert graph_1a.related_edges_for_point(picked)


def test_logic_graph_includes_inventory_conditions_switch_bindings_and_teleport_links() -> None:
    resource = discover_level_resources(GAME_DIR)[0]
    map_data = load_packed_map(resource.map_path)
    alfils = load_packed_alfils(resource.alfils_path)
    objects = load_packed_object_table(level_object_table_path(GAME_DIR, resource.level))
    weapons = load_packed_weapon_table(level_weapon_table_path(GAME_DIR, resource.level))
    graph = build_logic_graph(map_data, alfils, objects, weapons)

    edge_kinds = {edge.edge_kind for edge in graph.all_edges}
    assert "switch_binding" in edge_kinds
    assert "teleport_binding" in edge_kinds

    condition_sources = {edge.source.kind for edge in graph.all_edges if edge.edge_kind == "puzzle_condition"}
    assert "map_object_source" in condition_sources or "spawned_object_source" in condition_sources
    assert "health_condition" in condition_sources or "time_condition" in condition_sources


def test_referenced_moving_block_actions_have_known_semantics() -> None:
    valid_kinds = {
        "cycle_forward",
        "cycle_backward",
        "move_to_target_then_stop",
        "disable",
        "never_used",
    }
    for resource in discover_level_resources(GAME_DIR):
        alfils = load_packed_alfils(resource.alfils_path)
        for event in alfils.active_events:
            if event.event_type_index is None or not (6 <= event.event_type_index <= 9):
                continue
            block = alfils.moving_blocks[event.param]
            action_index = event.event_type_index - 6
            assert block.action_kind(action_index) in valid_kinds


def test_logic_graph_exposes_map_item_role_bundle_for_object_inspector() -> None:
    resource = discover_level_resources(GAME_DIR)[0]
    map_data = load_packed_map(resource.map_path)
    alfils = load_packed_alfils(resource.alfils_path)
    objects = load_packed_object_table(level_object_table_path(GAME_DIR, resource.level))
    weapons = load_packed_weapon_table(level_weapon_table_path(GAME_DIR, resource.level))
    graph = build_logic_graph(map_data, alfils, objects, weapons)

    switch_edge = next(edge for edge in graph.all_edges if edge.edge_kind == "switch_binding")
    assert switch_edge.source.index is not None
    item_index = switch_edge.source.index
    points = graph.points_for_map_item(item_index)
    assert points
    assert any(point.kind == "switch_item" for point in points)
    assert graph.preferred_point_for_map_item(item_index) is not None
    assert graph.direct_edges_for_map_item(item_index)
    assert graph.related_edges_for_map_item(item_index)
