import pytest

from career_bot.campaigns.rotation import RotationState, advance_rotation


def test_completed_trainee_enters_future_lineage_inventory():
    state = RotationState.bootstrap([1001, 1002, 1003, 1004])

    next_state = advance_rotation(state, produced_legacy_id="legacy-a")

    assert next_state.run_index == 1
    assert next_state.next_trainee_chara_id == 1002
    assert next_state.produced == ((1001, "legacy-a"),)
    assert next_state.available_legacy_ids == ["legacy-a"]


def test_twenty_rotations_cycle_exactly_four_trainees():
    state = RotationState.bootstrap([1001, 1002, 1003, 1004])
    seen = []

    for index in range(20):
        seen.append(state.next_trainee_chara_id)
        state = advance_rotation(state, produced_legacy_id=f"legacy-{index}")

    assert seen == [1001, 1002, 1003, 1004] * 5


@pytest.mark.parametrize(
    "chara_ids",
    [
        [1001, 1002, 1003],
        [1001, 1002, 1003, 1004, 1005],
        [1001, 1002, 1003, 1003],
    ],
)
def test_bootstrap_rejects_invalid_character_pool(chara_ids):
    with pytest.raises(ValueError, match="four unique characters"):
        RotationState.bootstrap(chara_ids)


def test_produced_inventory_retains_only_latest_eight_entries():
    state = RotationState.bootstrap([1001, 1002, 1003, 1004])

    for index in range(10):
        state = advance_rotation(state, produced_legacy_id=f"legacy-{index}")

    assert state.produced == (
        (1003, "legacy-2"),
        (1004, "legacy-3"),
        (1001, "legacy-4"),
        (1002, "legacy-5"),
        (1003, "legacy-6"),
        (1004, "legacy-7"),
        (1001, "legacy-8"),
        (1002, "legacy-9"),
    )
    assert state.available_legacy_ids == [f"legacy-{index}" for index in range(2, 10)]


def test_rotation_state_is_immutable_and_serializable():
    state = advance_rotation(
        RotationState.bootstrap([1001, 1002, 1003, 1004]),
        produced_legacy_id="legacy-a",
    )

    with pytest.raises(AttributeError):
        state.run_index = 2

    assert state.to_dict() == {
        "loop_chara_ids": (1001, 1002, 1003, 1004),
        "run_index": 1,
        "produced": ((1001, "legacy-a"),),
    }
