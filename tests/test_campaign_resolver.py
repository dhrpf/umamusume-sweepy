from copy import deepcopy
from itertools import permutations

import pytest

from career_bot.campaigns.resolver import LegacyResolver, LegacySlot


def test_locked_slot_keeps_specific_campaign_legacy():
    resolver = LegacyResolver(allow_rental=False)

    result = resolver.resolve_slot(
        LegacySlot(role="parent1", mode="LOCKED", trained_chara_id=41),
        candidates=[
            {"trained_chara_id": 41, "score": 10, "rental": False},
            {"trained_chara_id": 99, "score": 999, "rental": False},
        ],
    )

    assert result["trained_chara_id"] == 41
    assert result["replacement"] is False
    assert result["reason"] == "locked campaign lineage"


def test_locked_slot_is_unresolved_when_veteran_is_unavailable():
    resolver = LegacyResolver(allow_rental=False)

    result = resolver.resolve_slot(
        LegacySlot(role="parent1", mode="LOCKED", trained_chara_id=41),
        candidates=[{"trained_chara_id": 99, "score": 999, "rental": False}],
    )

    assert result == {
        "status": "UNRESOLVED",
        "role": "parent1",
        "reason": "locked veteran unavailable",
    }


def test_flexible_slot_uses_better_owned_candidate():
    resolver = LegacyResolver(allow_rental=False)

    result = resolver.resolve_slot(
        LegacySlot(role="parent1", mode="FLEXIBLE", trained_chara_id=41),
        candidates=[
            {"trained_chara_id": 41, "score": 10, "rental": False},
            {"trained_chara_id": 99, "score": 20, "rental": False},
        ],
    )

    assert result["trained_chara_id"] == 99
    assert result["replacement"] is True
    assert result["previous_trained_chara_id"] == 41
    assert result["reason"] == "highest deterministic resolver score"


def test_rental_candidate_is_filtered_when_disabled():
    resolver = LegacyResolver(allow_rental=False)

    result = resolver.resolve_slot(
        LegacySlot(role="parent2", mode="FLEXIBLE"),
        candidates=[{"trained_chara_id": 9, "score": 100, "rental": True}],
    )

    assert result == {
        "status": "UNRESOLVED",
        "role": "parent2",
        "reason": "no allowed veteran candidate",
    }


def test_flexible_slot_breaks_score_ties_by_trained_chara_id():
    resolver = LegacyResolver(allow_rental=False)

    result = resolver.resolve_slot(
        LegacySlot(role="parent1", mode="FLEXIBLE"),
        candidates=[
            {"trained_chara_id": 99, "score": 20, "rental": False},
            {"trained_chara_id": 41, "score": 20, "rental": False},
        ],
    )

    assert result["trained_chara_id"] == 41


def test_flexible_slot_does_not_mark_same_candidate_as_replacement():
    resolver = LegacyResolver(allow_rental=False)

    result = resolver.resolve_slot(
        LegacySlot(role="parent1", mode="FLEXIBLE", trained_chara_id=41),
        candidates=[{"trained_chara_id": 41, "score": 20, "rental": False}],
    )

    assert result["replacement"] is False
    assert result["previous_trained_chara_id"] == 41


def test_rental_candidate_is_allowed_when_enabled():
    resolver = LegacyResolver(allow_rental=True)

    result = resolver.resolve_slot(
        LegacySlot(role="parent2", mode="FLEXIBLE"),
        candidates=[{"trained_chara_id": 9, "score": 100, "rental": True}],
    )

    assert result["status"] == "RESOLVED"
    assert result["trained_chara_id"] == 9
    assert result["rental"] is True


def test_invalid_slot_mode_is_rejected():
    with pytest.raises(ValueError, match="mode must be LOCKED or FLEXIBLE"):
        LegacySlot(role="parent1", mode="AUTOMATIC")


@pytest.mark.parametrize("trained_chara_id", [0, -1, True, "41"])
def test_locked_slot_requires_positive_integer_trained_chara_id(trained_chara_id):
    with pytest.raises(
        ValueError,
        match="LOCKED trained_chara_id must be a positive integer",
    ):
        LegacySlot(
            role="parent1",
            mode="LOCKED",
            trained_chara_id=trained_chara_id,
        )


@pytest.mark.parametrize("trained_chara_id", [None, 0, -1, True, "41"])
def test_candidate_requires_positive_integer_trained_chara_id(trained_chara_id):
    resolver = LegacyResolver(allow_rental=False)
    candidate = {"score": 10, "rental": False}
    if trained_chara_id is not None:
        candidate["trained_chara_id"] = trained_chara_id

    with pytest.raises(
        ValueError,
        match="candidate trained_chara_id must be a positive integer",
    ):
        resolver.resolve_slot(
            LegacySlot(role="parent1", mode="FLEXIBLE"),
            candidates=[candidate],
        )


@pytest.mark.parametrize(
    "score",
    [None, True, "10", float("nan"), float("inf"), -float("inf")],
)
def test_candidate_requires_finite_non_bool_numeric_score(score):
    resolver = LegacyResolver(allow_rental=False)
    candidate = {"trained_chara_id": 41, "rental": False}
    if score is not None:
        candidate["score"] = score

    with pytest.raises(ValueError, match="candidate score must be finite numeric"):
        resolver.resolve_slot(
            LegacySlot(role="parent1", mode="FLEXIBLE"),
            candidates=[candidate],
        )


@pytest.mark.parametrize("allow_rental", [0, 1, "false", None])
def test_allow_rental_requires_boolean(allow_rental):
    with pytest.raises(TypeError, match="allow_rental must be a boolean"):
        LegacyResolver(allow_rental=allow_rental)


@pytest.mark.parametrize("rental", [0, 1, "false", None])
def test_candidate_rental_requires_explicit_boolean(rental):
    resolver = LegacyResolver(allow_rental=False)
    candidate = {"trained_chara_id": 41, "score": 10}
    if rental is not None:
        candidate["rental"] = rental

    with pytest.raises(
        ValueError,
        match="candidate rental must be an explicit boolean",
    ):
        resolver.resolve_slot(
            LegacySlot(role="parent1", mode="FLEXIBLE"),
            candidates=[candidate],
        )


def test_duplicate_sort_keys_are_rejected_for_every_input_permutation():
    resolver = LegacyResolver(allow_rental=True)
    candidates = [
        {"trained_chara_id": 41, "score": 20, "rental": False, "name": "A"},
        {"trained_chara_id": 41, "score": 20, "rental": True, "name": "B"},
    ]

    for ordered in permutations(candidates):
        with pytest.raises(ValueError, match="duplicate candidate sort key"):
            resolver.resolve_slot(
                LegacySlot(role="parent1", mode="FLEXIBLE"),
                candidates=list(ordered),
            )


def test_resolver_does_not_mutate_candidates():
    resolver = LegacyResolver(allow_rental=False)
    candidates = [
        {
            "trained_chara_id": 41,
            "score": 20,
            "rental": False,
            "metadata": {"factors": [1, 2]},
        }
    ]
    original = deepcopy(candidates)

    resolver.resolve_slot(
        LegacySlot(role="parent1", mode="FLEXIBLE", trained_chara_id=41),
        candidates=candidates,
    )

    assert candidates == original


def test_locked_rental_candidate_is_filtered_when_disabled():
    resolver = LegacyResolver(allow_rental=False)

    result = resolver.resolve_slot(
        LegacySlot(role="parent1", mode="LOCKED", trained_chara_id=41),
        candidates=[{"trained_chara_id": 41, "score": 20, "rental": True}],
    )

    assert result == {
        "status": "UNRESOLVED",
        "role": "parent1",
        "reason": "locked veteran unavailable",
    }
