from copy import deepcopy

import pytest
from pydantic import ValidationError

from career_bot.independent_training.models import (
    EnqueueRuns,
    FactorReroll,
    IndependentTrainingPreset,
    IndependentSetup,
    RunState,
)


def setup_payload():
    return {
        "card_id": 100101,
        "support_card_ids": [30001, 30002, 30003, 30004, 30005],
        "friend_viewer_id": 70001,
        "friend_card_id": 30006,
        "parent_id_1": 101,
        "parent_id_2": 202,
        "rental_viewer_id": 0,
        "rental_trained_chara_id": 0,
        "scenario_id": 3,
        "deck_id": 1,
        "running_style": 1,
        "difficulty_id": 0,
        "difficulty": 0,
        "is_boost": 0,
        "boost_story_event_id": 0,
        "training_policy_ground_type": 1,
        "training_policy_param_rate_set_id": 1,
        "priority_skill_array": [
            {"priority": 1, "skill_id": 100011},
            {"priority": 2, "skill_id": 100021},
        ],
        "race_array": [{"year": 2, "program_id": 301}],
        "factor_reroll": {
            "enabled": True,
            "targets": [
                {"category": "aptitude", "name": " Dirt ", "minimum_stars": 2}
            ],
        },
    }


def test_setup_normalizes_factor_target_and_forbids_unknown_keys():
    payload = setup_payload()
    payload["surprise"] = True
    with pytest.raises(ValidationError, match="surprise"):
        IndependentSetup.model_validate(payload)

    payload.pop("surprise")
    setup = IndependentSetup.model_validate(payload)
    assert setup.factor_reroll.targets[0].category == "pink"
    assert setup.factor_reroll.targets[0].name == "dirt"


def test_setup_accepts_only_named_independent_training_styles():
    payload = setup_payload()
    for style_id in (1, 2, 3):
        payload["training_policy_param_rate_set_id"] = style_id
        assert (
            IndependentSetup.model_validate(payload)
            .training_policy_param_rate_set_id
            == style_id
        )

    for style_id in (0, 4, 99):
        payload["training_policy_param_rate_set_id"] = style_id
        with pytest.raises(ValidationError):
            IndependentSetup.model_validate(payload)


def test_setup_keeps_final_skill_purchase_separate_from_training_priority():
    payload = setup_payload()
    payload["final_skill_ids"] = [100031, 100041]

    setup = IndependentSetup.model_validate(payload)

    assert setup.priority_skill_array[0].skill_id == 100011
    assert setup.final_skill_ids == [100031, 100041]


def test_setup_rejects_duplicate_final_skill_ids():
    payload = setup_payload()
    payload["final_skill_ids"] = [100031, 100031]

    with pytest.raises(ValidationError, match="final_skill_ids"):
        IndependentSetup.model_validate(payload)


def test_setup_rejects_client_controlled_tp_cost():
    payload = setup_payload()
    payload["use_tp"] = 15

    with pytest.raises(ValidationError, match="use_tp"):
        IndependentSetup.model_validate(payload)


def test_setup_requires_exactly_five_distinct_owned_supports():
    payload = setup_payload()
    payload["support_card_ids"] = [30001] * 5
    with pytest.raises(ValidationError, match="distinct"):
        IndependentSetup.model_validate(payload)


def test_enabled_reroll_requires_at_least_one_target():
    with pytest.raises(ValidationError, match="at least one target"):
        FactorReroll(enabled=True, targets=[])


def test_enqueue_count_and_tp_mode_are_strict():
    request = EnqueueRuns(setup=setup_payload(), count=3, tp_mode="wait")
    assert request.count == 3
    assert request.tp_mode.value == "wait"
    with pytest.raises(ValidationError):
        EnqueueRuns(setup=setup_payload(), count=101, tp_mode="wait")
    with pytest.raises(ValidationError):
        EnqueueRuns(setup=setup_payload(), count=1, tp_mode="invented")


def test_model_dump_is_an_immutable_queue_snapshot():
    payload = setup_payload()
    request = EnqueueRuns.model_validate(
        {"setup": payload, "count": 1, "tp_mode": "stop"}
    )
    snapshot = deepcopy(request.setup.model_dump(mode="json"))
    payload["race_array"][0]["program_id"] = 999
    assert snapshot["race_array"] == [{"year": 2, "program_id": 301}]
    assert RunState.QUEUED.value == "QUEUED"


def test_named_preset_keeps_complete_setup_and_queue_defaults():
    payload = setup_payload()
    payload["final_skill_ids"] = [100031, 100041]

    preset = IndependentTrainingPreset.model_validate({
        "name": "  Dirt sprint  ",
        "setup": payload,
        "count": 3,
        "tp_mode": "wait",
    })

    assert preset.name == "Dirt sprint"
    assert preset.count == 3
    assert preset.setup.final_skill_ids == [100031, 100041]
    assert preset.setup.race_array[0].program_id == 301


def test_named_preset_rejects_blank_names_and_unknown_fields():
    with pytest.raises(ValidationError, match="preset name"):
        IndependentTrainingPreset.model_validate({
            "name": " ",
            "setup": setup_payload(),
        })
    with pytest.raises(ValidationError, match="unexpected"):
        IndependentTrainingPreset.model_validate({
            "name": "Dirt sprint",
            "setup": setup_payload(),
            "unexpected": True,
        })
