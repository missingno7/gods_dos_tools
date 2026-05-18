from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw

from gods_tools.formats.alfils import AlfilsData
from gods_tools.formats.logic import LogicGraph, LogicPoint, build_logic_graph
from gods_tools.formats.flying_paths import FlyingPathsData
from gods_tools.formats.item_tables import ObjectTable, WeaponTable
from gods_tools.formats.enemy_info import EnemyInfo, get_enemy_info
from gods_tools.formats.pc_logic_tables import objective_locations, special_teleport_destinations, player_start_location
from gods_tools.render.sprites import SpriteBank
from gods_tools.formats.levels import LevelResource
from gods_tools.formats.map import (
    GodsMap,
    MAP_CELL_HEIGHT,
    MAP_CELL_WIDTH,
    MAP_HEIGHT_CELLS,
    MAP_WIDTH_CELLS,
)
from gods_tools.formats.pi1 import Pi1Image, load_packed_pi1
from gods_tools.render.images import render_pi1


@dataclass(frozen=True)
class LevelRenderOptions:
    show_raster_background: bool = False
    show_collision_overlay: bool = False
    show_event_overlay: bool = False
    show_item_sprites: bool = True
    show_item_markers: bool = False
    show_puzzle_markers: bool = False
    show_enemy_wave_markers: bool = False
    show_enemy_sprites: bool = False
    show_flying_wave_paths: bool = False
    show_wave_reward_previews: bool = False
    show_hidden_spawned_items: bool = False
    show_switch_markers: bool = False
    show_teleport_markers: bool = False
    show_special_teleport_markers: bool = False
    show_objective_location_markers: bool = False
    show_player_start_marker: bool = False
    show_trapdoor_markers: bool = False
    show_moving_block_markers: bool = False
    show_moving_block_action_preview: bool = False
    show_hint_markers: bool = False
    show_logic_links: bool = False
    recursive_logic_links: bool = True
    logic_link_scope: str = "selected"
    selected_event_index: int | None = None
    selected_flying_path_index: int | None = None
    selected_logic_point: LogicPoint | None = None
    show_grid: bool = False


@dataclass(frozen=True)
class OverlayLine:
    start_x: int
    start_y: int
    end_x: int
    end_y: int
    color: tuple[int, int, int, int]
    width: int = 2
    dashed: bool = False


@dataclass(frozen=True)
class OverlayRect:
    x0: int
    y0: int
    x1: int
    y1: int
    color: tuple[int, int, int, int]
    width: int = 1
    label: str | None = None


@dataclass(frozen=True)
class OverlayMarker:
    x: int
    y: int
    label: str | None
    color: tuple[int, int, int, int]
    shape: str = "ring"


@dataclass(frozen=True)
class CanvasOverlay:
    lines: tuple[OverlayLine, ...] = ()
    markers: tuple[OverlayMarker, ...] = ()
    rectangles: tuple[OverlayRect, ...] = ()


@dataclass(frozen=True)
class LevelRenderResult:
    image: Image.Image
    loaded_tile_count: int
    missing_tile_ids: tuple[int, ...]
    extra_bank_used: Path | None
    canvas_overlay: CanvasOverlay | None = None


def _merge_canvas_overlays(*overlays: CanvasOverlay | None) -> CanvasOverlay | None:
    lines = []
    markers = []
    rectangles = []
    for overlay in overlays:
        if overlay is None:
            continue
        lines.extend(overlay.lines)
        markers.extend(overlay.markers)
        rectangles.extend(overlay.rectangles)
    if not lines and not markers and not rectangles:
        return None
    return CanvasOverlay(lines=tuple(lines), markers=tuple(markers), rectangles=tuple(rectangles))


def _palette_word_to_rgb(word: int) -> tuple[int, int, int]:
    # The map raster palette uses the same 0x?RGB style channel packing as PI1 resources.
    r = ((word >> 8) & 0x7) * 255 // 7
    g = ((word >> 4) & 0x7) * 255 // 7
    b = (word & 0x7) * 255 // 7
    return (r, g, b)


def _build_background(map_data: GodsMap, options: LevelRenderOptions) -> Image.Image:
    width = MAP_WIDTH_CELLS * MAP_CELL_WIDTH
    height = MAP_HEIGHT_CELLS * MAP_CELL_HEIGHT
    if not options.show_raster_background or not map_data.raster.palette_words:
        return Image.new("RGBA", (width, height), (0, 0, 0, 255))

    final_color = _palette_word_to_rgb(map_data.raster.palette_words[-1])
    image = Image.new("RGBA", (width, height), (*final_color, 255))
    draw = ImageDraw.Draw(image)

    # Kroah's viewer uses 20 px tall vertical raster bands. Keep this as a viewer option,
    # while the default remains the cleaner black background.
    band_height = 20
    words = map_data.raster.palette_words
    for index in range(max(0, len(words) - 1)):
        color1 = _palette_word_to_rgb(words[index])
        color2 = _palette_word_to_rgb(words[index + 1])
        y0 = index * band_height
        if y0 >= height:
            break
        for dy in range(band_height):
            y = y0 + dy
            if y >= height:
                break
            t = dy / max(1, band_height - 1)
            color = tuple(round(color1[c] * (1.0 - t) + color2[c] * t) for c in range(3))
            draw.line((0, y, width, y), fill=(*color, 255))
    return image


def _crop_tile_bank(pi1: Pi1Image) -> list[Image.Image]:
    sheet = render_pi1(pi1).convert("RGBA")
    tiles: list[Image.Image] = []
    for index in range(120):
        x = (index % 10) * MAP_CELL_WIDTH
        y = (index // 10) * MAP_CELL_HEIGHT
        tiles.append(sheet.crop((x, y, x + MAP_CELL_WIDTH, y + MAP_CELL_HEIGHT)))
    return tiles


def load_level_tile_bank(resource: LevelResource) -> list[Image.Image]:
    tiles = _crop_tile_bank(load_packed_pi1(resource.bits_path))
    if resource.extra_path is not None:
        tiles.extend(_crop_tile_bank(load_packed_pi1(resource.extra_path)))
    return tiles


def _label(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    text: str,
    fill: tuple[int, int, int, int],
) -> None:
    draw.text(
        (x, y),
        text,
        fill=fill,
        stroke_width=1,
        stroke_fill=(0, 0, 0, 255),
    )


def _rectangle_label(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    label: str,
    color: tuple[int, int, int, int],
    label_dx: int = 2,
    label_dy: int = 2,
) -> None:
    draw.rectangle(box, outline=color, width=2)
    _label(draw, box[0] + label_dx, box[1] + label_dy, label, color)


def _draw_event_overlay(
    image: Image.Image,
    map_data: GodsMap,
    alfils_data: AlfilsData | None,
) -> None:
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for y in range(MAP_HEIGHT_CELLS):
        for x in range(MAP_WIDTH_CELLS):
            value = map_data.layer_b_at(x, y)
            if value < 3:
                continue
            event_index = value - 3
            px = x * MAP_CELL_WIDTH
            py = y * MAP_CELL_HEIGHT
            box = (px, py, px + MAP_CELL_WIDTH - 1, py + MAP_CELL_HEIGHT - 1)
            draw.rectangle(box, outline=(255, 230, 0, 210), width=1)
            if alfils_data is None:
                label = str(event_index)
            else:
                event = alfils_data.event(event_index)
                label = f"{event_index}" if event is None else f"{event.acronym}{event_index}"
            _label(draw, px + 2, py + 2, label, (255, 230, 0, 255))
    image.alpha_composite(overlay)


def _draw_collision_overlay(image: Image.Image, map_data: GodsMap) -> None:
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for y in range(MAP_HEIGHT_CELLS):
        for x in range(MAP_WIDTH_CELLS):
            value = map_data.layer_b_at(x, y)
            px = x * MAP_CELL_WIDTH
            py = y * MAP_CELL_HEIGHT
            box = (px, py, px + MAP_CELL_WIDTH - 1, py + MAP_CELL_HEIGHT - 1)
            if value == 1:
                draw.rectangle(box, fill=(255, 255, 255, 96))
            elif value == 2:
                draw.rectangle(box, fill=(255, 160, 0, 112))
    image.alpha_composite(overlay)


def _draw_map_item_sprites(image: Image.Image, map_data: GodsMap, sprite_bank: SpriteBank | None) -> None:
    if sprite_bank is None:
        return
    for item in map_data.active_items:
        if item.is_weapon:
            sprite = sprite_bank.weapon_sprite(item.object_or_weapon_info_index - 192)
        else:
            sprite = sprite_bank.object_sprite(item.object_or_weapon_info_index)
        if sprite is None:
            continue
        image.alpha_composite(sprite, (item.pixel_x, item.pixel_y))


def _ghost_sprite(sprite: Image.Image, max_alpha: int = 128) -> Image.Image:
    ghost = sprite.copy().convert("RGBA")
    alpha = ghost.getchannel("A").point(lambda value: min(value, max_alpha))
    ghost.putalpha(alpha)
    return ghost


def _hidden_spawned_item_entries(
    map_data: GodsMap,
    sprite_bank: SpriteBank | None,
) -> tuple[tuple[int, int, Image.Image, str], ...]:
    if sprite_bank is None:
        return ()

    entries: list[tuple[int, int, Image.Image, str]] = []
    for puzzle in map_data.active_puzzles:
        sprite: Image.Image | None = None
        label = ""
        if puzzle.effect_function_index == 0:  # SpawnObject
            sprite = sprite_bank.object_sprite(puzzle.effect_param)
            label = f"P{puzzle.index}->OBJ{puzzle.effect_param}"
        elif puzzle.effect_function_index == 1:  # SpawnWeapon
            sprite = sprite_bank.weapon_sprite(puzzle.effect_param)
            label = f"P{puzzle.index}->WPN{puzzle.effect_param}"
        if sprite is not None:
            entries.append((puzzle.pixel_x, puzzle.pixel_y, sprite, label))
    return tuple(entries)


def _draw_hidden_spawned_item_sprites(
    image: Image.Image,
    map_data: GodsMap,
    sprite_bank: SpriteBank | None,
) -> None:
    """Render ghost sprite previews for SpawnObject / SpawnWeapon puzzle effects."""

    for x, y, sprite, _label_text in _hidden_spawned_item_entries(map_data, sprite_bank):
        ghost = _ghost_sprite(sprite)
        image.alpha_composite(ghost, (x, y))


def _draw_map_items(image: Image.Image, map_data: GodsMap) -> None:
    draw = ImageDraw.Draw(image)
    for item in map_data.active_items:
        x = item.pixel_x
        y = item.pixel_y
        draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill=(0, 220, 255, 255), outline=(0, 0, 0, 255))
        _label(draw, x + 6, y - 5, f"I{item.index}", (0, 220, 255, 255))


def _draw_puzzles(image: Image.Image, map_data: GodsMap) -> None:
    draw = ImageDraw.Draw(image)
    for puzzle in map_data.active_puzzles:
        x = puzzle.pixel_x
        y = puzzle.pixel_y
        if x == 0 and y == 0:
            continue
        draw.rectangle((x - 4, y - 4, x + 4, y + 4), fill=(255, 80, 220, 255), outline=(0, 0, 0, 255))
        _label(draw, x + 6, y - 5, f"P{puzzle.index}", (255, 80, 220, 255))


def _draw_enemy_waves(image: Image.Image, alfils_data: AlfilsData) -> None:
    draw = ImageDraw.Draw(image)
    for wave in alfils_data.active_walking_waves:
        x, y = wave.pixel_x, wave.pixel_y
        draw.ellipse((x - 5, y - 5, x + 5, y + 5), outline=(255, 100, 100, 255), width=2)
        _label(draw, x + 7, y - 6, f"WW{wave.index}", (255, 100, 100, 255))
    for wave in alfils_data.active_intel_walking_waves:
        x, y = wave.pixel_x, wave.pixel_y
        draw.rectangle((x - 5, y - 5, x + 5, y + 5), outline=(255, 160, 80, 255), width=2)
        _label(draw, x + 7, y - 6, f"IW{wave.index}", (255, 160, 80, 255))
    for wave in alfils_data.active_intel_flying_waves:
        x, y = wave.pixel_x, wave.pixel_y
        draw.polygon(((x, y - 6), (x + 6, y + 6), (x - 6, y + 6)), outline=(255, 80, 80, 255))
        _label(draw, x + 7, y - 6, f"IF{wave.index}", (255, 80, 80, 255))



def _enemy_info_for_wave(level: int, kind: str, wave) -> EnemyInfo | None:
    return get_enemy_info(level, kind, wave.enemy_info_index)


def _enemy_sprite(sprite_bank: SpriteBank | None, info: EnemyInfo | None, facing: int = 0) -> Image.Image | None:
    if sprite_bank is None or info is None:
        return None
    return sprite_bank.sprite(info.sprite_index_for_facing(facing))


def _draw_enemy_sprite_at(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    sprite: Image.Image | None,
    x: int,
    y: int,
    label: str,
    color: tuple[int, int, int, int],
    info: EnemyInfo | None,
) -> tuple[int, int]:
    if sprite is not None:
        image.alpha_composite(sprite, (x, y))
        draw.rectangle((x, y, x + sprite.width - 1, y + sprite.height - 1), outline=color, width=1)
        return sprite.width, sprite.height
    width = info.width if info is not None else 24
    height = info.height if info is not None else 24
    draw.rectangle((x, y, x + width - 1, y + height - 1), outline=color, width=1)
    return width, height


def _draw_enemy_sprites(
    image: Image.Image,
    map_data: GodsMap,
    alfils_data: AlfilsData,
    sprite_bank: SpriteBank | None,
    flying_paths: FlyingPathsData | None,
    level: int,
    selected_event_index: int | None = None,
    selected_flying_path_index: int | None = None,
) -> None:
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    for prefix, kind, waves, color in (
        ("WW", "walking", alfils_data.active_walking_waves, (255, 120, 120, 245)),
        ("IW", "walking", alfils_data.active_intel_walking_waves, (255, 170, 90, 245)),
        ("IF", "flying", alfils_data.active_intel_flying_waves, (255, 100, 100, 245)),
    ):
        for wave in waves:
            info = _enemy_info_for_wave(level, kind, wave)
            sprite = _enemy_sprite(sprite_bank, info, getattr(wave, "facing", 0))
            _draw_enemy_sprite_at(overlay, draw, sprite, wave.pixel_x, wave.pixel_y, f"{prefix}{wave.index}", color, info)

    if flying_paths is not None:
        for y in range(MAP_HEIGHT_CELLS):
            for x in range(MAP_WIDTH_CELLS):
                value = map_data.layer_b_at(x, y)
                if value < 3:
                    continue
                event_index = value - 3
                if selected_event_index is not None and event_index != selected_event_index:
                    continue
                event = alfils_data.event(event_index)
                if event is None or event.event_type_index != 0:
                    continue
                wave_index = event.param
                if not (0 <= wave_index < len(alfils_data.flying_waves)):
                    continue
                wave = alfils_data.flying_waves[wave_index]
                if selected_flying_path_index is not None and wave.flying_path_index != selected_flying_path_index:
                    continue
                path = flying_paths.get(wave.flying_path_index)
                if path is None:
                    continue
                center_x = x * MAP_CELL_WIDTH + MAP_CELL_WIDTH // 2
                center_y = y * MAP_CELL_HEIGHT + MAP_CELL_HEIGHT // 2
                points = path.points_for_event_center(center_x, center_y)
                if not points:
                    continue
                info = _enemy_info_for_wave(level, "flying", wave)
                sprite = _enemy_sprite(sprite_bank, info, 0)
                _draw_enemy_sprite_at(overlay, draw, sprite, points[0][0], points[0][1], f"FW{wave.index}/E{event_index}", (120, 255, 200, 245), info)

    image.alpha_composite(overlay)

def _draw_flying_wave_paths(
    image: Image.Image,
    map_data: GodsMap,
    alfils_data: AlfilsData,
    flying_paths: FlyingPathsData | None,
    selected_event_index: int | None = None,
    selected_flying_path_index: int | None = None,
) -> None:
    """Draw actual .PAT flight paths for map cells that spawn flying waves.

    Relative GODS paths only become spatial after a trigger cell is known. Absolute
    paths ignore the trigger cell, but keeping the same loop makes all event anchors
    visible and keeps duplicate map triggers explicit.
    """

    if flying_paths is None:
        return
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for y in range(MAP_HEIGHT_CELLS):
        for x in range(MAP_WIDTH_CELLS):
            value = map_data.layer_b_at(x, y)
            if value < 3:
                continue
            event_index = value - 3
            if selected_event_index is not None and event_index != selected_event_index:
                continue
            event = alfils_data.event(event_index)
            if event is None or event.event_type_index != 0:
                continue
            wave_index = event.param
            if not (0 <= wave_index < len(alfils_data.flying_waves)):
                continue
            wave = alfils_data.flying_waves[wave_index]
            if selected_flying_path_index is not None and wave.flying_path_index != selected_flying_path_index:
                continue
            path = flying_paths.get(wave.flying_path_index)
            if path is None:
                continue
            center_x = x * MAP_CELL_WIDTH + MAP_CELL_WIDTH // 2
            center_y = y * MAP_CELL_HEIGHT + MAP_CELL_HEIGHT // 2
            points = path.points_for_event_center(center_x, center_y)
            if len(points) < 2:
                continue
            color = (80, 255, 180, 245) if path.is_absolute else (255, 180, 80, 245)
            shadow = (0, 0, 0, 210)
            draw.line(points, fill=shadow, width=4)
            draw.line(points, fill=color, width=2)
            first_x, first_y = points[0]
            last_x, last_y = points[-1]
            draw.ellipse((first_x - 4, first_y - 4, first_x + 4, first_y + 4), outline=color, width=2)
            draw.rectangle((last_x - 3, last_y - 3, last_x + 3, last_y + 3), outline=color, width=2)
            _label(draw, first_x + 7, first_y - 7, f"FW{wave_index}/FP{path.index}", color)
    image.alpha_composite(overlay)



def _reward_sprite(sprite_bank: SpriteBank | None, wave) -> Image.Image | None:
    if sprite_bank is None or not wave.has_reward or wave.reward_info_index is None:
        return None
    if wave.reward_kind == "weapon":
        return sprite_bank.weapon_sprite(wave.reward_info_index)
    if wave.reward_kind == "object":
        return sprite_bank.object_sprite(wave.reward_info_index)
    return None


def _draw_wave_reward_previews(
    image: Image.Image,
    map_data: GodsMap,
    alfils_data: AlfilsData,
    sprite_bank: SpriteBank | None,
    flying_paths: FlyingPathsData | None,
    level: int,
    selected_event_index: int | None = None,
    selected_flying_path_index: int | None = None,
) -> None:
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # Static-position waves can show their reward near the decoded spawn point.
    for prefix, waves in (
        ("WW", alfils_data.active_walking_waves),
        ("IW", alfils_data.active_intel_walking_waves),
        ("IF", alfils_data.active_intel_flying_waves),
    ):
        for wave in waves:
            if not wave.has_reward:
                continue
            sprite = _reward_sprite(sprite_bank, wave)
            info_kind = "flying" if prefix == "IF" else "walking"
            enemy_info = _enemy_info_for_wave(level, info_kind, wave)
            reward_code = f"{wave.reward_kind[0].upper()}{wave.reward_info_index}" if wave.reward_kind and wave.reward_info_index is not None else "?"
            _draw_reward_preview(
                overlay,
                draw,
                sprite,
                wave.pixel_x,
                wave.pixel_y,
                enemy_info.width if enemy_info is not None else None,
                f"{prefix}{wave.index}→{reward_code}",
            )

    # Ordinary flying waves are spatial only after a map event cell resolves a relative .PAT path.
    if flying_paths is not None:
        for y in range(MAP_HEIGHT_CELLS):
            for x in range(MAP_WIDTH_CELLS):
                value = map_data.layer_b_at(x, y)
                if value < 3:
                    continue
                event_index = value - 3
                if selected_event_index is not None and event_index != selected_event_index:
                    continue
                event = alfils_data.event(event_index)
                if event is None or event.event_type_index != 0:
                    continue
                wave_index = event.param
                if not (0 <= wave_index < len(alfils_data.flying_waves)):
                    continue
                wave = alfils_data.flying_waves[wave_index]
                if not wave.has_reward:
                    continue
                if selected_flying_path_index is not None and wave.flying_path_index != selected_flying_path_index:
                    continue
                path = flying_paths.get(wave.flying_path_index)
                if path is None:
                    continue
                center_x = x * MAP_CELL_WIDTH + MAP_CELL_WIDTH // 2
                center_y = y * MAP_CELL_HEIGHT + MAP_CELL_HEIGHT // 2
                points = path.points_for_event_center(center_x, center_y)
                if not points:
                    continue
                sprite = _reward_sprite(sprite_bank, wave)
                enemy_info = _enemy_info_for_wave(level, "flying", wave)
                reward_code = f"{wave.reward_kind[0].upper()}{wave.reward_info_index}" if wave.reward_kind and wave.reward_info_index is not None else "?"
                _draw_reward_preview(
                    overlay,
                    draw,
                    sprite,
                    points[0][0],
                    points[0][1],
                    enemy_info.width if enemy_info is not None else None,
                    f"FW{wave.index}→{reward_code}",
                )

    image.alpha_composite(overlay)

def _build_wave_reward_canvas_overlay(
    map_data: GodsMap,
    alfils_data: AlfilsData,
    sprite_bank: SpriteBank | None,
    flying_paths: FlyingPathsData | None,
    level: int,
    selected_event_index: int | None = None,
    selected_flying_path_index: int | None = None,
) -> CanvasOverlay | None:
    color = (255, 244, 120, 255)
    markers: list[OverlayMarker] = []
    rects: list[OverlayRect] = []

    def add_reward(enemy_x: int, enemy_y: int, enemy_width: int | None, sprite: Image.Image | None, label: str) -> None:
        width = enemy_width if enemy_width is not None else 24
        if sprite is not None:
            reward_x = enemy_x + (width - sprite.width) // 2
            reward_y = enemy_y - sprite.height
            rects.append(OverlayRect(reward_x - 2, reward_y - 2, reward_x + sprite.width + 1, reward_y + sprite.height + 1, color, width=1))
            markers.append(OverlayMarker(reward_x + sprite.width + 4, reward_y - 2, label, color, shape="label_only"))
        else:
            markers.append(OverlayMarker(enemy_x + width // 2, enemy_y - 10, label, color, shape="ring"))

    for prefix, waves in (
        ("WW", alfils_data.active_walking_waves),
        ("IW", alfils_data.active_intel_walking_waves),
        ("IF", alfils_data.active_intel_flying_waves),
    ):
        for wave in waves:
            if not wave.has_reward:
                continue
            sprite = _reward_sprite(sprite_bank, wave)
            info_kind = "flying" if prefix == "IF" else "walking"
            enemy_info = _enemy_info_for_wave(level, info_kind, wave)
            reward_code = f"{wave.reward_kind[0].upper()}{wave.reward_info_index}" if wave.reward_kind and wave.reward_info_index is not None else "?"
            add_reward(wave.pixel_x, wave.pixel_y, enemy_info.width if enemy_info is not None else None, sprite, f"{prefix}{wave.index}->{reward_code}")

    if flying_paths is not None:
        for y in range(MAP_HEIGHT_CELLS):
            for x in range(MAP_WIDTH_CELLS):
                value = map_data.layer_b_at(x, y)
                if value < 3:
                    continue
                event_index = value - 3
                if selected_event_index is not None and event_index != selected_event_index:
                    continue
                event = alfils_data.event(event_index)
                if event is None or event.event_type_index != 0:
                    continue
                wave_index = event.param
                if not (0 <= wave_index < len(alfils_data.flying_waves)):
                    continue
                wave = alfils_data.flying_waves[wave_index]
                if not wave.has_reward:
                    continue
                if selected_flying_path_index is not None and wave.flying_path_index != selected_flying_path_index:
                    continue
                path = flying_paths.get(wave.flying_path_index)
                if path is None:
                    continue
                center_x = x * MAP_CELL_WIDTH + MAP_CELL_WIDTH // 2
                center_y = y * MAP_CELL_HEIGHT + MAP_CELL_HEIGHT // 2
                points = path.points_for_event_center(center_x, center_y)
                if not points:
                    continue
                sprite = _reward_sprite(sprite_bank, wave)
                enemy_info = _enemy_info_for_wave(level, "flying", wave)
                reward_code = f"{wave.reward_kind[0].upper()}{wave.reward_info_index}" if wave.reward_kind and wave.reward_info_index is not None else "?"
                add_reward(points[0][0], points[0][1], enemy_info.width if enemy_info is not None else None, sprite, f"FW{wave.index}->{reward_code}")

    return _merge_canvas_overlays(CanvasOverlay(markers=tuple(markers), rectangles=tuple(rects)))

def _draw_switches(image: Image.Image, alfils_data: AlfilsData) -> None:
    draw = ImageDraw.Draw(image)
    for record in alfils_data.active_switches:
        x, y = record.pixel_x, record.pixel_y
        draw.polygon(((x, y - 6), (x + 6, y), (x, y + 6), (x - 6, y)), outline=(0, 255, 120, 255))
        _label(draw, x + 8, y - 6, f"S{record.index}", (0, 255, 120, 255))


def _draw_teleports(image: Image.Image, alfils_data: AlfilsData, logic_graph: LogicGraph | None = None) -> None:
    draw = ImageDraw.Draw(image)
    for record in alfils_data.active_teleports:
        x, y = record.marker_x, record.marker_y
        # A nonzero teleport row is not necessarily live. The actual stone binding is by srcPixelX.
        # If the graph has no teleport_binding edge for this target, render it as an unbound/stale row.
        bound = False
        if logic_graph is not None:
            for edge in logic_graph.all_edges:
                if edge.edge_kind != "teleport_binding":
                    continue
                if edge.target.kind == "teleport" and edge.target.index == record.index:
                    bound = True
                    break
        label = f"T{record.index}" if bound or logic_graph is None else f"T{record.index}?"
        color = (0, 255, 255, 255) if bound or logic_graph is None else (100, 180, 180, 220)
        _rectangle_label(draw, (x, y, x + 31, y + 47), label, color)


def _draw_special_teleports(image: Image.Image, level: int) -> None:
    draw = ImageDraw.Draw(image)
    for record in special_teleport_destinations(level):
        x, y = record.pixel_x, record.pixel_y
        _rectangle_label(draw, (x, y, x + 31, y + 47), f"HT{record.index}", (255, 90, 90, 255))


def _draw_objective_locations(image: Image.Image, level: int) -> None:
    draw = ImageDraw.Draw(image)
    for record in objective_locations(level):
        x, y = record.pixel_x, record.pixel_y
        _rectangle_label(draw, (x, y, x + 31, y + 47), f"OJE{record.index}", (245, 245, 245, 255))


def _draw_player_start(image: Image.Image, level: int) -> None:
    record = player_start_location(level)
    if record is None:
        return
    draw = ImageDraw.Draw(image)
    x, y = record.pixel_x, record.pixel_y
    color = (120, 255, 120, 255)
    draw.rectangle((x, y, x + 31, y + 47), outline=color, width=2)
    draw.line((x + 16, y - 8, x + 16, y + 55), fill=color, width=1)
    draw.line((x - 8, y + 24, x + 39, y + 24), fill=color, width=1)
    _label(draw, x + 35, y + 3, "START", color)


def _moving_block_action_selection(
    alfils_data: AlfilsData,
    selected_event_index: int | None,
    selected_logic_point: LogicPoint | None,
) -> tuple[tuple[int, int, int | None], ...]:
    selected: list[tuple[int, int, int | None]] = []
    if selected_event_index is not None:
        event = alfils_data.event(selected_event_index)
        if event is not None and event.event_type_index is not None and 6 <= event.event_type_index <= 9:
            selected.append((event.param, event.event_type_index - 6, event.index))
        return tuple(selected)
    if selected_logic_point is not None and selected_logic_point.kind == "moving_block" and selected_logic_point.index is not None:
        block_index = selected_logic_point.index
        for event in alfils_data.active_events:
            if event.event_type_index is None or not (6 <= event.event_type_index <= 9):
                continue
            if event.param == block_index:
                selected.append((block_index, event.event_type_index - 6, event.index))
    return tuple(selected)


def _draw_moving_block_action_preview(
    image: Image.Image,
    alfils_data: AlfilsData,
    selected_event_index: int | None,
    selected_logic_point: LogicPoint | None,
) -> None:
    actions = _moving_block_action_selection(alfils_data, selected_event_index, selected_logic_point)
    if not actions:
        return
    draw = ImageDraw.Draw(image)
    color = (255, 140, 255, 255)
    shadow = (0, 0, 0, 220)
    for block_index, action_index, event_index in actions:
        if not (0 <= block_index < len(alfils_data.moving_blocks)):
            continue
        record = alfils_data.moving_blocks[block_index]
        if not record.appears_used:
            continue
        w, h = record.width_pixels, record.height_pixels
        start_center = (record.pixel_x + w // 2, record.pixel_y + h // 2)
        raw = record.action_raw(action_index)
        kind = record.action_kind(action_index)
        route: list[tuple[int, int]] = [start_center]
        active_targets = [
            (tx + w // 2, ty + h // 2)
            for tx, ty in record.target_points
            if not (tx == 0 and ty == 0)
        ]
        if kind == "move_to_target_then_stop":
            target_index = raw - 2
            if 0 <= target_index < len(record.target_points):
                tx, ty = record.target_points[target_index]
                if not (tx == 0 and ty == 0):
                    route.append((tx + w // 2, ty + h // 2))
        elif kind == "cycle_forward":
            route.extend(active_targets)
            if active_targets:
                route.append(active_targets[0])
        elif kind == "cycle_backward":
            route.extend(reversed(active_targets))
            if active_targets:
                route.append(active_targets[-1])
        elif kind == "disable":
            _label(draw, start_center[0] + 8, start_center[1] - 12, f"MB{block_index}/A{action_index}: disable", color)
            continue
        if len(route) < 2:
            _label(draw, start_center[0] + 8, start_center[1] - 12, f"MB{block_index}/A{action_index}: {kind}", color)
            continue
        draw.line(route, fill=shadow, width=5)
        draw.line(route, fill=color, width=3)
        for src, dst in zip(route, route[1:]):
            _draw_arrow_head(draw, src, dst, color)
        event_text = f" via E{event_index}" if event_index is not None else ""
        _label(draw, start_center[0] + 8, start_center[1] - 12, f"MB{block_index}/A{action_index}{event_text}", color)


def _draw_trapdoors(image: Image.Image, alfils_data: AlfilsData) -> None:
    draw = ImageDraw.Draw(image)
    for record in alfils_data.active_trapdoors:
        suffix = "O" if record.is_opened else "C"
        _rectangle_label(
            draw,
            (record.pixel_x, record.pixel_y, record.pixel_x + 31, record.pixel_y + 15),
            f"D{record.index}{suffix}",
            (255, 230, 0, 255),
        )


def _draw_moving_blocks(image: Image.Image, alfils_data: AlfilsData) -> None:
    draw = ImageDraw.Draw(image)
    for record in alfils_data.active_moving_blocks:
        x, y = record.pixel_x, record.pixel_y
        w, h = record.width_pixels, record.height_pixels
        color = (245, 245, 245, 255)
        _rectangle_label(draw, (x, y, x + w - 1, y + h - 1), f"MB{record.index}", color)
        src_center = (x + w // 2, y + h // 2)
        for target_index, (tx, ty) in enumerate(record.target_points):
            if tx == 0 and ty == 0:
                continue
            draw.rectangle((tx, ty, tx + w - 1, ty + h - 1), outline=(220, 220, 220, 170), width=1)
            dst_center = (tx + w // 2, ty + h // 2)
            draw.line((src_center[0], src_center[1], dst_center[0], dst_center[1]), fill=(220, 220, 220, 170), width=1)
            _label(draw, tx + 2, ty + 2, f"{target_index}", (220, 220, 220, 255))


def _draw_hints(image: Image.Image, alfils_data: AlfilsData) -> None:
    draw = ImageDraw.Draw(image)
    _width, height = image.size
    for record in alfils_data.active_hints:
        x = record.pixel_x
        draw.line((x, 0, x, height - 1), fill=(180, 120, 255, 180), width=1)
        _label(draw, x + 2, 2, f"H{record.index}", (180, 120, 255, 255))



def _draw_arrow_head(draw: ImageDraw.ImageDraw, start: tuple[int, int], end: tuple[int, int], color: tuple[int, int, int, int]) -> None:
    sx, sy = start
    ex, ey = end
    dx = ex - sx
    dy = ey - sy
    length = max(1.0, (dx * dx + dy * dy) ** 0.5)
    ux, uy = dx / length, dy / length
    # Small arrow head in map pixel coordinates.
    left = (int(ex - ux * 10 - uy * 5), int(ey - uy * 10 + ux * 5))
    right = (int(ex - ux * 10 + uy * 5), int(ey - uy * 10 - ux * 5))
    draw.polygon((end, left, right), fill=color)


def _point_is_drawable(point) -> bool:
    # Purely logical points have no physical source location in the map. They still belong
    # in the inspector graph, but not as lines to the top-left corner of the bitmap.
    return point.kind not in {"event_effect", "flying_wave", "checkpoint", "guardian", "destroy_type4_offmap", "object_inventory_ref", "weapon_inventory_ref", "flying_reward_object", "flying_reward_weapon", "remove_weapon_effect", "raster_effect", "timer_effect"}


def _draw_logic_endpoint(draw: ImageDraw.ImageDraw, point, color: tuple[int, int, int, int]) -> None:
    """Draw a compact, type-aware marker for physical logic targets."""

    x, y = point.pixel_x, point.pixel_y
    kind = point.kind

    if kind in {"spawned_object", "spawned_weapon"}:
        draw.ellipse((x - 6, y - 6, x + 6, y + 6), outline=color, width=2)
        _label(draw, x + 8, y - 6, point.label, color)
    elif kind in {"door", "backdoor", "backdoor_destination", "backdoor_world"}:
        draw.rectangle((x - 16, y - 24, x + 15, y + 23), outline=color, width=2)
        _label(draw, x - 14, y - 22, point.label, color)
    elif kind in {"destructable_object", "spawned_destructable_object"}:
        draw.rectangle((x - 4, y - 4, x + 24, y + 24), outline=color, width=2)
        _label(draw, x + 26, y - 8, point.label, color)
    elif kind == "destroy_type4_unresolved":
        draw.rectangle((x - 12, y - 12, x + 12, y + 12), outline=color, width=2)
        _label(draw, x + 14, y - 8, point.label, color)
    elif kind == "trapdoor":
        draw.rectangle((x, y, x + 31, y + 15), outline=color, width=2)
        _label(draw, x + 2, y + 2, point.label, color)
    elif kind in {"puzzle", "event_cell", "switch", "walking_wave", "intel_walking_wave", "intel_flying_wave", "moving_block"}:
        # These already have dedicated overlays in the level renderer. A small target ring keeps
        # selected logic readable even when that overlay category is hidden.
        draw.ellipse((x - 4, y - 4, x + 4, y + 4), outline=color, width=2)


def _edge_color(edge) -> tuple[int, int, int, int]:
    if edge.edge_kind == "puzzle_condition":
        return (255, 80, 220, 235) if edge.positive_state is not False else (255, 150, 80, 235)
    if edge.edge_kind == "puzzle_effect":
        return (80, 220, 255, 235)
    return (235, 235, 235, 235)


def _dedupe_edges(edges) -> tuple:
    selected = []
    seen = set()
    for edge in edges:
        edge_id = id(edge)
        if edge_id in seen:
            continue
        seen.add(edge_id)
        selected.append(edge)
    return tuple(selected)


def _direct_edges_for_event(graph: LogicGraph, index: int) -> tuple:
    return _dedupe_edges(graph.outgoing_edges_for_event(index) + graph.incoming_edges_for_event(index))


def _one_hop_edges_for_event(graph: LogicGraph, index: int) -> tuple:
    edges = list(_direct_edges_for_event(graph, index))
    for edge in tuple(edges):
        for point in (edge.source, edge.target):
            if point.kind == "event_cell" and point.index == index:
                continue
            edges.extend(graph.direct_edges_for_point(point))
    return _dedupe_edges(edges)


def _one_hop_edges_for_point(graph: LogicGraph, point: LogicPoint) -> tuple:
    edges = list(graph.direct_edges_for_point(point))
    for edge in tuple(edges):
        other = edge.target if graph._same_graph_node(edge.source, point) else edge.source
        edges.extend(graph.direct_edges_for_point(other))
    return _dedupe_edges(edges)


def _build_logic_canvas_overlay(
    graph: LogicGraph,
    selected_event_index: int | None,
    selected_logic_point: LogicPoint | None,
    scope: str,
) -> CanvasOverlay | None:
    if selected_logic_point is not None:
        if scope == "full":
            edges = graph.related_edges_for_point(selected_logic_point, recursive=True)
        elif scope == "one_hop":
            edges = _one_hop_edges_for_point(graph, selected_logic_point)
        else:
            edges = graph.direct_edges_for_point(selected_logic_point)
    elif selected_event_index is not None:
        if scope == "full":
            edges = graph.related_edges_for_event(selected_event_index, recursive=True)
        elif scope == "one_hop":
            edges = _one_hop_edges_for_event(graph, selected_event_index)
        else:
            edges = _direct_edges_for_event(graph, selected_event_index)
    else:
        return None

    if not edges:
        return None

    lines: list[OverlayLine] = []
    markers: list[OverlayMarker] = []
    seen_points: set[tuple[str, int | None, int, int, str]] = set()

    for edge in edges:
        color = _edge_color(edge)
        if _point_is_drawable(edge.source) and _point_is_drawable(edge.target):
            lines.append(OverlayLine(edge.source.pixel_x, edge.source.pixel_y, edge.target.pixel_x, edge.target.pixel_y, color, width=2))
        for point in (edge.source, edge.target):
            if not _point_is_drawable(point):
                continue
            key = (point.kind, point.index, point.pixel_x, point.pixel_y, point.label)
            if key in seen_points:
                continue
            seen_points.add(key)
            markers.append(OverlayMarker(point.pixel_x, point.pixel_y, point.label, color, shape="ring"))

    if selected_event_index is not None:
        for point in graph.event_cell_points(selected_event_index):
            markers.append(OverlayMarker(point.pixel_x, point.pixel_y, f"E{selected_event_index}", (255, 40, 255, 255), shape="cell"))
    if selected_logic_point is not None and _point_is_drawable(selected_logic_point):
        markers.append(OverlayMarker(selected_logic_point.pixel_x, selected_logic_point.pixel_y, f"selected {selected_logic_point.label}", (255, 40, 255, 255), shape="selected"))

    return CanvasOverlay(lines=tuple(lines), markers=tuple(markers))



def _build_event_canvas_overlay(map_data: GodsMap, alfils_data: AlfilsData | None, selected_event_index: int | None) -> CanvasOverlay | None:
    rects: list[OverlayRect] = []
    markers: list[OverlayMarker] = []
    for y in range(MAP_HEIGHT_CELLS):
        for x in range(MAP_WIDTH_CELLS):
            value = map_data.layer_b_at(x, y)
            if value < 3:
                continue
            event_index = value - 3
            px = x * MAP_CELL_WIDTH
            py = y * MAP_CELL_HEIGHT
            label = None
            width = 1
            color = (170, 150, 40, 255)
            if selected_event_index == event_index:
                event = alfils_data.event(event_index) if alfils_data is not None else None
                label = f"{event_index}" if event is None else f"{event.acronym}{event_index}"
                width = 2
                color = (255, 230, 0, 255)
                markers.append(OverlayMarker(px + MAP_CELL_WIDTH // 2, py + MAP_CELL_HEIGHT // 2, label, color, shape="cell"))
            rects.append(OverlayRect(px, py, px + MAP_CELL_WIDTH - 1, py + MAP_CELL_HEIGHT - 1, color, width=width, label=None))
    return _merge_canvas_overlays(CanvasOverlay(markers=tuple(markers), rectangles=tuple(rects)))


def _build_item_marker_canvas_overlay(map_data: GodsMap) -> CanvasOverlay | None:
    markers = [OverlayMarker(item.pixel_x, item.pixel_y, None, (0, 200, 220, 255), shape="dot") for item in map_data.active_items]
    return _merge_canvas_overlays(CanvasOverlay(markers=tuple(markers)))


def _build_puzzle_canvas_overlay(map_data: GodsMap) -> CanvasOverlay | None:
    markers = [OverlayMarker(p.pixel_x, p.pixel_y, None, (215, 90, 200, 255), shape="square") for p in map_data.active_puzzles if not (p.pixel_x == 0 and p.pixel_y == 0)]
    return _merge_canvas_overlays(CanvasOverlay(markers=tuple(markers)))


def _build_hidden_spawned_canvas_overlay(
    map_data: GodsMap,
    sprite_bank: SpriteBank | None,
) -> CanvasOverlay | None:
    color = (180, 255, 255, 255)
    rects: list[OverlayRect] = []
    markers: list[OverlayMarker] = []
    for x, y, sprite, label in _hidden_spawned_item_entries(map_data, sprite_bank):
        rects.append(OverlayRect(x, y, x + sprite.width - 1, y + sprite.height - 1, color, width=1))
        markers.append(OverlayMarker(x + sprite.width + 3, y - 2, label, color, shape="label_only"))
    return _merge_canvas_overlays(CanvasOverlay(markers=tuple(markers), rectangles=tuple(rects)))


def _build_enemy_wave_canvas_overlay(alfils_data: AlfilsData) -> CanvasOverlay | None:
    markers: list[OverlayMarker] = []
    markers.extend(OverlayMarker(w.pixel_x, w.pixel_y, None, (255, 100, 100, 255), shape="ring") for w in alfils_data.active_walking_waves)
    markers.extend(OverlayMarker(w.pixel_x, w.pixel_y, None, (255, 160, 80, 255), shape="square") for w in alfils_data.active_intel_walking_waves)
    markers.extend(OverlayMarker(w.pixel_x, w.pixel_y, None, (255, 80, 80, 255), shape="triangle") for w in alfils_data.active_intel_flying_waves)
    return _merge_canvas_overlays(CanvasOverlay(markers=tuple(markers)))


def _build_enemy_sprite_label_canvas_overlay(
    map_data: GodsMap,
    alfils_data: AlfilsData,
    sprite_bank: SpriteBank | None,
    flying_paths: FlyingPathsData | None,
    level: int,
    selected_event_index: int | None = None,
    selected_flying_path_index: int | None = None,
) -> CanvasOverlay | None:
    markers: list[OverlayMarker] = []
    for prefix, kind, waves, color in (
        ("WW", "walking", alfils_data.active_walking_waves, (255, 120, 120, 255)),
        ("IW", "walking", alfils_data.active_intel_walking_waves, (255, 170, 90, 255)),
        ("IF", "flying", alfils_data.active_intel_flying_waves, (255, 100, 100, 255)),
    ):
        for wave in waves:
            info = _enemy_info_for_wave(level, kind, wave)
            sprite = _enemy_sprite(sprite_bank, info, getattr(wave, "facing", 0))
            width = sprite.width if sprite is not None else (info.width if info is not None else 24)
            markers.append(OverlayMarker(wave.pixel_x + width + 3, wave.pixel_y - 2, f"{prefix}{wave.index}", color, shape="label_only"))

    if flying_paths is not None:
        for y in range(MAP_HEIGHT_CELLS):
            for x in range(MAP_WIDTH_CELLS):
                value = map_data.layer_b_at(x, y)
                if value < 3:
                    continue
                event_index = value - 3
                if selected_event_index is not None and event_index != selected_event_index:
                    continue
                event = alfils_data.event(event_index)
                if event is None or event.event_type_index != 0:
                    continue
                wave_index = event.param
                if not (0 <= wave_index < len(alfils_data.flying_waves)):
                    continue
                wave = alfils_data.flying_waves[wave_index]
                if selected_flying_path_index is not None and wave.flying_path_index != selected_flying_path_index:
                    continue
                path = flying_paths.get(wave.flying_path_index)
                if path is None:
                    continue
                center_x = x * MAP_CELL_WIDTH + MAP_CELL_WIDTH // 2
                center_y = y * MAP_CELL_HEIGHT + MAP_CELL_HEIGHT // 2
                points = path.points_for_event_center(center_x, center_y)
                if not points:
                    continue
                info = _enemy_info_for_wave(level, "flying", wave)
                sprite = _enemy_sprite(sprite_bank, info, 0)
                width = sprite.width if sprite is not None else (info.width if info is not None else 24)
                markers.append(OverlayMarker(points[0][0] + width + 3, points[0][1] - 2, f"FW{wave.index}/E{event_index}", (120, 255, 200, 255), shape="label_only"))

    return _merge_canvas_overlays(CanvasOverlay(markers=tuple(markers)))


def _build_switch_canvas_overlay(alfils_data: AlfilsData) -> CanvasOverlay | None:
    markers = [OverlayMarker(r.pixel_x, r.pixel_y, None, (0, 255, 120, 255), shape="diamond") for r in alfils_data.active_switches]
    return _merge_canvas_overlays(CanvasOverlay(markers=tuple(markers)))


def _build_teleport_canvas_overlay(alfils_data: AlfilsData, logic_graph: LogicGraph | None = None) -> CanvasOverlay | None:
    rects: list[OverlayRect] = []
    for record in alfils_data.active_teleports:
        bound = False
        if logic_graph is not None:
            for edge in logic_graph.all_edges:
                if edge.edge_kind == "teleport_binding" and edge.target.kind == "teleport" and edge.target.index == record.index:
                    bound = True
                    break
        color = (0, 255, 255, 255) if bound or logic_graph is None else (120, 170, 170, 255)
        rects.append(OverlayRect(record.marker_x, record.marker_y, record.marker_x + 31, record.marker_y + 47, color, width=2 if bound else 1))
    return _merge_canvas_overlays(CanvasOverlay(rectangles=tuple(rects)))


def _build_special_teleport_canvas_overlay(level: int) -> CanvasOverlay | None:
    rects = [OverlayRect(r.pixel_x, r.pixel_y, r.pixel_x + 31, r.pixel_y + 47, (255, 90, 90, 255), width=1) for r in special_teleport_destinations(level)]
    return _merge_canvas_overlays(CanvasOverlay(rectangles=tuple(rects)))


def _build_objective_canvas_overlay(level: int) -> CanvasOverlay | None:
    rects = [OverlayRect(r.pixel_x, r.pixel_y, r.pixel_x + 31, r.pixel_y + 47, (235, 235, 235, 255), width=1, label=f"OJE{r.index}") for r in objective_locations(level)]
    return _merge_canvas_overlays(CanvasOverlay(rectangles=tuple(rects)))


def _build_player_start_canvas_overlay(level: int) -> CanvasOverlay | None:
    record = player_start_location(level)
    if record is None:
        return None
    rects = [OverlayRect(record.pixel_x, record.pixel_y, record.pixel_x + 31, record.pixel_y + 47, (120, 255, 120, 255), width=2)]
    lines = [
        OverlayLine(record.pixel_x + 16, record.pixel_y - 8, record.pixel_x + 16, record.pixel_y + 55, (120, 255, 120, 255), width=1),
        OverlayLine(record.pixel_x - 8, record.pixel_y + 24, record.pixel_x + 39, record.pixel_y + 24, (120, 255, 120, 255), width=1),
    ]
    markers = [OverlayMarker(record.pixel_x + 16, record.pixel_y + 24, "START", (120, 255, 120, 255), shape="selected")]
    return _merge_canvas_overlays(CanvasOverlay(lines=tuple(lines), markers=tuple(markers), rectangles=tuple(rects)))


def _build_trapdoor_canvas_overlay(alfils_data: AlfilsData) -> CanvasOverlay | None:
    rects = [OverlayRect(r.pixel_x, r.pixel_y, r.pixel_x + 31, r.pixel_y + 15, (255, 230, 0, 255), width=2 if r.is_opened else 1) for r in alfils_data.active_trapdoors]
    return _merge_canvas_overlays(CanvasOverlay(rectangles=tuple(rects)))


def _build_moving_blocks_canvas_overlay(alfils_data: AlfilsData) -> CanvasOverlay | None:
    rects: list[OverlayRect] = []
    lines: list[OverlayLine] = []
    markers: list[OverlayMarker] = []
    for record in alfils_data.active_moving_blocks:
        x, y = record.pixel_x, record.pixel_y
        w, h = record.width_pixels, record.height_pixels
        rects.append(OverlayRect(x, y, x + w - 1, y + h - 1, (245, 245, 245, 255), width=2))
        src_center = (x + w // 2, y + h // 2)
        for target_index, (tx, ty) in enumerate(record.target_points):
            if tx == 0 and ty == 0:
                continue
            rects.append(OverlayRect(tx, ty, tx + w - 1, ty + h - 1, (185, 185, 185, 255), width=1))
            dst_center = (tx + w // 2, ty + h // 2)
            lines.append(OverlayLine(src_center[0], src_center[1], dst_center[0], dst_center[1], (185, 185, 185, 255), width=1, dashed=True))
            markers.append(OverlayMarker(tx + 2, ty + 2, str(target_index), (220, 220, 220, 255), shape="label_only"))
    return _merge_canvas_overlays(CanvasOverlay(lines=tuple(lines), markers=tuple(markers), rectangles=tuple(rects)))


def _build_hint_canvas_overlay(alfils_data: AlfilsData) -> CanvasOverlay | None:
    lines = [OverlayLine(r.pixel_x, 0, r.pixel_x, MAP_HEIGHT_CELLS * MAP_CELL_HEIGHT - 1, (180, 120, 255, 255), width=1, dashed=True) for r in alfils_data.active_hints]
    return _merge_canvas_overlays(CanvasOverlay(lines=tuple(lines)))


def _build_flying_path_canvas_overlay(
    map_data: GodsMap,
    alfils_data: AlfilsData,
    flying_paths: FlyingPathsData | None,
    selected_event_index: int | None = None,
    selected_flying_path_index: int | None = None,
) -> CanvasOverlay | None:
    if flying_paths is None:
        return None
    lines: list[OverlayLine] = []
    markers: list[OverlayMarker] = []
    for y in range(MAP_HEIGHT_CELLS):
        for x in range(MAP_WIDTH_CELLS):
            value = map_data.layer_b_at(x, y)
            if value < 3:
                continue
            event_index = value - 3
            if selected_event_index is not None and event_index != selected_event_index:
                continue
            event = alfils_data.event(event_index)
            if event is None or event.event_type_index != 0:
                continue
            wave_index = event.param
            if not (0 <= wave_index < len(alfils_data.flying_waves)):
                continue
            wave = alfils_data.flying_waves[wave_index]
            if selected_flying_path_index is not None and wave.flying_path_index != selected_flying_path_index:
                continue
            path = flying_paths.get(wave.flying_path_index)
            if path is None:
                continue
            center_x = x * MAP_CELL_WIDTH + MAP_CELL_WIDTH // 2
            center_y = y * MAP_CELL_HEIGHT + MAP_CELL_HEIGHT // 2
            points = path.points_for_event_center(center_x, center_y)
            if len(points) < 2:
                continue
            color = (80, 255, 180, 255) if path.is_absolute else (255, 180, 80, 255)
            for src, dst in zip(points, points[1:]):
                lines.append(OverlayLine(src[0], src[1], dst[0], dst[1], color, width=2))
            markers.append(OverlayMarker(points[0][0], points[0][1], None, color, shape="ring"))
            markers.append(OverlayMarker(points[-1][0], points[-1][1], None, color, shape="square"))
            if selected_event_index == event_index or selected_flying_path_index == wave.flying_path_index:
                markers.append(OverlayMarker(points[0][0], points[0][1], f"FW{wave_index}/FP{path.index}", color, shape="label_only"))
    return _merge_canvas_overlays(CanvasOverlay(lines=tuple(lines), markers=tuple(markers)))


def _build_moving_block_action_canvas_overlay(
    alfils_data: AlfilsData,
    selected_event_index: int | None,
    selected_logic_point: LogicPoint | None,
) -> CanvasOverlay | None:
    actions = _moving_block_action_selection(alfils_data, selected_event_index, selected_logic_point)
    if not actions:
        return None
    lines: list[OverlayLine] = []
    markers: list[OverlayMarker] = []
    for block_index, action_index, event_index in actions:
        if not (0 <= block_index < len(alfils_data.moving_blocks)):
            continue
        record = alfils_data.moving_blocks[block_index]
        if not record.appears_used:
            continue
        w, h = record.width_pixels, record.height_pixels
        start_center = (record.pixel_x + w // 2, record.pixel_y + h // 2)
        raw = record.action_raw(action_index)
        kind = record.action_kind(action_index)
        route: list[tuple[int, int]] = [start_center]
        active_targets = [(tx + w // 2, ty + h // 2) for tx, ty in record.target_points if not (tx == 0 and ty == 0)]
        if kind == "move_to_target_then_stop":
            target_index = raw - 2
            if 0 <= target_index < len(record.target_points):
                tx, ty = record.target_points[target_index]
                if not (tx == 0 and ty == 0):
                    route.append((tx + w // 2, ty + h // 2))
        elif kind == "cycle_forward":
            route.extend(active_targets)
            if active_targets:
                route.append(active_targets[0])
        elif kind == "cycle_backward":
            route.extend(reversed(active_targets))
            if active_targets:
                route.append(active_targets[-1])
        elif kind == "disable":
            markers.append(OverlayMarker(start_center[0], start_center[1], f"MB{block_index}/A{action_index}: disable", (255, 140, 255, 255), shape="label_only"))
            continue
        if len(route) < 2:
            markers.append(OverlayMarker(start_center[0], start_center[1], f"MB{block_index}/A{action_index}: {kind}", (255, 140, 255, 255), shape="label_only"))
            continue
        for src, dst in zip(route, route[1:]):
            lines.append(OverlayLine(src[0], src[1], dst[0], dst[1], (255, 140, 255, 255), width=3))
        event_text = f" via E{event_index}" if event_index is not None else ""
        markers.append(OverlayMarker(start_center[0], start_center[1], f"MB{block_index}/A{action_index}{event_text}", (255, 140, 255, 255), shape="label_only"))
    return _merge_canvas_overlays(CanvasOverlay(lines=tuple(lines), markers=tuple(markers)))


def render_level_map(
    map_data: GodsMap,
    resource: LevelResource,
    options: LevelRenderOptions | None = None,
    alfils_data: AlfilsData | None = None,
    object_table: ObjectTable | None = None,
    weapon_table: WeaponTable | None = None,
    sprite_bank: SpriteBank | None = None,
    flying_paths: FlyingPathsData | None = None,
) -> LevelRenderResult:
    options = options or LevelRenderOptions()
    tiles = load_level_tile_bank(resource)
    image = _build_background(map_data, options)
    draw = ImageDraw.Draw(image)
    missing: set[int] = set()

    for y in range(MAP_HEIGHT_CELLS):
        for x in range(MAP_WIDTH_CELLS):
            tile_id = map_data.layer_a_at(x, y)
            if tile_id == 0:
                continue
            tile_index = tile_id - 1
            px = x * MAP_CELL_WIDTH
            py = y * MAP_CELL_HEIGHT
            if 0 <= tile_index < len(tiles):
                image.alpha_composite(tiles[tile_index], (px, py))
            else:
                missing.add(tile_id)
                draw.rectangle((px, py, px + MAP_CELL_WIDTH - 1, py + MAP_CELL_HEIGHT - 1), fill=(160, 0, 120, 255))
                _label(draw, px + 2, py + 2, str(tile_id), (255, 255, 255, 255))

    if options.show_item_sprites:
        _draw_map_item_sprites(image, map_data, sprite_bank)
    if options.show_hidden_spawned_items:
        _draw_hidden_spawned_item_sprites(image, map_data, sprite_bank)

    if options.show_collision_overlay:
        _draw_collision_overlay(image, map_data)
    semantic_overlays: list[CanvasOverlay | None] = []
    if options.show_item_markers:
        semantic_overlays.append(_build_item_marker_canvas_overlay(map_data))
    if options.show_puzzle_markers:
        semantic_overlays.append(_build_puzzle_canvas_overlay(map_data))
    if options.show_hidden_spawned_items:
        semantic_overlays.append(_build_hidden_spawned_canvas_overlay(map_data, sprite_bank))

    if options.show_event_overlay:
        semantic_overlays.append(_build_event_canvas_overlay(map_data, alfils_data, options.selected_event_index))

    canvas_overlay = None
    if alfils_data is not None:
        if options.show_enemy_wave_markers:
            semantic_overlays.append(_build_enemy_wave_canvas_overlay(alfils_data))
        if options.show_enemy_sprites:
            _draw_enemy_sprites(
                image,
                map_data,
                alfils_data,
                sprite_bank,
                flying_paths,
                resource.level,
                options.selected_event_index,
                options.selected_flying_path_index,
            )
            semantic_overlays.append(_build_enemy_sprite_label_canvas_overlay(
                map_data,
                alfils_data,
                sprite_bank,
                flying_paths,
                resource.level,
                options.selected_event_index,
                options.selected_flying_path_index,
            ))
        if options.show_flying_wave_paths:
            semantic_overlays.append(_build_flying_path_canvas_overlay(
                map_data,
                alfils_data,
                flying_paths,
                options.selected_event_index,
                options.selected_flying_path_index,
            ))
        if options.show_wave_reward_previews:
            semantic_overlays.append(_build_wave_reward_canvas_overlay(
                map_data,
                alfils_data,
                sprite_bank,
                flying_paths,
                resource.level,
                options.selected_event_index,
                options.selected_flying_path_index,
            ))
        if options.show_switch_markers:
            semantic_overlays.append(_build_switch_canvas_overlay(alfils_data))
        if options.show_teleport_markers:
            teleport_graph = build_logic_graph(map_data, alfils_data, object_table, weapon_table)
            semantic_overlays.append(_build_teleport_canvas_overlay(alfils_data, teleport_graph))
        if options.show_special_teleport_markers:
            semantic_overlays.append(_build_special_teleport_canvas_overlay(resource.level))
        if options.show_objective_location_markers:
            semantic_overlays.append(_build_objective_canvas_overlay(resource.level))
        if options.show_player_start_marker:
            semantic_overlays.append(_build_player_start_canvas_overlay(resource.level))
        if options.show_trapdoor_markers:
            semantic_overlays.append(_build_trapdoor_canvas_overlay(alfils_data))
        if options.show_moving_block_markers:
            semantic_overlays.append(_build_moving_blocks_canvas_overlay(alfils_data))
        if options.show_moving_block_action_preview:
            semantic_overlays.append(_build_moving_block_action_canvas_overlay(
                alfils_data,
                options.selected_event_index,
                options.selected_logic_point,
            ))
        if options.show_hint_markers:
            semantic_overlays.append(_build_hint_canvas_overlay(alfils_data))
        if options.show_logic_links and (options.selected_event_index is not None or options.selected_logic_point is not None):
            graph = build_logic_graph(map_data, alfils_data, object_table, weapon_table)
            semantic_overlays.append(_build_logic_canvas_overlay(
                graph,
                options.selected_event_index,
                options.selected_logic_point,
                options.logic_link_scope,
            ))

    canvas_overlay = _merge_canvas_overlays(*semantic_overlays)

    if options.show_grid:
        grid_draw = ImageDraw.Draw(image)
        width, height = image.size
        for x in range(0, width + 1, MAP_CELL_WIDTH):
            grid_draw.line((x, 0, x, height), fill=(255, 255, 255, 64))
        for y in range(0, height + 1, MAP_CELL_HEIGHT):
            grid_draw.line((0, y, width, y), fill=(255, 255, 255, 64))

    return LevelRenderResult(
        image=image.convert("RGB"),
        loaded_tile_count=len(tiles),
        missing_tile_ids=tuple(sorted(missing)),
        extra_bank_used=resource.extra_path,
        canvas_overlay=canvas_overlay,
    )
