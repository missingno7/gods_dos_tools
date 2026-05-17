from pathlib import Path

from gods_tools.formats.alfils import load_packed_alfils
from gods_tools.formats.item_tables import (
    level_object_table_path,
    level_weapon_table_path,
    load_packed_object_table,
    load_packed_weapon_table,
)
from gods_tools.formats.levels import discover_level_resources
from gods_tools.formats.logic import build_logic_graph
from gods_tools.formats.map import load_packed_map
from gods_tools.formats.mechanisms import (
    describe_event_mechanism,
    describe_map_item_mechanism,
    describe_point_mechanism,
)

GAME_DIR = Path(__file__).resolve().parents[1] / "game_data" / "Gods"


def _graph_1a():
    resource = discover_level_resources(GAME_DIR)[0]
    map_data = load_packed_map(resource.map_path)
    alfils = load_packed_alfils(resource.alfils_path)
    objects = load_packed_object_table(level_object_table_path(GAME_DIR, resource.level))
    weapons = load_packed_weapon_table(level_weapon_table_path(GAME_DIR, resource.level))
    return build_logic_graph(map_data, alfils, objects, weapons)


def test_mechanism_narrative_for_event_mentions_story_sections() -> None:
    graph = _graph_1a()
    narrative = describe_event_mechanism(graph, 0, recursive=True).text
    assert "Mechanism driven by event E0" in narrative
    assert "At a glance" in narrative
    assert "Entry points" in narrative


def test_mechanism_narrative_for_map_item_tracks_switch_story() -> None:
    graph = _graph_1a()
    switch_edge = next(edge for edge in graph.all_edges if edge.edge_kind == "switch_binding")
    assert switch_edge.source.index is not None
    narrative = describe_map_item_mechanism(graph, switch_edge.source.index, recursive=True).text
    assert "Mechanism around map item" in narrative
    assert "Physical bindings" in narrative


def test_mechanism_narrative_for_logic_point_handles_physical_target() -> None:
    graph = _graph_1a()
    physical = next(edge.target for edge in graph.all_edges if edge.target.kind == "destructable_object")
    narrative = describe_point_mechanism(graph, physical, recursive=True).text
    assert "Mechanism around" in narrative
    assert "Puzzle stories" in narrative or "At a glance" in narrative
