from pathlib import Path

from gods_tools.formats.alfils import load_packed_alfils
from gods_tools.formats.levels import discover_level_resources


def test_wave_reward_decoding_matches_object_weapon_split() -> None:
    resource = discover_level_resources(Path("game_data/Gods"))[0]
    assert resource.alfils_path is not None
    alfils = load_packed_alfils(resource.alfils_path)

    flying_with_rewards = [wave for wave in alfils.active_flying_waves if wave.has_reward]
    assert flying_with_rewards
    assert any(wave.reward_kind == "object" for wave in flying_with_rewards)
    assert any(wave.reward_kind == "weapon" for wave in flying_with_rewards)

    for wave in flying_with_rewards:
        assert wave.reward_info_index is not None
        if wave.reward_kind == "weapon":
            assert 0 <= wave.reward_info_index <= 10
        elif wave.reward_kind == "object":
            assert wave.reward_info_index >= 0
        else:
            raise AssertionError(f"unexpected reward kind {wave.reward_kind!r}")
