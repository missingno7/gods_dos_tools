from pathlib import Path

from gods_tools.formats.alfils import load_packed_alfils
from gods_tools.formats.diagnostics import build_level_diagnostics
from gods_tools.formats.item_tables import (
    level_object_table_path,
    level_weapon_table_path,
    load_packed_object_table,
    load_packed_weapon_table,
)
from gods_tools.formats.levels import discover_level_resources
from gods_tools.formats.logic import LogicPoint, build_logic_graph
from gods_tools.formats.map import load_packed_map
from gods_tools.formats.pc_logic_tables import player_start_location
from gods_tools.render.levels import LevelRenderOptions, render_level_map
from gods_tools.render.sprites import load_level_sprite_bank

GAME_DIR = Path("game_data/Gods")


def _level_1a():
    resource = next(resource for resource in discover_level_resources(GAME_DIR) if resource.key == "1A")
    map_data = load_packed_map(resource.map_path)
    alfils = load_packed_alfils(resource.alfils_path)
    objects = load_packed_object_table(level_object_table_path(GAME_DIR, resource.level))
    weapons = load_packed_weapon_table(level_weapon_table_path(GAME_DIR, resource.level))
    graph = build_logic_graph(map_data, alfils, objects, weapons)
    return resource, map_data, alfils, objects, weapons, graph


def test_logic_graph_adds_chest_key_and_hint_bindings() -> None:
    _resource, _map_data, _alfils, _objects, _weapons, graph = _level_1a()
    kinds = [edge.edge_kind for edge in graph.all_edges]
    assert "chest_key_binding" in kinds
    assert "hint_binding" in kinds


def test_player_start_table_has_level_1_marker() -> None:
    start = player_start_location(1)
    assert start is not None
    assert (start.pixel_x, start.pixel_y) == (64, 944)


def test_diagnostics_report_is_emitted_without_warnings_for_level_1a() -> None:
    _resource, map_data, alfils, _objects, _weapons, graph = _level_1a()
    diagnostics = build_level_diagnostics(map_data, alfils, graph)
    assert diagnostics.warning_count == 0
    rendered = diagnostics.render_text()
    assert "Level diagnostics" in rendered
    assert "Chest-key links" in rendered


def test_hidden_spawned_and_player_start_overlays_render() -> None:
    resource, map_data, alfils, objects, weapons, _graph = _level_1a()
    sprite_bank = load_level_sprite_bank(GAME_DIR, resource.level, resource.world)
    result = render_level_map(
        map_data,
        resource,
        LevelRenderOptions(show_hidden_spawned_items=True, show_player_start_marker=True),
        alfils,
        objects,
        weapons,
        sprite_bank,
    )
    assert result.image.size == (4096, 1024)
    assert result.canvas_overlay is not None
    assert result.canvas_overlay.rectangles
    labels = [marker.label for marker in result.canvas_overlay.markers if marker.label]
    assert any("->OBJ" in label or "->WPN" in label for label in labels)


def test_moving_block_preview_accepts_selected_moving_block() -> None:
    resource, map_data, alfils, objects, weapons, _graph = _level_1a()
    sprite_bank = load_level_sprite_bank(GAME_DIR, resource.level, resource.world)
    first = alfils.active_moving_blocks[0]
    result = render_level_map(
        map_data,
        resource,
        LevelRenderOptions(
            show_moving_block_markers=True,
            show_moving_block_action_preview=True,
            selected_logic_point=LogicPoint(first.pixel_x, first.pixel_y, f"MB{first.index}", "moving_block", first.index),
        ),
        alfils,
        objects,
        weapons,
        sprite_bank,
    )
    assert result.image.size == (4096, 1024)
