from pathlib import Path

from gods_tools.formats.atlas_dat import load_packed_atlas_dat
from gods_tools.formats.item_tables import ObjectInfo
from gods_tools.formats.pi1 import load_packed_pi1


def test_unnamed_switch_object_is_named_button() -> None:
    info = ObjectInfo(
        index=118,
        sprite_index=0,
        unknown_always_zero=0,
        type_index=3,
        value=0,
        name="",
        description="",
        effect_index=None,
    )
    assert info.full_name == "button"


def test_pi1_unpack_and_decode() -> None:
    path = Path("game_data/Gods/PALWAYS1.PI1")
    pi1 = load_packed_pi1(path)
    assert pi1.width == 320
    assert pi1.height == 200
    assert len(pi1.pixels) == 320 * 200


def test_atlas_dat_unpack() -> None:
    path = Path("game_data/Gods/PALWAYS1.DAT")
    atlas = load_packed_atlas_dat(path)
    assert atlas.count == 39
    assert atlas.records[0].width == 32
    assert atlas.records[0].height == 48
