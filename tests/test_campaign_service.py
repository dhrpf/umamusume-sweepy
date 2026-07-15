from __future__ import annotations

from copy import deepcopy

import pytest

from career_bot.campaigns.models import ParentCampaignSpec
from career_bot.campaigns.service import CampaignService


def valid_spec(**overrides):
    payload = {
        "account": "acct01",
        "goal": {
            "purpose": "parent",
            "target_factors": [
                {"name": "stamina", "minimum_stars": 2, "scope": "lineage"}
            ],
        },
        "strategy": {
            "preset_name": "parent",
            "maximum_runs": 20,
            "maximum_runtime_hours": 4,
        },
        "final_uma": {"card_id": 100101},
        "spark_targets": [
            {"category": "blue", "name": "stamina", "minimum_stars": 9}
        ],
        "loop_members": [
            {"chara_id": 1, "deck_id": 1},
            {"chara_id": 2, "deck_id": 2},
            {"chara_id": 3, "deck_id": 3},
            {"chara_id": 4, "deck_id": 4},
        ],
        "options": {"allow_rental": False, "auto_use_best_veteran": False},
    }
    payload.update(overrides)
    return payload


class FakeStore:
    def __init__(self, campaign=None):
        self.campaign = campaign or {
            "campaign_id": "cmp1",
            "account": "acct01",
            "state": "SELECTING_LINEAGE",
            "spec": valid_spec(),
            "context": {},
        }
        self.calls = []
        self.candidates = []

    def create(self, spec):
        self.calls.append(("create", spec))
        return {**self.campaign, "spec": spec.model_dump(mode="json")}

    def list(self, *, account=None, limit=100):
        self.calls.append(("list", account, limit))
        return [self.campaign]

    def get(self, campaign_id):
        self.calls.append(("get", campaign_id))
        return deepcopy(self.campaign)

    def update_context(self, campaign_id, context, **kwargs):
        self.calls.append(("update_context", campaign_id, deepcopy(context), kwargs))
        self.campaign.setdefault("context", {}).update(deepcopy(context))
        return deepcopy(self.campaign)

    def set_next_action(self, campaign_id, next_action, **kwargs):
        self.calls.append(("set_next_action", campaign_id, next_action, kwargs))
        self.campaign["next_action"] = next_action
        return deepcopy(self.campaign)

    def transition(self, campaign_id, state, **kwargs):
        value = getattr(state, "value", state)
        self.calls.append(("transition", campaign_id, value, kwargs))
        self.campaign["state"] = value
        self.campaign.update(kwargs)
        return deepcopy(self.campaign)

    def add_candidate(self, campaign_id, **kwargs):
        row = {"candidate_id": f"candidate-{len(self.candidates)+1}", **kwargs}
        self.calls.append(("add_candidate", campaign_id, kwargs))
        self.candidates.append(row)
        return row

    def list_candidates(self, campaign_id, *, limit=100):
        return deepcopy(self.candidates)


class FakeRunner:
    def __init__(self):
        self.calls = []

    def start(self, campaign_id, **kwargs):
        self.calls.append(("start", campaign_id, kwargs))
        return {"campaign_id": campaign_id}

    def require_user_input(self, campaign_id, next_action, review):
        self.calls.append(("require_user_input", campaign_id, next_action))
        return {"campaign_id": campaign_id, "next_action": next_action}

    def select_candidate(self, campaign_id, candidate_id):
        self.calls.append(("select_candidate", campaign_id, candidate_id))
        return {"candidate_id": candidate_id}

    def continue_for_preferred(self, campaign_id):
        self.calls.append(("continue_for_preferred", campaign_id))
        return {"campaign_id": campaign_id}

    def pause(self, campaign_id):
        self.calls.append(("pause", campaign_id))
        return {"state": "PAUSED"}

    def resume(self, campaign_id):
        self.calls.append(("resume", campaign_id))
        return {"state": "SELECTING_LINEAGE"}

    def cancel(self, campaign_id, *, reason=""):
        self.calls.append(("cancel", campaign_id, reason))
        return {"state": "CANCELLED"}


def service(store=None, runner=None, *, start_career=None, snapshot=None):
    store = store or FakeStore()
    runner = runner or FakeRunner()
    started = []
    svc = CampaignService(
        store=store,
        runner=runner,
        preset_store=object(),
        runtime_snapshot=snapshot or (lambda account: {"account": account}),
        affinity_for_setup=lambda *_args, **_kwargs: 150,
        start_career=start_career or (lambda request: started.append(request) or {"started": True}),
        planned_slots=lambda campaign, rotation, runtime: [
            {"role": "parent1", "mode": "FLEXIBLE", "trained_chara_id": 10}
        ],
        candidate_pool=lambda campaign, rotation, runtime: [
            {"trained_chara_id": 11, "score": 20, "rental": False}
        ],
        race_overrides=lambda campaign, rotation, runtime: [101, 202],
        career_request=lambda campaign, rotation, resolved, races, runtime: {
            "campaign_id": campaign["campaign_id"],
            "trainee_chara_id": rotation.next_trainee_chara_id,
            "parents": resolved,
            "race_overrides": races,
        },
    )
    return svc, store, runner, started


@pytest.mark.parametrize(
    "change,match",
    [
        ({"final_uma": {"card_id": 0}}, "final_uma.card_id"),
        ({"spark_targets": [{"category": "blue", "name": "speed", "minimum_stars": 3, "priority": "preferred"}]}, "required spark"),
        ({"loop_members": valid_spec()["loop_members"][:3]}, "exactly four"),
        ({"loop_members": [{"chara_id": 1, "deck_id": 0}, {"chara_id": 2, "deck_id": 2}, {"chara_id": 3, "deck_id": 3}, {"chara_id": 4, "deck_id": 4}]}, "deck_id"),
    ],
)
def test_create_campaign_enforces_web_workflow(change, match):
    svc, *_ = service()
    with pytest.raises(ValueError, match=match):
        svc.create_campaign(valid_spec(**change))


def test_create_list_get_and_recommend_delegate():
    planner_calls = []
    svc, store, *_ = service()
    svc.planner_factory = lambda request: type("Planner", (), {
        "recommend_final_parents": lambda self, **kwargs: planner_calls.append(("parents", kwargs)) or [1],
        "recommend_loops": lambda self, **kwargs: planner_calls.append(("loops", kwargs)) or {"loops": [2]},
    })()
    created = svc.create_campaign(valid_spec())
    assert ParentCampaignSpec.model_validate(created["spec"])
    assert svc.list_campaigns("acct01") == [store.campaign]
    assert svc.get_campaign("cmp1")["campaign_id"] == "cmp1"
    assert svc.recommend_final_parents({"limit": 2}) == [1]
    assert svc.recommend_loops({"limit": 3}) == {"loops": [2]}
    assert planner_calls == [("parents", {"limit": 2}), ("loops", {"limit": 3})]


def test_prepare_defaults_to_review_and_persists_before_return():
    svc, store, runner, _ = service()
    result = svc.prepare_next_run("cmp1")
    context = store.campaign["context"]
    assert context["rotation"]["run_index"] == 0
    assert context["prepared_run"] == result["prepared_run"]
    assert context["pending_review"] is True
    assert runner.calls[-1] == ("require_user_input", "cmp1", "approve_run")


def test_activate_uses_fresh_snapshot_and_runner_start():
    snapshots = []
    svc, _, runner, _ = service(
        snapshot=lambda account: snapshots.append(account) or {
            "runtime": {"api_reachable": True},
            "bot_state": {"session": {"logged_in": True}},
        }
    )
    svc.activate("cmp1")
    assert snapshots == ["acct01"]
    assert runner.calls == [
        (
            "start",
            "cmp1",
            {
                "runtime": {"api_reachable": True},
                "bot_state": {"session": {"logged_in": True}},
            },
        )
    ]


def test_prepare_auto_mode_skips_review_and_audits_replacement():
    campaign = {"campaign_id": "cmp1", "account": "acct01", "state": "SELECTING_LINEAGE", "spec": valid_spec(options={"allow_rental": False, "auto_use_best_veteran": True}), "context": {}}
    svc, store, runner, _ = service(FakeStore(campaign))
    result = svc.prepare_next_run("cmp1")
    assert result["campaign"]["next_action"] == "start_career"
    assert store.campaign["context"]["pending_review"] is False
    assert store.campaign["context"]["audit_events"][0]["event"] == "legacy_replaced"
    assert not any(call[0] == "require_user_input" for call in runner.calls)


def test_approve_delegates_one_persisted_request_exactly_once():
    svc, store, _, started = service()
    svc.prepare_next_run("cmp1")
    first = svc.approve_run("cmp1", {"race_overrides": [303]})
    second = svc.approve_run("cmp1")
    assert first == {"started": True}
    assert second == first
    assert len(started) == 1
    assert started[0]["race_overrides"] == [303]


def completed_candidate(affinity=150, required=9, preferred=0):
    return {
        "trained_chara_id": 501,
        "name": "Veteran",
        "spark_totals": {("blue", "stamina"): required, ("pink", "long"): preferred},
    }, [{"key": "pair", "affinity": affinity, "rental": False}]


def test_required_targets_and_affinity_exactly_150_complete():
    svc, store, *_ = service()
    candidate, _ = completed_candidate()
    pairings = [{"key": "pair", "rental": False}]
    result = svc.record_completed_veteran("cmp1", candidate, pairings)
    assert result["final_setup"]["status"] == "READY"
    assert store.campaign["state"] == "COMPLETED"


def test_rental_disabled_does_not_complete():
    svc, store, *_ = service()
    candidate, _ = completed_candidate()
    result = svc.record_completed_veteran("cmp1", candidate, [{"affinity": 180, "rental": True}])
    assert result["final_setup"]["status"] == "IN_PROGRESS"
    assert store.campaign["state"] == "SELECTING_LINEAGE"


def test_dominated_result_rejected_and_rotation_advances():
    svc, store, *_ = service()
    store.candidates.append({"candidate_id": "old", "score": 1, "evaluation": {"required_progress": 1, "preferred_progress": 1, "best_affinity": 149}})
    candidate, pairings = completed_candidate(affinity=100, required=8)
    result = svc.record_completed_veteran("cmp1", candidate, pairings)
    assert result["decision"] == "reject"
    assert store.campaign["context"]["rotation"]["run_index"] == 1
    assert store.campaign["state"] == "SELECTING_LINEAGE"


def test_meaningful_tradeoff_requests_candidate_review():
    svc, store, runner, _ = service()
    store.candidates.append({"candidate_id": "old", "score": 1, "evaluation": {"required_progress": .5, "preferred_progress": 1, "best_affinity": 170}})
    candidate, pairings = completed_candidate(affinity=140, required=9)
    result = svc.record_completed_veteran("cmp1", candidate, pairings)
    assert result["decision"] == "tradeoff"
    assert runner.calls[-1] == ("require_user_input", "cmp1", "select_candidate")


def test_simple_runner_delegations():
    svc, _, runner, _ = service()
    assert svc.select_candidate("cmp1", "candidate-1") == {"candidate_id": "candidate-1"}
    assert svc.continue_for_preferred("cmp1") == {"campaign_id": "cmp1"}
    assert svc.pause("cmp1") == {"state": "PAUSED"}
    assert svc.resume("cmp1") == {"state": "SELECTING_LINEAGE"}
    assert svc.cancel("cmp1", "done") == {"state": "CANCELLED"}
    assert runner.calls[-5:] == [
        ("select_candidate", "cmp1", "candidate-1"),
        ("continue_for_preferred", "cmp1"),
        ("pause", "cmp1"),
        ("resume", "cmp1"),
        ("cancel", "cmp1", "done"),
    ]
