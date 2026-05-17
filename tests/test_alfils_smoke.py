from pathlib import Path

from gods_tools.formats.alfils import ALFILS_EXPECTED_SIZE, load_packed_alfils
from gods_tools.formats.levels import discover_level_resources
from gods_tools.formats.map import load_packed_map
from gods_tools.render.levels import LevelRenderOptions, render_level_map


def test_alfils_unpack_parse_and_logic_overlay_render() -> None:
    resources = discover_level_resources(Path("game_data/Gods"))
    resource = resources[0]
    assert resource.alfils_path is not None

    alfils = load_packed_alfils(resource.alfils_path)
    assert alfils.unpacked_size == ALFILS_EXPECTED_SIZE
    assert len(alfils.events) == 253
    assert len(alfils.switches) == 64
    assert len(alfils.teleports) == 30
    assert len(alfils.trapdoors) == 20
    assert len(alfils.moving_blocks) == 25
    assert len(alfils.trailing_zero_bytes) == 80

    map_data = load_packed_map(resource.map_path)
    rendered = render_level_map(
        map_data,
        resource,
        LevelRenderOptions(
            show_event_overlay=True,
            show_enemy_wave_markers=True,
            show_switch_markers=True,
            show_teleport_markers=True,
            show_trapdoor_markers=True,
            show_moving_block_markers=True,
            show_hint_markers=True,
        ),
        alfils,
    )
    assert rendered.image.size == (4096, 1024)
