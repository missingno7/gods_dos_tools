from __future__ import annotations

from pathlib import Path
import argparse
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gods_tools.formats.alfils import load_packed_alfils
from gods_tools.formats.levels import discover_level_resources
from gods_tools.formats.map import load_packed_map
from gods_tools.formats.flying_paths import load_packed_flying_paths
from gods_tools.formats.item_tables import level_object_table_path, level_weapon_table_path, load_packed_object_table, load_packed_weapon_table
from gods_tools.render.sprites import load_level_sprite_bank
from gods_tools.render.levels import LevelRenderOptions, render_level_map


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export rendered DOS GODS level maps as PNG.")
    parser.add_argument(
        "--game-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "game_data" / "Gods",
        help="Directory containing packed DOS GODS files.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "exports" / "levels",
        help="PNG export directory.",
    )
    parser.add_argument("--collision", action="store_true", help="Show layer B wall/stair overlay.")
    parser.add_argument("--events", action="store_true", help="Show layer B event cell overlay.")
    parser.add_argument("--no-item-sprites", action="store_true", help="Hide rendered map item sprites.")
    parser.add_argument("--items", action="store_true", help="Show map item ID markers.")
    parser.add_argument("--puzzles", action="store_true", help="Show puzzle markers.")
    parser.add_argument("--waves", action="store_true", help="Show walking/intelligent wave spawn markers.")
    parser.add_argument("--flying-paths", action="store_true", help="Show decoded .PAT flight polylines for map-triggered flying waves.")
    parser.add_argument("--wave-rewards", action="store_true", help="Show semantic reward previews for enemy waves.")
    parser.add_argument("--hidden-spawned", action="store_true", help="Show ghost previews for puzzle-spawned objects and weapons.")
    parser.add_argument("--switches", action="store_true", help="Show PALFILS switch markers.")
    parser.add_argument("--teleports", action="store_true", help="Show PALFILS teleport table targets.")
    parser.add_argument("--hardcoded-teleports", action="store_true", help="Show special teleport destinations extracted from the DOS executable.")
    parser.add_argument("--objective-locations", action="store_true", help="Show intelligent-enemy objective locations extracted from the DOS executable.")
    parser.add_argument("--player-start", action="store_true", help="Show the viewer-derived player start marker.")
    parser.add_argument("--trapdoors", action="store_true", help="Show PALFILS trapdoors.")
    parser.add_argument("--moving-blocks", action="store_true", help="Show PALFILS moving block overlays.")
    parser.add_argument("--moving-block-preview", action="store_true", help="Show selected moving-block action routes when the selection is available.")
    parser.add_argument("--hints", action="store_true", help="Show hint X-lines.")
    parser.add_argument("--grid", action="store_true", help="Show tile grid.")
    parser.add_argument("--raster", action="store_true", help="Show experimental raster background.")
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    options = LevelRenderOptions(
        show_raster_background=args.raster,
        show_collision_overlay=args.collision,
        show_event_overlay=args.events,
        show_item_sprites=not args.no_item_sprites,
        show_item_markers=args.items,
        show_puzzle_markers=args.puzzles,
        show_enemy_wave_markers=args.waves,
        show_flying_wave_paths=args.flying_paths,
        show_wave_reward_previews=args.wave_rewards,
        show_hidden_spawned_items=args.hidden_spawned,
        show_switch_markers=args.switches,
        show_teleport_markers=args.teleports,
        show_special_teleport_markers=args.hardcoded_teleports,
        show_objective_location_markers=args.objective_locations,
        show_player_start_marker=args.player_start,
        show_trapdoor_markers=args.trapdoors,
        show_moving_block_markers=args.moving_blocks,
        show_moving_block_action_preview=args.moving_block_preview,
        show_hint_markers=args.hints,
        show_grid=args.grid,
    )

    for resource in discover_level_resources(args.game_dir):
        map_data = load_packed_map(resource.map_path)
        alfils_data = load_packed_alfils(resource.alfils_path) if resource.alfils_path is not None else None
        object_path = level_object_table_path(args.game_dir, resource.level)
        weapon_path = level_weapon_table_path(args.game_dir, resource.level)
        object_table = load_packed_object_table(object_path) if object_path.exists() else None
        weapon_table = load_packed_weapon_table(weapon_path) if weapon_path.exists() else None
        sprite_bank = load_level_sprite_bank(args.game_dir, resource.level, resource.world)
        flying_paths = load_packed_flying_paths(resource.flying_paths_path) if resource.flying_paths_path is not None else None
        rendered = render_level_map(map_data, resource, options, alfils_data, object_table, weapon_table, sprite_bank, flying_paths=flying_paths)
        target = args.output_dir / f"level_{resource.key}.png"
        rendered.image.save(target)
        print(
            f"{resource.key}: {target.name} | "
            f"tiles={rendered.loaded_tile_count} missing={list(rendered.missing_tile_ids)}"
        )


if __name__ == "__main__":
    main()
