import pytest

from career_bot.campaigns.resolver import LegacyResolver, LegacySlot


def test_locked_slot_keeps_specific_campaign_legacy():
    resolver = LegacyResolver(allow_rental=False)

    result = resolver.resolve_slot(
        LegacySlot(role="parent1", mode="LOCKED", trained_chara_id=41),
        candidates=[
            {"trained_chara_id": 41, "score": 10},
            {"trained_chara_id": 99, "score": 999},
        ],
    )

    assert result["trained_chara_id"] == 41
    assert result["replacement"] is False
    assert result["reason"] == "locked campaign lineage"


def test_locked_slot_is_unresolved_when_veteran_is_unavailable():
    resolver = LegacyResolver(allow_rental=False)

    result = resolver.resolve_slot(
        LegacySlot(role="parent1", mode="LOCKED", trained_chara_id=41),
        candidates=[{"trained_chara_id": 99, "score": 999}],
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
            {"trained_chara_id": 99, "score": 20},
            {"trained_chara_id": 41, "score": 20},
        ],
    )

    assert result["trained_chara_id"] == 41


def test_flexible_slot_does_not_mark_same_candidate_as_replacement():
    resolver = LegacyResolver(allow_rental=False)

    result = resolver.resolve_slot(
        LegacySlot(role="parent1", mode="FLEXIBLE", trained_chara_id=41),
        candidates=[{"trained_chara_id": 41, "score": 20}],
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
