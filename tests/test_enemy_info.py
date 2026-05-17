from gods_tools.formats.enemy_info import get_enemy_info


def test_enemy_info_maps_kroah_sprite_indices_to_dos_bank() -> None:
    flying = get_enemy_info(1, "flying", 0)
    walking = get_enemy_info(1, "walking", 0)
    mouth = get_enemy_info(1, "walking", 5)

    assert flying is not None
    assert flying.sprite_index_st == 448
    assert flying.sprite_index_dos == 450
    assert flying.width == 32 and flying.height == 32

    assert walking is not None
    assert walking.sprite_index_for_facing(0) == 462
    assert walking.sprite_index_for_facing(1) == 471

    assert mouth is not None
    # Kroah's viewer reverses facing for mouth/turret-like enemies.
    assert mouth.sprite_index_for_facing(0) == 535
    assert mouth.sprite_index_for_facing(1) == 532
