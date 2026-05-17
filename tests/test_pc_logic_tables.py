from gods_tools.formats.pc_logic_tables import objective_locations, special_teleport_destinations


def test_special_teleport_tables_match_verified_pc_extract() -> None:
    level1 = special_teleport_destinations(1)
    level2 = special_teleport_destinations(2)
    assert len(level1) == 8
    assert len(level2) == 6
    assert level1[0].coded == 0x182C
    assert (level1[0].pixel_x, level1[0].pixel_y) == (784, 704)
    assert level2[-1].coded == 0x202E
    assert level2[-1].unpacked_game_offset is None


def test_objective_location_tables_are_present() -> None:
    assert [len(objective_locations(level)) for level in range(1, 5)] == [9, 19, 13, 13]
    first = objective_locations(1)[0]
    assert (first.cell_x, first.cell_y) == (8, 25)
    assert (first.pixel_x, first.pixel_y) == (256, 416)
