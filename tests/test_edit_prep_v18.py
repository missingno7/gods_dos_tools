from pathlib import Path

import pytest

from gods_tools.edit.patches import PatchPlanError, RawBytePatch, WriteBackPlan
from gods_tools.edit.session import EditSession, map_payload_layout
from gods_tools.formats.alfils import load_packed_alfils
from gods_tools.formats.diagnostics import build_level_diagnostics
from gods_tools.formats.flying_paths import load_packed_flying_paths
from gods_tools.formats.item_tables import (
    level_object_table_path,
    level_weapon_table_path,
    load_packed_object_table,
    load_packed_weapon_table,
)
from gods_tools.formats.levels import discover_level_resources
from gods_tools.formats.logic import build_logic_graph
from gods_tools.formats.map import parse_map_payload, load_packed_map
from gods_tools.model.document import LevelDocument
from gods_tools.model.entities import build_entity_index
from gods_tools.render.sprites import load_level_sprite_bank

GAME_DIR = Path(__file__).resolve().parents[1] / "game_data" / "Gods"


def _document_1a() -> LevelDocument:
    resource = next(resource for resource in discover_level_resources(GAME_DIR) if resource.key == "1A")
    map_data = load_packed_map(resource.map_path)
    alfils = load_packed_alfils(resource.alfils_path)
    objects = load_packed_object_table(level_object_table_path(GAME_DIR, resource.level))
    weapons = load_packed_weapon_table(level_weapon_table_path(GAME_DIR, resource.level))
    sprite_bank = load_level_sprite_bank(GAME_DIR, resource.level, resource.world)
    paths = load_packed_flying_paths(resource.flying_paths_path)
    graph = build_logic_graph(map_data, alfils, objects, weapons)
    diagnostics = build_level_diagnostics(map_data, alfils, graph)
    return LevelDocument(
        resource=resource,
        map_data=map_data,
        alfils_data=alfils,
        object_table=objects,
        weapon_table=weapons,
        sprite_bank=sprite_bank,
        flying_paths=paths,
        logic_graph=graph,
        diagnostics=diagnostics,
    )


def test_level_document_and_entity_index_cover_main_browser_groups() -> None:
    document = _document_1a()
    index = build_entity_index(document)
    assert document.has_logic
    assert index.count > 0
    assert index.by_group("Events")
    assert index.by_group("Map items")
    assert any(group.startswith("Logic:") for group, _entities in index.counts_by_group())
    assert index.find("event", 0) is not None


def test_edit_session_move_item_creates_safe_patch_and_reparses() -> None:
    document = _document_1a()
    first = document.map_data.active_items[0]
    session = EditSession(document).plan_move_map_item(first.index, pixel_x=first.pixel_x + 1, pixel_y=first.pixel_y + 2)
    assert session.patch_count == 1
    patched = session.preview_patched_map_payload()
    reparsed = parse_map_payload(patched)
    changed = reparsed.items[first.index]
    assert (changed.pixel_x, changed.pixel_y) == (first.pixel_x + 1, first.pixel_y + 2)


def test_edit_session_layer_patch_uses_stable_layout() -> None:
    document = _document_1a()
    layout = map_payload_layout(document)
    session = EditSession(document).plan_set_layer_a_tile(0, 0, 7)
    patch = session.plan.patches[0]
    assert patch.offset == layout.layer_a_offset
    patched = session.preview_patched_map_payload()
    assert patched[layout.layer_a_offset] == 7


def test_writeback_plan_rejects_overlapping_patches() -> None:
    patch_a = RawBytePatch("map", 10, b"\x01\x02", b"\x03\x04", "a")
    patch_b = RawBytePatch("map", 11, b"\x02\x05", b"\x06\x07", "b")
    with pytest.raises(PatchPlanError):
        WriteBackPlan((patch_a, patch_b)).validate()
