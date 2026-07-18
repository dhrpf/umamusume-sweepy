import pytest

from career_bot.campaigns.cycle import (
    CampaignCycleState,
    advance_bootstrap_rotation,
    enter_final_stage,
    migrate_stage_state_to_cycle,
    record_final_repeat,
)


def test_bootstrap_rotation_wraps_after_three_members():
    state = CampaignCycleState.bootstrap([1001, 1002, 1003])
    assert state.next_bootstrap_chara_id == 1001

    state = advance_bootstrap_rotation(state, produced_legacy_id="v1")
    assert state.next_bootstrap_chara_id == 1002
    state = advance_bootstrap_rotation(state, produced_legacy_id="v2")
    assert state.next_bootstrap_chara_id == 1003
    state = advance_bootstrap_rotation(state, produced_legacy_id="v3")
    assert state.next_bootstrap_chara_id == 1001
    assert state.run_index == 3
    assert state.produced == ((1001, "v1"), (1002, "v2"), (1003, "v3"))


def test_enter_final_stops_bootstrap_rotation_and_final_repeats_do_not_change_run_index():
    state = CampaignCycleState.bootstrap([1001, 1002, 1003])
    final = enter_final_stage(state)
    repeated = record_final_repeat(final)

    assert final.final_stage_active is True
    assert final.next_bootstrap_chara_id == 0
    assert repeated.run_index == 0
    assert repeated.final_repeat_count == 1


def test_old_completed_stage_state_migrates_back_to_next_cyclic_member():
    migrated = migrate_stage_state_to_cycle(
        [1001, 1002, 1003],
        {
            "stage_index": 3,
            "produced": [[1001, "v1"], [1002, "v2"], [1003, "v3"]],
            "final_repeat_count": 0,
        },
    )

    assert migrated.final_stage_active is False
    assert migrated.run_index == 3
    assert migrated.next_bootstrap_chara_id == 1001
    assert migrated.produced == ((1001, "v1"), (1002, "v2"), (1003, "v3"))


def test_cycle_state_rejects_duplicate_bootstrap_characters():
    with pytest.raises(ValueError, match="unique"):
        CampaignCycleState.bootstrap([1001, 1001, 1003])


def test_bootstrap_rotation_cannot_advance_after_final_stage_begins():
    state = enter_final_stage(CampaignCycleState.bootstrap([1001, 1002, 1003]))

    with pytest.raises(ValueError, match="final stage"):
        advance_bootstrap_rotation(state, produced_legacy_id="v1")
