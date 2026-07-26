import copy

import pytest

from career_bot.independent_training.finalizer import (
    IndependentFinalizer,
    NeedsAttention,
)


FACTOR_MAP = {
    "2301": {"category": "aptitude", "name": "Dirt", "stars": 1},
    "2302": {"category": "aptitude", "name": "Dirt", "stars": 2},
}


def candidate(lottery_id, factor_ids):
    return {
        "lottery_id": lottery_id,
        "factor_info_array": [
            {"factor_id": factor_id, "level": 0} for factor_id in factor_ids
        ],
    }


def factor_response(candidates, *, lottery_count=1, remain=1):
    return {
        "data": {
            "single_mode_factor_select_common": {
                "factor_select_info_array": candidates,
                "lottery_count": lottery_count,
                "lottery_remain_num": remain,
            }
        }
    }


def finish_response(trained_chara_id=77):
    return {
        "data": {
            "single_mode_finish_common": {
                "trained_chara_id": trained_chara_id,
            },
            "trained_chara": [
                {
                    "trained_chara_id": trained_chara_id,
                    "card_id": 1001,
                    "rank": 7,
                }
            ],
        }
    }


def collected_run(*, reroll=True, targets=None, current_tp=60):
    return {
        "run_id": "run-1",
        "version": 1,
        "setup": {
            "running_style": 1,
            "priority_skill_array": [
                {"priority": 1, "skill_id": 100011},
            ],
            "factor_reroll": {
                "enabled": reroll,
                "targets": targets
                if targets is not None
                else [
                    {
                        "category": "pink",
                        "name": "dirt",
                        "minimum_stars": 2,
                    }
                ],
            },
        },
        "finalization": {
            "chara_info": {
                "turn": 78,
                "skill_point": 500,
                "speed": 1100,
                "stamina": 700,
                "power": 900,
                "guts": 500,
                "wiz": 800,
                "skill_array": [],
                "skill_tips_array": [],
            },
            "tp_info": {
                "current_tp": current_tp,
                "max_tp": 100,
                "max_recovery_time": 0,
            },
        },
        "factor_lottery_attempted": False,
        "factor_candidates": [],
        "selected_lottery_id": None,
        "finish_attempted": False,
        "result": {},
    }


class FakeStore:
    def __init__(self, run):
        self.run = copy.deepcopy(run)
        self.calls = []

    def _update(self):
        self.run["version"] += 1
        return copy.deepcopy(self.run)

    def update_finalization(self, run_id, expected_version, progress):
        assert expected_version == self.run["version"]
        self.calls.append("update_finalization")
        self.run["finalization"].update(copy.deepcopy(progress))
        return self._update()

    def save_factor_candidates(
        self,
        run_id,
        expected_version,
        candidates,
        selected_lottery_id=None,
    ):
        assert expected_version == self.run["version"]
        self.calls.append("save_factor_candidates")
        self.run["factor_candidates"] = copy.deepcopy(candidates)
        if selected_lottery_id is not None:
            self.run["selected_lottery_id"] = selected_lottery_id
        return self._update()

    def mark_factor_lottery_attempted(self, run_id, expected_version):
        assert expected_version == self.run["version"]
        self.calls.append("mark_factor_lottery_attempted")
        self.run["factor_lottery_attempted"] = True
        return self._update()

    def mark_finish_attempted(self, run_id, expected_version):
        assert expected_version == self.run["version"]
        self.calls.append("mark_finish_attempted")
        self.run["finish_attempted"] = True
        return self._update()

    def save_result(self, run_id, expected_version, result):
        assert expected_version == self.run["version"]
        self.calls.append("save_result")
        self.run["result"] = copy.deepcopy(result)
        return self._update()


class FakeBuyer:
    def __init__(self):
        self.calls = []

    def final_purchase(
        self,
        client,
        state,
        *,
        priority_skill_ids,
        running_style,
    ):
        self.calls.append((priority_skill_ids, running_style))
        return state, 0


class FakeClient:
    def __init__(self, store):
        self.store = store
        self.factor_select_result = factor_response([candidate(1, [2301])])
        self.factor_lottery_result = factor_response(
            [candidate(1, [2301]), candidate(2, [2302])]
        )
        self.finish_result = finish_response()
        self.lottery_calls = 0
        self.finish_calls = []
        self.raise_lottery = False
        self.raise_finish = False

    def select_independent_factors(self, current_turn):
        return self.factor_select_result

    def reroll_independent_factors(self, lottery_count, tp_info, use_tp=30):
        assert self.store.run["factor_lottery_attempted"] is True
        self.lottery_calls += 1
        if self.raise_lottery:
            raise RuntimeError("connection lost after factor lottery")
        return self.factor_lottery_result

    def finish_independent_training(self, current_turn, factor_lottery_id):
        assert self.store.run["finish_attempted"] is True
        self.finish_calls.append((current_turn, factor_lottery_id))
        if self.raise_finish:
            raise RuntimeError("connection lost after finish")
        return self.finish_result


def build_finalizer(run):
    store = FakeStore(run)
    client = FakeClient(store)
    buyer = FakeBuyer()
    finalizer = IndependentFinalizer(
        store=store,
        client=client,
        skill_buyer=buyer,
        factor_map=FACTOR_MAP,
    )
    return finalizer, store, client, buyer


def test_disabled_reroll_skips_lottery_and_finishes():
    finalizer, store, client, _ = build_finalizer(
        collected_run(reroll=False, targets=[])
    )

    result = finalizer.run(store.run)

    assert client.lottery_calls == 0
    assert result["selected_lottery_id"] == 1
    assert result["trained_chara_id"] == 77


def test_initial_target_hit_skips_lottery():
    finalizer, store, client, _ = build_finalizer(collected_run())
    client.factor_select_result = factor_response([candidate(1, [2302])])

    finalizer.run(store.run)

    assert client.lottery_calls == 0
    assert store.run["selected_lottery_id"] == 1


def test_dirt_miss_marks_once_then_chooses_best_candidate():
    finalizer, store, client, _ = build_finalizer(collected_run())

    result = finalizer.run(store.run)

    assert store.calls.index(
        "mark_factor_lottery_attempted"
    ) < store.calls.index("save_factor_candidates")
    assert client.lottery_calls == 1
    assert result["selected_lottery_id"] == 2
    assert client.finish_calls == [(result["current_turn"], 2)]


def test_best_of_two_can_keep_original():
    finalizer, store, client, _ = build_finalizer(collected_run())
    client.factor_select_result = factor_response([candidate(1, [2301])])
    client.factor_lottery_result = factor_response(
        [candidate(1, [2301]), candidate(2, [2301])]
    )

    result = finalizer.run(store.run)

    assert result["selected_lottery_id"] == 1


@pytest.mark.parametrize(
    ("current_tp", "remain", "reason"),
    [(29, 1, "insufficient_tp"), (60, 0, "no_lottery_remaining")],
)
def test_known_lottery_limits_skip_and_keep_original(
    current_tp,
    remain,
    reason,
):
    finalizer, store, client, _ = build_finalizer(
        collected_run(current_tp=current_tp)
    )
    client.factor_select_result = factor_response(
        [candidate(1, [2301])],
        remain=remain,
    )

    result = finalizer.run(store.run)

    assert client.lottery_calls == 0
    assert result["selected_lottery_id"] == 1
    assert store.run["finalization"]["factor_lottery_skip"] == reason


def test_persisted_lottery_attempt_is_never_retried():
    run = collected_run()
    run["factor_lottery_attempted"] = True
    finalizer, store, client, _ = build_finalizer(run)

    with pytest.raises(NeedsAttention, match="factor lottery"):
        finalizer.run(store.run)

    assert client.lottery_calls == 0


def test_finish_marker_is_stored_before_finish():
    finalizer, store, client, _ = build_finalizer(
        collected_run(reroll=False, targets=[])
    )

    finalizer.run(store.run)

    assert "mark_finish_attempted" in store.calls
    assert client.finish_calls == [(78, 1)]


@pytest.mark.parametrize("phase", ["lottery", "finish"])
def test_ambiguous_mutation_requires_attention(phase):
    finalizer, store, client, _ = build_finalizer(collected_run())
    if phase == "lottery":
        client.raise_lottery = True
    else:
        client.factor_select_result = factor_response([candidate(1, [2302])])
        client.raise_finish = True

    with pytest.raises(NeedsAttention, match=phase):
        finalizer.run(store.run)

    if phase == "lottery":
        assert store.run["factor_lottery_attempted"] is True
        assert client.lottery_calls == 1
    else:
        assert store.run["finish_attempted"] is True
        assert len(client.finish_calls) == 1
