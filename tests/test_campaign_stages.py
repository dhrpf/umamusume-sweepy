import pytest

from career_bot.campaigns.stages import (
    CampaignStageState,
    build_stage_goal_assignments,
    migrate_legacy_rotation,
    record_stage_result,
)


def test_stage_state_runs_bootstraps_then_final():
    state = CampaignStageState.bootstrap([1001, 1002, 1003])

    assert state.stage_index == 0
    assert state.current_bootstrap_chara_id == 1001
    assert state.is_final_stage is False

    state = record_stage_result(state, produced_legacy_id="v1", goal_complete=True)
    assert state.stage_index == 1
    assert state.current_bootstrap_chara_id == 1002

    state = record_stage_result(state, produced_legacy_id="v2", goal_complete=True)
    state = record_stage_result(state, produced_legacy_id="v3", goal_complete=True)
    assert state.stage_index == 3
    assert state.is_final_stage is True
    assert state.current_bootstrap_chara_id == 0
    assert state.completed_bootstrap_stages == (0, 1, 2)


def test_incomplete_bootstrap_goal_repeats_same_stage():
    state = CampaignStageState.bootstrap([1001, 1002, 1003])

    repeated = record_stage_result(state, produced_legacy_id="v1", goal_complete=False)

    assert repeated.stage_index == 0
    assert repeated.completed_bootstrap_stages == ()
    assert repeated.produced == ((1001, "v1"),)


def test_final_stage_repeats_without_advancing():
    state = CampaignStageState(
        bootstrap_chara_ids=(1001, 1002, 1003),
        stage_index=3,
        completed_bootstrap_stages=(0, 1, 2),
        final_repeat_count=0,
        produced=(),
    )

    repeated = record_stage_result(state, produced_legacy_id="final-1", goal_complete=False)
    completed = record_stage_result(repeated, produced_legacy_id="final-2", goal_complete=True)

    assert repeated.stage_index == 3
    assert repeated.final_repeat_count == 1
    assert completed.stage_index == 3
    assert completed.final_repeat_count == 2


def test_completed_bootstrap_stage_never_reopens():
    state = CampaignStageState(
        bootstrap_chara_ids=(1001, 1002, 1003),
        stage_index=1,
        completed_bootstrap_stages=(0,),
        final_repeat_count=0,
        produced=((1001, "v1"),),
    )

    advanced = record_stage_result(state, produced_legacy_id="v2", goal_complete=True)

    assert advanced.completed_bootstrap_stages == (0, 1)
    assert advanced.stage_index == 2


def test_stage_goal_assignments_distribute_targets_deterministically():
    targets = [
        {"category": "blue", "name": "speed", "minimum_stars": 3},
        {"category": "blue", "name": "stamina", "minimum_stars": 3},
        {"category": "pink", "name": "mile", "minimum_stars": 2},
        {"category": "blue", "name": "power", "minimum_stars": 3},
    ]

    assigned = build_stage_goal_assignments(targets, bootstrap_count=3)

    assert assigned == {
        "0": [targets[0], targets[3]],
        "1": [targets[1]],
        "2": [targets[2]],
    }


def test_empty_target_list_still_creates_all_bootstrap_assignments():
    assert build_stage_goal_assignments([], bootstrap_count=3) == {
        "0": [],
        "1": [],
        "2": [],
    }


def test_legacy_rotation_migration_preserves_next_trainee_and_all_members():
    migrated = migrate_legacy_rotation(
        [1001, 1002, 1003, 1004],
        {
            "loop_chara_ids": [1001, 1002, 1003, 1004],
            "run_index": 2,
            "produced": [[1001, "a"], [1002, "b"]],
        },
    )

    assert migrated.bootstrap_chara_ids == (1003, 1004, 1001, 1002)
    assert migrated.stage_index == 0
    assert migrated.completed_bootstrap_stages == ()
    assert migrated.produced == ((1001, "a"), (1002, "b"))


def test_stage_state_rejects_duplicate_bootstrap_characters():
    with pytest.raises(ValueError, match="unique"):
        CampaignStageState.bootstrap([1001, 1001, 1003])
