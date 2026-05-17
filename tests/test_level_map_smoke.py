from pathlib import Path

from gods_tools.formats.levels import discover_level_resources
from gods_tools.formats.map import load_packed_map
from gods_tools.render.levels import render_level_map


def test_level_map_unpack_parse_and_render() -> None:
    resources = discover_level_resources(Path("game_data/Gods"))
    assert len(resources) == 8

    resource = resources[0]
    map_data = load_packed_map(resource.map_path)
    rendered = render_level_map(map_data, resource)

    assert map_data.unpacked_size == 21868
    assert map_data.layer_a_max_tile == 182
    assert len(map_data.items) == 200
    assert len(map_data.puzzles) == 100
    assert rendered.loaded_tile_count == 240
    assert rendered.missing_tile_ids == ()
    assert rendered.image.size == (4096, 1024)
