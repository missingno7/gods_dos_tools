from pathlib import Path

from gods_tools.formats.flying_paths import parse_flying_paths


def _u32(value: int) -> bytes:
    return value.to_bytes(4, "big", signed=False)


def _s32(value: int) -> bytes:
    return value.to_bytes(4, "big", signed=True)


def test_parse_relative_and_absolute_paths() -> None:
    relative = (12).to_bytes(2, "big", signed=True) + (-7).to_bytes(2, "big", signed=True) + bytes([0x1F, 0xE2])
    absolute = (0x2345).to_bytes(2, "big") + (100).to_bytes(2, "big") + (200).to_bytes(2, "big") + bytes([0x11])
    header = _s32(1) + _u32(len(relative)) + _s32(2) + _u32(len(absolute)) + _s32(-1) + _u32(0)
    data = header.ljust(0x190, b"\x00") + relative + absolute
    parsed = parse_flying_paths(data, Path("synthetic.PAT"))

    assert len(parsed.paths) == 2
    rel = parsed.paths[0]
    assert rel.kind == "relative"
    assert rel.deltas == ((1, -1), (-2, 2))
    assert rel.points_for_event_center(160, 96) == ((12, -7), (13, -8), (11, -6))

    abs_path = parsed.paths[1]
    assert abs_path.kind == "absolute"
    assert abs_path.points_for_event_center(999, 999) == ((100, 200), (101, 201))
