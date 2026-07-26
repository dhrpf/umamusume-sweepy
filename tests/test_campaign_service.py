from __future__ import annotations

from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock

import pytest

from career_bot.campaigns.models import ParentCampaignSpec
from career_bot.campaigns.service import CampaignService
from career_bot.campaigns.rotation import RotationState
from career_bot.campaigns.runner import CampaignRunner
from career_bot.campaigns.store import CampaignStore


def valid_spec(**overrides):
    payload = {
        "account": "acct01",
        "spec_version": 2,
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


def valid_v3_spec(**overrides):
    payload = valid_spec(
        spec_version=3,
        final_uma={
            "card_id": 100401,
            "deck_id": 4,
            "friend_support": {
                "viewer_id": 904,
                "support_card_id": 30016,
                "support_name": "Final Support",
            },
        },
        loop_members=[
            {
                "chara_id": 1001,
                "deck_id": 1,
                "friend_support": {
                    "viewer_id": 901,
                    "support_card_id": 30011,
                    "support_name": "Bootstrap 1",
                },
            },
            {
                "chara_id": 1002,
                "deck_id": 2,
                "friend_support": {
                    "viewer_id": 902,
                    "support_card_id": 30012,
                    "support_name": "Bootstrap 2",
                },
            },
            {
                "chara_id": 1003,
                "deck_id": 3,
                "friend_support": {
                    "viewer_id": 903,
                    "support_card_id": 30013,
                    "support_name": "Bootstrap 3",
                },
            },
        ],
    )
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
        self.events = []
        self.lock = Lock()

    def create(self, spec, *, initial_context=None):
        self.calls.append(("create", spec, deepcopy(initial_context)))
        return {**self.campaign, "spec": spec.model_dump(mode="json"), "context": deepcopy(initial_context or {})}

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

    def recent_events(self, campaign_id, *, limit=100):
        return deepcopy(self.events[:limit])

    def get_candidate(self, campaign_id, candidate_id):
        return deepcopy(next(row for row in self.candidates if row["candidate_id"] == candidate_id))

    def append_event(self, campaign_id, event_type, data=None):
        self.events.append({"event_type": event_type, "data": deepcopy(data or {})})

    def pause_for_runtime_mismatch(self, campaign_id, *, error, expected_version=None):
        self.append_event(campaign_id, "runtime_reconciliation_mismatch", {"error": error})
        return self.transition(
            campaign_id,
            "PAUSED",
            next_action="inspect_current_career",
            error=error,
            context_updates={"runtime_reconciliation": {"status": "MISMATCH"}},
        )

    def recover_missing_active_career(self, campaign_id, *, expected_version=None):
        run_start = (self.campaign.get("context") or {}).get("run_start") or {}
        if run_start.get("status") in {"STARTING", "STARTED"}:
            return {"recovered": False, "reason": "run_start_in_progress", "campaign": deepcopy(self.campaign)}
        self.campaign["state"] = "PAUSED"
        self.campaign["next_action"] = "review_missing_active_career"
        self.campaign["error"] = "Persisted running career is no longer active"
        self.campaign.setdefault("context", {}).setdefault("runtime_reconciliation", {})["status"] = "ACTIVE_CAREER_DISAPPEARED"
        self.append_event(campaign_id, "runtime_active_career_disappeared")
        return {"recovered": True, "reason": "", "campaign": deepcopy(self.campaign)}

    def reserve_prepared_run_start(self, campaign_id, operation_id, *, prepared_run=None):
        with self.lock:
            run_start = self.campaign.setdefault("context", {}).get("run_start")
            if run_start and run_start["status"] in {"STARTING", "STARTED"}:
                return {"acquired": False, "run_start": deepcopy(run_start)}
            run_start = {"operation_id": operation_id, "status": "STARTING"}
            self.campaign["context"]["run_start"] = run_start
            self.campaign["context"]["prepared_run"] = deepcopy(prepared_run)
            return {"acquired": True, "run_start": deepcopy(run_start)}

    def finish_prepared_run_start(self, campaign_id, operation_id, *, status, result=None, error=""):
        with self.lock:
            run_start = {
                "operation_id": operation_id,
                "status": status,
                "result": deepcopy(result),
                "error": error,
            }
            self.campaign.setdefault("context", {})["run_start"] = run_start
            return deepcopy(run_start)

    def persist_candidate_result(self, campaign_id, **kwargs):
        candidate_id = kwargs["candidate_id"]
        existing = next((row for row in self.candidates if row["candidate_id"] == candidate_id), None)
        if existing:
            return {"campaign": deepcopy(self.campaign), "candidate": deepcopy(existing), "replayed": True}
        row = {
            "candidate_id": candidate_id,
            "campaign_id": campaign_id,
            "trained_chara_id": kwargs["trained_chara_id"],
            "name": kwargs["name"],
            "score": kwargs["score"],
            "accepted": kwargs["evaluation"]["accepted"],
            "selected": kwargs["select"],
            "evaluation": deepcopy(kwargs["evaluation"]),
        }
        if kwargs["select"]:
            for old in self.candidates:
                old["selected"] = False
            self.campaign["selected_candidate_id"] = candidate_id
        self.candidates.append(row)
        self.campaign.setdefault("context", {}).update(deepcopy(kwargs.get("context_updates") or {}))
        self.campaign["state"] = getattr(kwargs["state"], "value", kwargs["state"])
        self.campaign["next_action"] = kwargs["next_action"]
        return {"campaign": deepcopy(self.campaign), "candidate": deepcopy(row), "replayed": False}

    def apply_candidate_selection(self, campaign_id, candidate_id, *, state, next_action, context_updates, allowed_candidate_ids=None):
        review = self.campaign.get("context", {}).get("pending_review")
        allowed = {str(value) for value in (allowed_candidate_ids or set())}
        allowed.update({
            str(review.get("candidate_id")) if isinstance(review, dict) and review.get("candidate_id") is not None else "",
            *(str(value) for value in ((review or {}).get("candidate_ids") or [])),
        })
        if not (
            self.campaign.get("state") == "NEEDS_USER_INPUT"
            and self.campaign.get("next_action") == "select_candidate"
            and isinstance(review, dict)
            and review.get("kind", review.get("type")) == "candidate_tradeoff"
            and candidate_id in allowed
        ):
            raise ValueError("campaign has no matching candidate selection review")
        row = next(row for row in self.candidates if row["candidate_id"] == candidate_id)
        for candidate in self.candidates:
            candidate["selected"] = candidate is row
        self.campaign["selected_candidate_id"] = candidate_id
        self.campaign["state"] = getattr(state, "value", state)
        self.campaign["next_action"] = next_action
        self.campaign.setdefault("context", {}).update(deepcopy(context_updates))
        return {"campaign": deepcopy(self.campaign), "candidate": deepcopy(row)}


class FakeRunner:
    def __init__(self):
        self.calls = []

    def start(self, campaign_id, **kwargs):
        self.calls.append(("start", campaign_id, kwargs))
        return {"campaign_id": campaign_id}

    def require_user_input(self, campaign_id, next_action, review):
        self.calls.append(("require_user_input", campaign_id, next_action))
        return {"campaign_id": campaign_id, "next_action": next_action}

    def begin_run(self, campaign_id):
        self.calls.append(("begin_run", campaign_id))
        return {"state": "RUNNING_CAREER"}

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


class FakePresetStore:
    def __init__(self):
        self.saved = []
        self.presets = {"parent": {"name": "parent", "running_style": 2, "scenario_id": 4, "expect_attribute": [900, 1200, 800, 700, 600], "support_card_ids": [1, 2, 3, 4, 5]}}

    def load(self, name):
        return deepcopy(self.presets[name])

    def save(self, preset):
        self.saved.append(deepcopy(preset))
        self.presets[preset["name"]] = deepcopy(preset)
        return deepcopy(preset)


def service(store=None, runner=None, *, start_career=None, snapshot=None, preset_store=None, default_career_request=False, projected_affinity=None, direct_compatibility=None):
    store = store or FakeStore()
    runner = runner or FakeRunner()
    started = []
    svc = CampaignService(
        store=store,
        runner=runner,
        preset_store=preset_store or FakePresetStore(),
        runtime_snapshot=snapshot or (lambda account: {"account": account}),
        affinity_for_setup=lambda *_args, **_kwargs: 150,
        projected_affinity_for_pair=projected_affinity,
        direct_compatibility_for_parent=direct_compatibility or (lambda _card_id, _chara_id: 15),
        start_career=start_career or (lambda request: started.append(request) or {"started": True}),
        planned_slots=lambda campaign, rotation, runtime: [
            {"role": "parent1", "mode": "FLEXIBLE", "trained_chara_id": 10}
        ],
        candidate_pool=lambda campaign, rotation, runtime: [
            {"trained_chara_id": 11, "score": 20, "rental": False}
        ],
        race_overrides=lambda campaign, rotation, runtime: [101, 202],
        career_request=None if default_career_request else lambda campaign, rotation, resolved, races, runtime: {
            "campaign_id": campaign["campaign_id"],
            "trainee_chara_id": rotation.next_trainee_chara_id,
            "parents": resolved,
            "race_overrides": races,
        },
    )
    return svc, store, runner, started

def real_running_service(tmp_path, *, prepared_run=None):
    store = CampaignStore(tmp_path / "campaigns.sqlite3")
    store.create(ParentCampaignSpec.model_validate(valid_spec()), campaign_id="cmp1")
    for state in ("READY", "STARTING_BOT", "SELECTING_LINEAGE", "RUNNING_CAREER"):
        store.transition("cmp1", state)
    if prepared_run is not None:
        store.update_context("cmp1", {"prepared_run": prepared_run})
    svc, _, runner, started = service(store=store)
    return svc, store, runner, started


@pytest.mark.parametrize(
    "change,match",
    [
        ({"final_uma": {"card_id": 0}}, "final_uma.card_id"),
        ({"spark_targets": [{"category": "blue", "name": "speed", "minimum_stars": 3, "priority": "preferred"}]}, "required spark"),
        ({"loop_members": valid_v3_spec()["loop_members"][:2]}, "exactly three"),
        ({"loop_members": [{"chara_id": 1, "deck_id": 0}, {"chara_id": 2, "deck_id": 2}, {"chara_id": 3, "deck_id": 3}]}, "deck_id"),
    ],
)
def test_create_campaign_enforces_web_workflow(change, match):
    svc, *_ = service()
    with pytest.raises(ValueError, match=match):
        svc.create_campaign(valid_v3_spec(**change))


@pytest.mark.parametrize(
    "change,match",
    [
        ({"final_uma": {"card_id": True}}, "final_uma.card_id"),
        ({"trainee": {"card_id": True}}, "trainee.card_id"),
        ({"deck": {"deck_id": True}}, "deck.deck_id"),
        ({"final_parent": {"chara_id": True}}, "final_parent.chara_id"),
        ({"final_parent": {"trained_chara_id": True}}, "final_parent.trained_chara_id"),
        ({"loop_members": [{"chara_id": True, "deck_id": 1}, {"chara_id": 2, "deck_id": 2}, {"chara_id": 3, "deck_id": 3}]}, "chara_id"),
        ({"loop_members": [{"chara_id": 1, "deck_id": True}, {"chara_id": 2, "deck_id": 2}, {"chara_id": 3, "deck_id": 3}]}, "deck_id"),
        ({"strategy": {**valid_spec()["strategy"], "maximum_runs": True}}, "maximum_runs"),
        ({"spark_targets": [{"category": "blue", "name": "stamina", "minimum_stars": True}]}, "minimum_stars"),
    ],
)
def test_create_rejects_boolean_integer_fields_before_pydantic(change, match):
    svc, *_ = service()
    with pytest.raises(ValueError, match=match):
        svc.create_campaign(valid_v3_spec(**change))


def test_create_campaign_rejects_bootstrap_loop_without_two_compatible_parents():
    scores = {1001: 9, 1002: 10, 1003: 17}
    svc, *_ = service(
        direct_compatibility=lambda _final_card_id, chara_id: scores[chara_id]
    )

    with pytest.raises(ValueError, match="two compatible bootstrap characters"):
        svc.create_campaign(valid_v3_spec())


def test_create_campaign_accepts_exact_direct_compatibility_threshold():
    scores = {1001: 15, 1002: 15, 1003: 0}
    svc, *_ = service(
        direct_compatibility=lambda _final_card_id, chara_id: scores[chara_id]
    )

    created = svc.create_campaign(valid_v3_spec())

    assert created["campaign_id"] == "cmp1"


def test_get_campaign_enriches_legacy_candidate_sparks_from_runtime_cache():
    store = FakeStore()
    store.candidates.append({
        "candidate_id": "legacy-candidate",
        "trained_chara_id": 501,
        "name": "Legacy Veteran",
        "score": 100,
        "selected": True,
        "evaluation": {"required_progress": 1, "preferred_progress": 0, "best_affinity": 150},
    })
    tree = {
        "self": {
            "factors": [
                {"factor_id": 303, "category": "stat", "name": "Stamina", "stars": 3}
            ]
        }
    }
    svc, *_ = service(
        store=store,
        snapshot=lambda _account: {"display_by_id": {501: {"tree": tree}}},
    )

    result = svc.get_campaign("cmp1")

    assert result["candidates"][0]["evaluation"]["factor_tree"] == tree
    assert "factor_tree" not in store.candidates[0]["evaluation"]


def test_create_list_get_and_recommend_delegate():
    planner_calls = []
    svc, store, *_ = service()
    svc.planner_factory = lambda request: type("Planner", (), {
        "recommend_final_parents": lambda self, **kwargs: planner_calls.append(("parents", kwargs)) or [1],
        "recommend_loops": lambda self, **kwargs: planner_calls.append(("loops", kwargs)) or {"loops": [2]},
        "recommend_bootstraps": lambda self, **kwargs: planner_calls.append(("bootstraps", kwargs)) or {"bootstraps": [3]},
    })()
    created = svc.create_campaign(valid_v3_spec())
    assert ParentCampaignSpec.model_validate(created["spec"])
    assert svc.list_campaigns("acct01") == [store.campaign]
    assert svc.get_campaign("cmp1")["campaign_id"] == "cmp1"
    assert svc.recommend_final_parents({"limit": 2}) == [1]
    assert svc.recommend_loops({"limit": 3, "final_parent_chara_id": 1004, "pinned_chara_ids": [1001]}) == {"loops": [2]}
    assert svc.recommend_bootstraps({"limit": 2, "pinned_chara_ids": [1001]}) == {"bootstraps": [3]}
    assert planner_calls == [
        ("parents", {"limit": 2}),
        ("loops", {"limit": 3, "pinned_chara_ids": {1001}, "final_parent_chara_id": 1004}),
        ("bootstraps", {"limit": 2, "pinned_chara_ids": {1001}}),
    ]


def test_v3_create_campaign_uses_cyclic_context():
    svc, _, *_ = service()

    created = svc.create_campaign(valid_v3_spec())
    context = created["context"]

    assert context["bootstrap_rotation"] == {
        "bootstrap_chara_ids": [1001, 1002, 1003],
        "run_index": 0,
        "final_stage_active": False,
        "final_repeat_count": 0,
        "produced": [],
    }
    assert context["ready_parent_candidates"] == []
    assert context["selected_ready_pair"] is None
    assert "stage_state" not in context
    assert "stage_goal_assignments" not in context
    assert "bootstrap_goal_state" not in context


def test_default_candidates_normalize_raw_runtime_rows_and_dedupe():
    campaign = {
        "context": {
            "campaign_candidates": [
                {"trained_chara_id": 11, "score": 99, "rental": False},
                {"trained_chara_id": 33, "rank": 7},
            ]
        }
    }
    runtime = {
        "owned_candidates": [
            {"trained_chara_id": 11, "rank_score": 12345},
            {"trained_chara_id": 22, "rank_score": 23456},
        ],
        "rental_candidates": [
            {"trained_chara_id": 44, "score": float("nan"), "rank_score": 34567},
        ],
    }

    result = CampaignService._default_candidates(
        campaign,
        RotationState.bootstrap([1, 2, 3, 4]),
        runtime,
    )

    assert result == [
        {"trained_chara_id": 11, "rank_score": 12345, "score": 12345.0, "rental": False},
        {"trained_chara_id": 22, "rank_score": 23456, "score": 23456.0, "rental": False},
        {"trained_chara_id": 33, "rank": 7, "score": 7.0, "rental": False},
        {"trained_chara_id": 44, "score": 34567.0, "rank_score": 34567, "rental": True},
    ]


def test_default_career_request_uses_loop_member_friend_support():
    spec = valid_spec(
        loop_members=[
            {
                "chara_id": 1,
                "deck_id": 1,
                "friend_support": {
                    "viewer_id": 501,
                    "support_card_id": 9001,
                    "support_name": "Kitasan Black",
                },
            },
            {"chara_id": 2, "deck_id": 2},
            {"chara_id": 3, "deck_id": 3},
            {"chara_id": 4, "deck_id": 4},
        ]
    )
    campaign = {
        "campaign_id": "cmp1",
        "account": "acct01",
        "spec": spec,
        "context": {},
    }
    svc, *_ = service(default_career_request=True)

    request = svc._default_career_request(
        campaign,
        RotationState.bootstrap([1, 2, 3, 4]),
        [{"trained_chara_id": 11, "score": 20, "rental": False}],
        [],
        {},
    )

    assert request["friend_support"] == {
        "viewer_id": 501,
        "support_card_id": 9001,
        "support_name": "Kitasan Black",
    }


def test_create_generates_deterministic_campaign_preset_and_context():
    presets = FakePresetStore()
    svc, *_ = service(preset_store=presets)
    payload = valid_v3_spec(spark_targets=[{"category": "blue", "name": "power", "minimum_stars": 9}], race_plan={"core": [101], "optional": [202], "deferable": [303]})
    first = svc.create_campaign(payload)
    second = svc.create_campaign(payload)
    generated = presets.saved[-1]
    assert generated["name"].startswith("campaign-acct01-")
    assert presets.saved[-2]["name"] == generated["name"]
    assert generated["expect_attribute"] == [900, 1200, 1100, 700, 600]
    assert "support_card_ids" not in generated
    assert first["spec"]["strategy"]["preset_name"] == generated["name"]
    assert second["context"]["base_preset_name"] == "parent"
    assert second["context"]["race_agenda"] == {"CORE": [101], "OPTIONAL": [202], "DEFERABLE": [303]}
    assert second["context"]["step_race_overrides"] == {"mandatory_race_list": [101], "extra_race_list": [202], "parent_run": True}


def test_grand_live_preset_survives_campaign_create_and_request():
    presets = FakePresetStore()
    presets.presets["parent"].update({
        "scenario_id": 3,
        "performance_training_weight": 0.75,
    })
    svc, *_ = service(
        preset_store=presets,
        default_career_request=True,
    )

    campaign = svc.create_campaign(valid_v3_spec())
    generated_name = campaign["spec"]["strategy"]["preset_name"]
    generated = presets.load(generated_name)

    assert generated["scenario_id"] == 3
    assert generated["performance_training_weight"] == 0.75

    request = svc._default_career_request(
        campaign,
        RotationState.bootstrap([1001, 1002, 1003, 1004]),
        [],
        {"mandatory_race_list": [], "extra_race_list": []},
        {},
    )
    assert request["preset"]["scenario_id"] == 3
    assert request["preset"]["performance_training_weight"] == 0.75


def test_default_career_request_uses_rotating_members_manual_deck():
    svc, store, *_ = service(default_career_request=True)
    request = svc._default_career_request(store.campaign, RotationState(loop_chara_ids=(1, 2, 3, 4), run_index=2, produced=()), [], [], {})
    assert request["deck_id"] == 3


def test_default_lineage_resolves_two_distinct_non_trainee_parents():
    svc, store, *_ = service()
    store.campaign["spec"]["final_parent"] = {
        "chara_id": 2,
        "trained_chara_id": 50,
    }
    svc.planned_slots = svc._default_slots
    svc.candidate_pool = lambda *_args: [
        {"trained_chara_id": 70, "chara_id": 1, "score": 999, "rental": False},
        {"trained_chara_id": 50, "chara_id": 2, "score": 100, "rental": False},
        {"trained_chara_id": 51, "chara_id": 2, "score": 95, "rental": False},
        {"trained_chara_id": 60, "chara_id": 3, "score": 90, "rental": False},
    ]

    result = svc.prepare_next_run("cmp1")

    assert [row["trained_chara_id"] for row in result["resolved_slots"]] == [50, 60]
    assert len({row["trained_chara_id"] for row in result["resolved_slots"]}) == 2


def test_default_lineage_does_not_lock_final_parent_when_it_is_the_trainee():
    svc, store, *_ = service()
    store.campaign["spec"]["final_parent"] = {
        "chara_id": 2,
        "trained_chara_id": 50,
    }
    store.campaign["context"]["rotation"] = RotationState(
        loop_chara_ids=(1, 2, 3, 4),
        run_index=1,
        produced=(),
    ).to_dict()
    svc.planned_slots = svc._default_slots
    svc.candidate_pool = lambda *_args: [
        {"trained_chara_id": 50, "chara_id": 2, "score": 1000, "rental": False},
        {"trained_chara_id": 70, "chara_id": 1, "score": 100, "rental": False},
        {"trained_chara_id": 60, "chara_id": 3, "score": 90, "rental": False},
    ]

    result = svc.prepare_next_run("cmp1")

    assert [row["trained_chara_id"] for row in result["resolved_slots"]] == [70, 60]


def test_prepare_defaults_to_review_and_persists_before_return():
    svc, store, runner, _ = service()
    result = svc.prepare_next_run("cmp1")
    context = store.campaign["context"]
    assert context["rotation"]["run_index"] == 0
    assert context["prepared_run"] == result["prepared_run"]
    assert context["pending_review"]["kind"] == "prepared_run"
    assert context["review_required"] is True
    assert runner.calls[-1] == ("require_user_input", "cmp1", "approve_run")


def test_prepare_preserves_mapping_race_overrides_for_default_request():
    svc, store, *_ = service(default_career_request=True)
    overrides = {"mandatory_race_list": [101], "extra_race_list": [202], "parent_run": True}
    store.campaign["context"]["step_race_overrides"] = overrides
    svc.race_overrides = svc._default_races

    prepared = svc.prepare_next_run("cmp1")["prepared_run"]

    assert prepared["race_overrides"] == overrides


def test_prepare_next_run_captures_owned_parent_baseline():
    svc, store, *_ = service(
        snapshot=lambda _account: {
            "owned_candidates": [
                {"trained_chara_id": 11},
                {"trained_chara_id": 12},
                {"trained_chara_id": 0},
            ]
        }
    )

    svc.prepare_next_run("cmp1")

    assert store.campaign["context"]["baseline_parent_ids"] == [11, 12]


def test_prepare_next_run_resets_previous_run_start_reservation():
    svc, store, *_ = service()
    store.campaign["context"]["run_start"] = {
        "operation_id": "old-operation",
        "status": "STARTED",
        "result": {"job_id": "old-job"},
    }
    svc.prepare_next_run("cmp1")
    assert store.campaign["context"]["run_start"] is None


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

def test_activate_real_store_reconciles_matching_active_career(tmp_path):
    prepared = {"account": "acct01", "campaign_id": "cmp1", "card_id": 100101, "deck_id": 2, "parent_id_1": 10, "parent_id_2": 11}
    _, store, _, _ = real_running_service(tmp_path, prepared_run=prepared)
    runner = CampaignRunner(store)
    svc, _, _, _ = service(
        store=store,
        runner=runner,
        snapshot=lambda _account: {
            "current_career": {"active": True, "card_id": 100101, "deck_id": 2, "parent_id_1": 10, "parent_id_2": 11},
            "runtime": {"api_reachable": True},
            "bot_state": {"career_runner": {"running": False}},
        },
    )

    result = svc.activate("cmp1")

    assert result["state"] == "RUNNING_CAREER"
    assert store.get("cmp1")["state"] == "RUNNING_CAREER"

def test_activate_real_store_reconciles_mismatched_active_career(tmp_path):
    prepared = {"account": "acct01", "campaign_id": "cmp1", "card_id": 100101, "deck_id": 2, "parent_id_1": 10, "parent_id_2": 11}
    _, store, _, _ = real_running_service(tmp_path, prepared_run=prepared)
    svc, _, _, _ = service(
        store=store,
        runner=CampaignRunner(store),
        snapshot=lambda _account: {"current_career": {"active": True, "card_id": 999999, "deck_id": 2, "parent_id_1": 10, "parent_id_2": 11}},
    )

    result = svc.activate("cmp1")

    assert result["state"] == "PAUSED"
    assert result["next_action"] == "inspect_current_career"

def test_resume_real_store_reconciles_matching_active_career(tmp_path):
    prepared = {"account": "acct01", "campaign_id": "cmp1", "card_id": 100101, "deck_id": 2, "parent_id_1": 10, "parent_id_2": 11}
    _, store, _, _ = real_running_service(tmp_path, prepared_run=prepared)
    store.pause("cmp1")
    svc, _, _, resumed = service(
        store=store,
        runner=CampaignRunner(store),
        snapshot=lambda _account: {
            "current_career": {"active": True, "card_id": 100101, "deck_id": 2, "parent_id_1": 10, "parent_id_2": 11},
            "bot_state": {"career_runner": {"running": False}},
        },
    )

    result = svc.resume("cmp1")

    assert result["state"] == "RUNNING_CAREER"
    assert resumed == [prepared]

def test_resume_real_store_reconciles_mismatched_active_career_without_unpausing(tmp_path):
    prepared = {"account": "acct01", "campaign_id": "cmp1", "card_id": 100101, "deck_id": 2, "parent_id_1": 10, "parent_id_2": 11}
    _, store, _, _ = real_running_service(tmp_path, prepared_run=prepared)
    store.pause("cmp1")
    svc, _, _, _ = service(
        store=store,
        runner=CampaignRunner(store),
        snapshot=lambda _account: {"current_career": {"active": True, "card_id": 999999, "deck_id": 2, "parent_id_1": 10, "parent_id_2": 11}},
    )

    result = svc.resume("cmp1")

    assert result["state"] == "PAUSED"
    assert result["paused_from_state"] == "RUNNING_CAREER"

@pytest.mark.parametrize("method", ["activate", "resume"])
def test_entry_flow_treats_explicit_none_career_as_authoritative_absence(tmp_path, method):
    prepared = {"account": "acct01", "campaign_id": "cmp1", "card_id": 100101}
    _, store, _, _ = real_running_service(tmp_path, prepared_run=prepared)
    store.reserve_prepared_run_start("cmp1", "operation-1")
    store.finish_prepared_run_start(
        "cmp1",
        "operation-1",
        status="STARTED",
        result={"job_id": "job-1"},
    )
    svc, _, _, _ = service(
        store=store,
        runner=CampaignRunner(store),
        snapshot=lambda _account: {"current_career": None},
    )

    result = getattr(svc, method)("cmp1")

    assert result["state"] == "PAUSED"
    assert result["error"] == "Persisted running career is no longer active"
    assert result["context"]["run_start"]["status"] == "STARTED"
    assert store.recent_events("cmp1")[0]["event_type"] == "runtime_active_career_disappeared"


def test_runtime_snapshot_type_error_is_not_retried_or_masked():
    calls = []

    def snapshot(account):
        calls.append(account)
        raise TypeError("snapshot bug")

    svc, *_ = service(snapshot=snapshot)
    with pytest.raises(TypeError, match="snapshot bug"):
        svc.activate("cmp1")
    assert calls == ["acct01"]


def test_prepare_auto_mode_skips_review_and_audits_replacement():
    campaign = {"campaign_id": "cmp1", "account": "acct01", "state": "SELECTING_LINEAGE", "spec": valid_spec(options={"allow_rental": False, "auto_use_best_veteran": True}), "context": {}}
    svc, store, runner, _ = service(FakeStore(campaign))
    result = svc.prepare_next_run("cmp1")
    assert result["campaign"]["next_action"] == "start_career"
    assert store.campaign["context"]["pending_review"] is None
    assert store.events[0]["event_type"] == "automatic_legacy_replacement"
    assert not any(call[0] == "require_user_input" for call in runner.calls)


def test_prepare_manual_mode_emits_no_automatic_replacement_event():
    svc, store, *_ = service()
    svc.prepare_next_run("cmp1")
    assert store.events == []


def test_prepare_unresolved_slot_persists_review_and_never_builds_request():
    built = []
    svc, store, runner, _ = service()
    svc.candidate_pool = lambda *_args: []
    svc.career_request = lambda *_args: built.append(True) or {}
    result = svc.prepare_next_run("cmp1")
    assert built == []
    assert result["prepared_run"] is None
    assert store.campaign["context"]["pending_review"]["kind"] == "unresolved_legacy_slots"
    assert runner.calls[-1] == ("require_user_input", "cmp1", "prepare_next_run")

def test_reconcile_runtime_migrates_legacy_four_member_campaign_before_recovery():
    svc, store, _, _ = service()
    store.campaign.update({
        "state": "RUNNING_CAREER",
        "context": {
            "rotation": {
                "loop_chara_ids": [1, 2, 3, 4],
                "run_index": 2,
                "produced": [[1, "v1"], [2, "v2"]],
            },
            "prepared_run": {
                "card_id": 100101,
                "deck_id": 2,
                "parent_id_1": 10,
                "parent_id_2": 11,
            },
        },
    })

    result = svc.reconcile_runtime(
        "cmp1",
        current_career={
            "active": True,
            "card_id": 100101,
            "deck_id": 2,
            "parent_id_1": 10,
            "parent_id_2": 11,
        },
    )

    assert result["state"] == "RUNNING_CAREER"
    assert store.campaign["context"]["stage_state"]["bootstrap_chara_ids"] == [3, 4, 1, 2]
    assert store.campaign["context"]["stage_state"]["stage_index"] == 0
    assert store.campaign["context"]["legacy_stage_migrated"] is True


def test_reconcile_matching_active_career_resumes_running_state():
    svc, store, _, started = service()
    store.campaign.update({
        "state": "RUNNING_CAREER",
        "context": {"prepared_run": {"career_request": {
            "card_id": 100101,
            "deck_id": 2,
            "parent_id_1": 10,
            "parent_id_2": 11,
        }}},
    })

    result = svc.reconcile_runtime(
        "cmp1",
        current_career={"active": True, "card_id": 100101, "deck_id": 2, "parent_id_1": 10, "parent_id_2": 11},
    )

    assert result["state"] == "RUNNING_CAREER"
    assert store.campaign["state"] == "RUNNING_CAREER"
    assert started == []

def test_reconcile_matching_active_career_supports_trainee_identity_contract():
    svc, store, _, _ = service()
    store.campaign.update({
        "state": "RUNNING_CAREER",
        "context": {"prepared_run": {"trainee_chara_id": 3, "deck_id": 2}},
    })

    result = svc.reconcile_runtime(
        "cmp1",
        current_career={"active": True, "trainee_chara_id": 3, "deck_id": 2},
    )

    assert result["state"] == "RUNNING_CAREER"


def test_reconcile_matches_prepared_base_trainee_to_runtime_card_id():
    svc, store, _, _ = service()
    store.campaign.update({
        "state": "RUNNING_CAREER",
        "context": {"prepared_run": {"trainee_chara_id": 1001}},
    })

    result = svc.reconcile_runtime(
        "cmp1",
        current_career={"active": True, "card_id": 100101},
    )

    assert result["state"] == "RUNNING_CAREER"


def test_reconcile_normal_prepared_run_rejects_wrong_legacy_slot_parents():
    svc, store, _, _ = service()
    store.campaign.update({
        "state": "RUNNING_CAREER",
        "context": {"prepared_run": {
            "card_id": 100101,
            "deck_id": 2,
            "legacy_slots": [
                {"trained_chara_id": 10},
                {"trained_chara_id": 11},
            ],
        }},
    })

    result = svc.reconcile_runtime(
        "cmp1",
        current_career={"active": True, "card_id": 100101, "deck_id": 2, "parent_id_1": 10, "parent_id_2": 99},
    )

    assert result["state"] == "PAUSED"

def test_reconcile_real_prepared_payload_rejects_wrong_parent(tmp_path):
    store = CampaignStore(tmp_path / "campaigns.sqlite3")
    store.create(ParentCampaignSpec.model_validate(valid_spec()), campaign_id="cmp1")
    for state in ("READY", "STARTING_BOT", "SELECTING_LINEAGE"):
        store.transition("cmp1", state)
    svc, _, _, _ = service(store=store)
    svc.planned_slots = lambda *_args: [
        {"role": "parent1", "mode": "FLEXIBLE", "trained_chara_id": 10},
        {"role": "parent2", "mode": "FLEXIBLE", "trained_chara_id": 12},
    ]
    svc.candidate_pool = lambda *_args: [
        {"trained_chara_id": 11, "score": 20, "rental": False},
        {"trained_chara_id": 12, "score": 10, "rental": False},
    ]
    prepared = svc.prepare_next_run("cmp1")["prepared_run"]
    store.transition("cmp1", "RUNNING_CAREER")

    result = svc.reconcile_runtime(
        "cmp1",
        current_career={
            "active": True,
            "trainee_chara_id": prepared["trainee_chara_id"],
            "parent_id_1": prepared["parents"][0]["trained_chara_id"],
            "parent_id_2": 999,
        },
    )

    assert result["state"] == "PAUSED"

@pytest.mark.parametrize("field,value", [("account", "acct02"), ("campaign_id", "other")])
def test_reconcile_rejects_wrong_optional_campaign_identity(field, value):
    svc, store, _, _ = service()
    store.campaign.update({
        "state": "RUNNING_CAREER",
        "context": {"prepared_run": {
            "account": "acct01",
            "campaign_id": "cmp1",
            "card_id": 100101,
            "deck_id": 2,
            "parent_id_1": 10,
            "parent_id_2": 11,
        }},
    })
    current = {"active": True, "account": "acct01", "campaign_id": "cmp1", "card_id": 100101, "deck_id": 2, "parent_id_1": 10, "parent_id_2": 11}
    current[field] = value

    assert svc.reconcile_runtime("cmp1", current_career=current)["state"] == "PAUSED"

@pytest.mark.parametrize("missing", ["account", "campaign_id"])
def test_reconcile_rejects_missing_required_campaign_identity(missing):
    svc, store, _, _ = service()
    prepared = {"account": "acct01", "campaign_id": "cmp1", "card_id": 100101, "deck_id": 2, "parent_id_1": 10, "parent_id_2": 11}
    store.campaign.update({"state": "RUNNING_CAREER", "context": {"prepared_run": prepared}})
    current = {"active": True, **prepared}
    current.pop(missing)

    assert svc.reconcile_runtime("cmp1", current_career=current)["state"] == "PAUSED"

@pytest.mark.parametrize("field,value", [("account", "acct02"), ("campaign_id", "other")])
def test_reconcile_real_store_rejects_wrong_optional_campaign_identity(tmp_path, field, value):
    prepared = {"account": "acct01", "campaign_id": "cmp1", "card_id": 100101, "deck_id": 2, "parent_id_1": 10, "parent_id_2": 11}
    svc, _, _, _ = real_running_service(tmp_path, prepared_run=prepared)
    current = {"active": True, **prepared}
    current[field] = value

    assert svc.reconcile_runtime("cmp1", current_career=current)["state"] == "PAUSED"

def test_reconcile_string_false_active_is_not_active():
    svc, store, _, _ = service()
    store.campaign.update({"state": "PAUSED", "context": {"prepared_run": {}}})

    result = svc.reconcile_runtime("cmp1", current_career={"active": "false"})

    assert result["state"] == "PAUSED"
    assert not any(call[0] == "update_context" for call in store.calls)

def test_reconcile_real_paused_campaign_treats_string_false_as_noop(tmp_path):
    svc, store, runner, started = real_running_service(tmp_path, prepared_run={"card_id": 100101})
    store.pause("cmp1")
    before = store.get("cmp1")

    result = svc.reconcile_runtime("cmp1", current_career={"active": "false"})

    assert result == before
    assert runner.calls == []
    assert started == []

def test_reconcile_mismatched_active_career_pauses_campaign_without_touching_career():
    svc, store, runner, started = service()
    store.campaign.update({
        "state": "RUNNING_CAREER",
        "context": {"prepared_run": {"career_request": {
            "card_id": 100101,
            "deck_id": 2,
            "parent_id_1": 10,
            "parent_id_2": 11,
        }}},
    })

    result = svc.reconcile_runtime(
        "cmp1",
        current_career={"active": True, "card_id": 999999, "deck_id": 9},
    )

    assert result["state"] == "PAUSED"
    assert "does not match" in result["error"].lower()
    assert store.events[-1]["event_type"] == "runtime_reconciliation_mismatch"
    assert runner.calls == []
    assert started == []

def test_reconcile_running_without_active_career_uses_real_store_safe_pause(tmp_path):
    store = CampaignStore(tmp_path / "campaigns.sqlite3")
    store.create(ParentCampaignSpec.model_validate(valid_spec()), campaign_id="cmp1")
    for state in ("READY", "STARTING_BOT", "WAITING_FOR_LOGIN", "SELECTING_LINEAGE", "RUNNING_CAREER"):
        store.transition("cmp1", state)
    store.update_context("cmp1", {"prepared_run": {"card_id": 100101}, "run_start": None})
    svc, _, _, started = service(store=store)

    result = svc.reconcile_runtime("cmp1", current_career={"active": False})

    assert result["state"] == "PAUSED"
    assert result["next_action"] == "review_missing_active_career"
    assert result["context"]["prepared_run"] == {"card_id": 100101}
    assert result["context"]["runtime_reconciliation"]["status"] == "ACTIVE_CAREER_DISAPPEARED"
    assert started == []

@pytest.mark.parametrize("state", ["PAUSED", "NEEDS_USER_INPUT", "COMPLETED"])
def test_reconcile_no_active_career_is_noop_for_nonrecoverable_states(state):
    svc, store, runner, started = service()
    store.campaign["state"] = state

    result = svc.reconcile_runtime("cmp1", current_career={"active": False})

    assert result["state"] == state
    assert runner.calls == []
    assert started == []

def test_reconcile_missing_locked_veteran_requires_specific_user_action():
    svc, store, _, started = service()
    store.campaign.update({"state": "SELECTING_LINEAGE", "context": {"prepared_run": {}}})
    svc.planned_slots = lambda *_args: [{"role": "parent1", "mode": "LOCKED", "trained_chara_id": 99}]
    svc.candidate_pool = lambda *_args: []

    result = svc.reconcile_runtime("cmp1", current_career={"active": False})

    assert result["campaign"]["state"] == "NEEDS_USER_INPUT"
    assert result["campaign"]["next_action"] == "resolve_missing_locked_veteran"
    assert started == []

def test_reconcile_unavailable_rental_uses_owned_fallback():
    svc, store, _, started = service()
    store.campaign["spec"]["options"]["allow_rental"] = True
    store.campaign.update({
        "state": "SELECTING_LINEAGE",
        "context": {"prepared_run": {"legacy_slots": [
            {"trained_chara_id": 50, "score": 30, "rental": True, "status": "RESOLVED"}
        ]}},
    })
    svc.candidate_pool = lambda *_args: [{"trained_chara_id": 51, "score": 20, "rental": False}]

    result = svc.reconcile_runtime("cmp1", current_career={"active": False})

    assert result["resolved_slots"][0]["trained_chara_id"] == 51
    assert result["resolved_slots"][0]["rental"] is False
    assert started == []

def test_reconcile_unavailable_rental_without_fallback_requires_review():
    svc, store, _, started = service()
    store.campaign["spec"]["options"]["allow_rental"] = True
    store.campaign.update({
        "state": "SELECTING_LINEAGE",
        "context": {"prepared_run": {"legacy_slots": [
            {"trained_chara_id": 50, "score": 30, "rental": True, "status": "RESOLVED"}
        ]}},
    })
    svc.candidate_pool = lambda *_args: []

    result = svc.reconcile_runtime("cmp1", current_career={"active": False})

    assert result["campaign"]["state"] == "NEEDS_USER_INPUT"
    assert result["campaign"]["next_action"] == "review_unavailable_rental"
    assert started == []


def test_approve_rebuilds_stale_one_parent_prepared_run_before_starting():
    svc, store, _, started = service()
    store.campaign["spec"]["final_parent"] = {
        "chara_id": 2,
        "trained_chara_id": 50,
    }
    store.campaign["context"]["prepared_run"] = {
        "campaign_id": "cmp1",
        "trainee_chara_id": 1,
        "legacy_slots": [
            {"trained_chara_id": 50, "status": "RESOLVED", "rental": False}
        ],
    }
    svc.planned_slots = svc._default_slots
    svc.candidate_pool = lambda *_args: [
        {"trained_chara_id": 50, "chara_id": 2, "score": 100, "rental": False},
        {"trained_chara_id": 60, "chara_id": 3, "score": 90, "rental": False},
    ]

    result = svc.approve_run("cmp1")

    assert result == {"started": True}
    assert len(started) == 1
    assert [row["trained_chara_id"] for row in started[0]["parents"]] == [50, 60]


def test_approve_moves_campaign_to_running_after_start(tmp_path):
    store = CampaignStore(tmp_path / "campaigns.sqlite3")
    store.create(ParentCampaignSpec.model_validate(valid_spec()), campaign_id="cmp1")
    for state in ("READY", "STARTING_BOT", "SELECTING_LINEAGE"):
        store.transition("cmp1", state)
    svc, _, _, _ = service(
        store=store,
        runner=CampaignRunner(store),
        start_career=lambda _request: {"job_id": "job-1"},
    )
    svc.prepare_next_run("cmp1")

    result = svc.approve_run("cmp1")
    campaign = store.get("cmp1")

    assert result == {"job_id": "job-1"}
    assert campaign["state"] == "RUNNING_CAREER"
    assert campaign["next_action"] == "monitor_career"
    assert campaign["usage"]["runs"] == 1


def test_approve_delegates_one_persisted_request_exactly_once():
    svc, store, _, started = service()
    svc.prepare_next_run("cmp1")
    first = svc.approve_run("cmp1", {"race_overrides": [303]})
    second = svc.approve_run("cmp1")
    assert first == {"started": True}
    assert second == first
    assert len(started) == 1
    assert started[0]["race_overrides"] == [303]


def test_second_approval_with_different_allowed_override_never_starts_twice():
    svc, _, _, started = service()
    svc.prepare_next_run("cmp1")
    first = svc.approve_run("cmp1", {"race_overrides": [303]})
    second = svc.approve_run("cmp1", {"race_overrides": [404]})
    assert first == {"started": True}
    assert second == first
    assert len(started) == 1


def test_approve_rejects_unknown_or_identity_overrides():
    svc, *_ = service()
    svc.prepare_next_run("cmp1")
    for override in ({"unknown": 1}, {"account": "acct02"}, {"campaign_id": "other"}):
        with pytest.raises(ValueError, match="override"):
            svc.approve_run("cmp1", override)


def test_concurrent_approvals_call_gateway_once():
    entered = Event()
    release = Event()
    calls = []

    def gateway(request):
        calls.append(request)
        entered.set()
        release.wait(2)
        return {"job_id": "job-1"}

    svc, *_ = service(start_career=gateway)
    svc.prepare_next_run("cmp1")
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(svc.approve_run, "cmp1")
        assert entered.wait(1)
        second = pool.submit(svc.approve_run, "cmp1")
        concurrent = second.result(timeout=1)
        release.set()
        completed = first.result(timeout=1)
    assert len(calls) == 1
    assert concurrent["status"] == "STARTING"
    assert completed == {"job_id": "job-1"}


def test_failed_gateway_marks_failed_and_allows_retry():
    attempts = []

    def gateway(request):
        attempts.append(request)
        if len(attempts) == 1:
            raise RuntimeError("gateway failed")
        return {"job_id": "job-2"}

    svc, store, *_ = service(start_career=gateway)
    svc.prepare_next_run("cmp1")
    with pytest.raises(RuntimeError, match="gateway failed"):
        svc.approve_run("cmp1")
    assert store.campaign["context"]["run_start"]["status"] == "FAILED"
    assert svc.approve_run("cmp1") == {"job_id": "job-2"}
    assert len(attempts) == 2


def _v3_campaign_for_cycle(*, final_stage_active=False):
    spec = ParentCampaignSpec.model_validate(
        valid_v3_spec(race_plan={"core": [101], "optional": [], "deferable": []})
    ).model_dump(mode="json")
    return {
        "campaign_id": "cmp1",
        "account": "acct01",
        "state": "SELECTING_LINEAGE",
        "spec": spec,
        "context": {
            "bootstrap_rotation": {
                "bootstrap_chara_ids": [1001, 1002, 1003],
                "run_index": 0,
                "final_stage_active": final_stage_active,
                "final_repeat_count": 0,
                "produced": [],
            },
            "ready_parent_candidates": [],
            "selected_ready_pair": None,
            "cycle_migrated": True,
            "race_agenda": {"CORE": [101], "OPTIONAL": [], "DEFERABLE": []},
        },
        "version": 1,
    }


def _v3_campaign_for_stage(stage_index=0):
    spec = ParentCampaignSpec.model_validate(
        valid_v3_spec(race_plan={"core": [101], "optional": [], "deferable": []})
    ).model_dump(mode="json")
    return {
        "campaign_id": "cmp1",
        "account": "acct01",
        "state": "SELECTING_LINEAGE",
        "spec": spec,
        "context": {
            "stage_state": {
                "bootstrap_chara_ids": [1001, 1002, 1003],
                "stage_index": stage_index,
                "completed_bootstrap_stages": list(range(min(stage_index, 3))),
                "final_repeat_count": 0,
                "produced": [],
            },
            "stage_goal_assignments": {
                "0": [spec["spark_targets"][0]],
                "1": [],
                "2": [],
            },
            "bootstrap_goal_state": {},
            "race_agenda": {"CORE": [101], "OPTIONAL": [], "DEFERABLE": []},
        },
        "version": 1,
    }


def _v3_runtime():
    def display(trained_id, *, dirt=0, stamina=0):
        factors = []
        if dirt:
            factors.append({"category": "aptitude", "name": "Dirt", "stars": dirt})
        if stamina:
            factors.append({"category": "stat", "name": "Stamina", "stars": stamina})
        return {
            "trained_chara_id": trained_id,
            "tree": {
                "self": {"factors": factors},
                "p1": {"factors": []},
                "p2": {"factors": []},
            },
        }

    owned = [
        {"trained_chara_id": 11, "card_id": 100201, "rank_score": 100, "win_saddle_id_array": [10]},
        {"trained_chara_id": 12, "card_id": 100301, "rank_score": 90, "win_saddle_id_array": [10]},
        {"trained_chara_id": 13, "card_id": 100501, "rank_score": 1000, "win_saddle_id_array": []},
    ]
    return {
        "owned_candidates": owned,
        "rental_candidates": [],
        "display_by_id": {
            11: display(11, dirt=2, stamina=3),
            12: display(12, dirt=2, stamina=3),
            13: display(13),
        },
        "umas": [
            {"id": 100101, "card_id": 100101},
            {"id": 100201, "card_id": 100201},
            {"id": 100301, "card_id": 100301},
            {"id": 100401, "card_id": 100401},
        ],
        "base_aptitudes": {
            "100101": {"dirt": "D", "long": "A"},
            "100201": {"dirt": "A", "long": "A"},
            "100301": {"dirt": "A", "long": "A"},
            "100401": {"dirt": "D", "long": "A"},
        },
        "race_rows": [
            {"program_id": 101, "turn": 20, "date": "Classic Year Early Jan", "name": "Dirt G1", "type": "G1", "terrain": "Dirt", "distance": "Long"},
        ],
        "g1_saddle_program_map": {101: {10}},
    }


def test_v3_prepare_requires_user_input_when_trainee_is_in_stage_deck():
    campaign = _v3_campaign_for_cycle()
    campaign["spec"]["loop_members"][0]["chara_id"] = 1068
    campaign["spec"]["loop_members"][0]["deck_id"] = 4
    campaign["context"]["bootstrap_rotation"]["bootstrap_chara_ids"][0] = 1068
    store = FakeStore(campaign)
    runtime = _v3_runtime()
    runtime["umas"].append({"id": 106801, "card_id": 106801, "name": "Kitasan Black"})
    runtime["decks"] = [
        {
            "id": 4,
            "name": "Deck 4",
            "cards": [
                {"id": 30010, "name": "Fine Motion"},
                {"id": 30028, "name": "Kitasan Black"},
            ],
        }
    ]
    svc, _, runner, _ = service(store=store, snapshot=lambda _account: runtime)
    svc.candidate_pool = svc._default_candidates

    result = svc.prepare_next_run("cmp1")

    assert result["prepared_run"] is None
    assert result["campaign"]["next_action"] == "resolve_stage_deck_conflict"
    review = store.campaign["context"]["pending_review"]
    assert review["kind"] == "stage_deck_conflict"
    assert review["rotation_index"] == 0
    assert review["stage_kind"] == "cycle_bootstrap"
    assert review["trainee_chara_id"] == 1068
    assert review["deck_id"] == 4
    assert review["conflicts"][0]["support_card_id"] == 30028
    assert runner.calls[-1] == ("require_user_input", "cmp1", "resolve_stage_deck_conflict")


def test_v3_ambiguity_only_auto_starts_deterministic_cycle_run():
    campaign = _v3_campaign_for_cycle()
    campaign["spec"]["strategy"]["approval_mode"] = "ambiguity_only"
    campaign["spec"]["options"]["auto_use_best_veteran"] = False
    store = FakeStore(campaign)
    runtime = _v3_runtime()
    svc, _, runner, _ = service(store=store, snapshot=lambda _account: runtime)
    svc.candidate_pool = svc._default_candidates

    result = svc.prepare_next_run("cmp1")

    assert result["campaign"]["next_action"] == "start_career"
    assert store.campaign["context"]["review_required"] is False
    assert store.campaign["context"]["pending_review"] is None
    assert not any(call[0] == "require_user_input" for call in runner.calls)


def test_v3_per_generation_still_requires_pre_run_approval():
    campaign = _v3_campaign_for_cycle()
    campaign["spec"]["strategy"]["approval_mode"] = "per_generation"
    campaign["spec"]["options"]["auto_use_best_veteran"] = True
    store = FakeStore(campaign)
    runtime = _v3_runtime()
    svc, _, runner, _ = service(store=store, snapshot=lambda _account: runtime)
    svc.candidate_pool = svc._default_candidates

    result = svc.prepare_next_run("cmp1")

    assert result["campaign"]["next_action"] == "approve_run"
    assert store.campaign["context"]["review_required"] is True
    assert store.campaign["context"]["pending_review"]["kind"] == "prepared_run"
    assert runner.calls[-1] == ("require_user_input", "cmp1", "approve_run")


def test_v3_fully_automatic_auto_starts_deterministic_cycle_run():
    campaign = _v3_campaign_for_cycle()
    campaign["spec"]["strategy"]["approval_mode"] = "fully_automatic"
    campaign["spec"]["options"]["auto_use_best_veteran"] = False
    store = FakeStore(campaign)
    runtime = _v3_runtime()
    svc, _, runner, _ = service(store=store, snapshot=lambda _account: runtime)
    svc.candidate_pool = svc._default_candidates

    result = svc.prepare_next_run("cmp1")

    assert result["campaign"]["next_action"] == "start_career"
    assert store.campaign["context"]["review_required"] is False
    assert not any(call[0] == "require_user_input" for call in runner.calls)


def test_v3_prepare_uses_stage_trainee_and_ranks_aptitude_feasible_pair():
    store = FakeStore(_v3_campaign_for_stage(0))
    runtime = _v3_runtime()
    svc, _, _, _ = service(store=store, snapshot=lambda _account: runtime)
    svc.candidate_pool = svc._default_candidates

    result = svc.prepare_next_run("cmp1")

    prepared = result["prepared_run"]
    assert prepared["trainee_chara_id"] == 1001
    assert prepared["card_id"] == 100101
    assert [row["trained_chara_id"] for row in prepared["legacy_slots"]] == [11, 12]
    assert store.campaign["context"]["aptitude_targets"][0]["aptitude"] == "dirt"
    assert store.campaign["context"]["aptitude_shortfalls"] == []
    assert store.campaign["context"]["aptitude_evidence"]["dirt"]["total_stars"] == 4


def test_v3_prepare_includes_parent_specific_affinity_races_in_aptitude_targets():
    campaign = _v3_campaign_for_stage(0)
    campaign["spec"]["race_plan"] = {"core": [], "optional": [], "deferable": []}
    campaign["context"]["race_agenda"] = {"CORE": [], "OPTIONAL": [], "DEFERABLE": []}
    store = FakeStore(campaign)
    runtime = _v3_runtime()
    svc, _, _, _ = service(store=store, snapshot=lambda _account: runtime)
    svc.candidate_pool = svc._default_candidates

    result = svc.prepare_next_run("cmp1")

    assert result["prepared_run"]["race_overrides"]["extra_race_list"] == [101]
    assert store.campaign["context"]["aptitude_targets"] == [
        {
            "aptitude": "dirt",
            "starting_grade": "D",
            "required_red_stars": 4,
            "achievable_target_grade": "B",
            "supporting_race_ids": [101],
        }
    ]
    assert store.campaign["context"]["aptitude_shortfalls"] == []


def test_v3_prepare_uses_projected_displayed_affinity_callback():
    store = FakeStore(_v3_campaign_for_stage(0))
    runtime = _v3_runtime()
    calls = []
    svc, _, _, _ = service(
        store=store,
        snapshot=lambda _account: runtime,
        projected_affinity=lambda card_id, first, second, saddles: calls.append(
            (card_id, first["trained_chara_id"], second["trained_chara_id"], set(saddles))
        ) or {"total": 77},
    )
    svc.candidate_pool = svc._default_candidates

    svc.prepare_next_run("cmp1")

    assert store.campaign["context"]["projected_displayed_affinity"] == 77
    assert calls
    assert all(call[0] == 100101 for call in calls)
    assert all(call[3] == {10} for call in calls)


def test_v3_prepare_final_stage_uses_exact_final_uma_card_and_durable_setup():
    campaign = _v3_campaign_for_cycle(final_stage_active=True)
    campaign["context"]["ready_parent_candidates"] = [
        {"candidate_id": "v11", "trained_chara_id": 11, "bootstrap_chara_id": 1001},
        {"candidate_id": "v12", "trained_chara_id": 12, "bootstrap_chara_id": 1002},
    ]
    store = FakeStore(campaign)
    runtime = _v3_runtime()
    svc, _, _, _ = service(store=store, snapshot=lambda _account: runtime)
    svc.candidate_pool = svc._default_candidates

    result = svc.prepare_next_run("cmp1")

    prepared = result["prepared_run"]
    assert prepared["trainee_chara_id"] == 1004
    assert prepared["card_id"] == 100401
    assert prepared["deck_id"] == 4
    assert prepared["friend_support"]["viewer_id"] == 904


def test_migrated_legacy_final_stage_pauses_when_durable_final_setup_is_missing():
    campaign = {
        "campaign_id": "cmp1",
        "account": "acct01",
        "state": "SELECTING_LINEAGE",
        "spec": valid_spec(final_uma={"card_id": 100101}),
        "context": {
            "stage_state": {
                "bootstrap_chara_ids": [1, 2, 3, 4],
                "stage_index": 4,
                "completed_bootstrap_stages": [0, 1, 2, 3],
                "final_repeat_count": 0,
                "produced": [],
            },
            "stage_goal_assignments": {"0": [], "1": [], "2": [], "3": []},
        },
        "version": 1,
    }
    store = FakeStore(campaign)
    runtime = _v3_runtime()
    svc, _, _, _ = service(store=store, snapshot=lambda _account: runtime)
    svc.candidate_pool = svc._default_candidates

    result = svc.prepare_next_run("cmp1")

    assert result["campaign"]["state"] == "PAUSED"
    assert result["campaign"]["next_action"] == "resolve_final_uma_setup"
    assert "deck" in result["campaign"]["error"].lower()


def test_v3_prepare_pauses_when_exact_final_uma_is_unavailable():
    campaign = _v3_campaign_for_cycle(final_stage_active=True)
    campaign["context"]["ready_parent_candidates"] = [
        {"candidate_id": "v11", "trained_chara_id": 11, "bootstrap_chara_id": 1001},
        {"candidate_id": "v12", "trained_chara_id": 12, "bootstrap_chara_id": 1002},
    ]
    store = FakeStore(campaign)
    runtime = _v3_runtime()
    runtime["umas"] = [row for row in runtime["umas"] if row["id"] != 100401]
    svc, _, _, _ = service(store=store, snapshot=lambda _account: runtime)
    svc.candidate_pool = svc._default_candidates

    result = svc.prepare_next_run("cmp1")

    assert result["campaign"]["state"] == "PAUSED"
    assert result["campaign"]["next_action"] == "resolve_final_uma_unavailable"
    assert "100401" in result["campaign"]["error"]


def test_resume_migrates_v3_stage_state_to_cyclic_context_from_self_sparks():
    campaign = _v3_campaign_for_stage(3)
    campaign["state"] = "PAUSED"
    campaign["context"]["stage_state"]["produced"] = [
        [1001, "1786"],
        [1002, "1787"],
        [1003, "1788"],
    ]
    store = FakeStore(campaign)
    store.candidates = [
        {
            "candidate_id": "veteran-1786",
            "trained_chara_id": 1786,
            "evaluation": {
                "stage_kind": "bootstrap",
                "trainee_chara_id": 1001,
                "rank_score": 100,
                "factor_tree": {
                    "self": {"factors": [{"category": "stat", "name": "Speed", "stars": 2}]},
                    "p1": {"factors": [{"category": "stat", "name": "Stamina", "stars": 3}]},
                    "p2": {"factors": [{"category": "stat", "name": "Stamina", "stars": 3}]},
                    "gp1": {"factors": [{"category": "stat", "name": "Stamina", "stars": 3}]},
                },
            },
        },
        {
            "candidate_id": "veteran-1787",
            "trained_chara_id": 1787,
            "evaluation": {
                "stage_kind": "bootstrap",
                "trainee_chara_id": 1002,
                "rank_score": 200,
                "factor_tree": {
                    "self": {"factors": [{"category": "stat", "name": "Stamina", "stars": 3}]},
                },
            },
        },
        {
            "candidate_id": "veteran-1788",
            "trained_chara_id": 1788,
            "evaluation": {
                "stage_kind": "bootstrap",
                "trainee_chara_id": 1003,
                "rank_score": 300,
                "factor_tree": {
                    "self": {"factors": [{"category": "stat", "name": "Stamina", "stars": 2}]},
                },
            },
        },
    ]
    svc, _, _, _ = service(store=store)

    svc.resume("cmp1")

    context = store.campaign["context"]
    assert context["bootstrap_rotation"]["final_stage_active"] is False
    assert context["bootstrap_rotation"]["run_index"] == 3
    assert context["bootstrap_rotation"]["bootstrap_chara_ids"] == [1001, 1002, 1003]
    assert [row["trained_chara_id"] for row in context["ready_parent_candidates"]] == [1787]
    assert context["stage_state"] is None


def test_get_campaign_migrates_v3_stage_state_to_cycle_context():
    campaign = _v3_campaign_for_stage(3)
    campaign["context"]["stage_state"]["produced"] = [
        [1001, "1786"],
        [1002, "1787"],
        [1003, "1788"],
    ]
    store = FakeStore(campaign)
    store.candidates = [
        {
            "candidate_id": "veteran-1787",
            "trained_chara_id": 1787,
            "evaluation": {
                "stage_kind": "bootstrap",
                "trainee_chara_id": 1002,
                "factor_tree": {
                    "self": {
                        "factors": [
                            {"category": "stat", "name": "Stamina", "stars": 3}
                        ]
                    }
                },
            },
        }
    ]
    svc, _, _, _ = service(store=store)

    result = svc.get_campaign("cmp1")

    assert result["context"]["bootstrap_rotation"]["run_index"] == 3
    assert result["context"]["bootstrap_rotation"]["final_stage_active"] is False
    assert [
        row["trained_chara_id"]
        for row in result["context"]["ready_parent_candidates"]
    ] == [1787]


def test_legacy_v2_resume_migrates_four_members_without_dropping_next_trainee():
    campaign = {
        "campaign_id": "cmp1",
        "account": "acct01",
        "state": "PAUSED",
        "spec": valid_spec(),
        "context": {
            "rotation": {
                "loop_chara_ids": [1, 2, 3, 4],
                "run_index": 2,
                "produced": [[1, "v1"], [2, "v2"]],
            }
        },
        "version": 1,
    }
    store = FakeStore(campaign)
    svc, _, _, _ = service(store=store)

    svc.resume("cmp1")

    assert store.campaign["context"]["stage_state"] == {
        "bootstrap_chara_ids": [3, 4, 1, 2],
        "stage_index": 0,
        "completed_bootstrap_stages": [],
        "final_repeat_count": 0,
        "produced": [[1, "v1"], [2, "v2"]],
    }
    assert set(store.campaign["context"]["stage_goal_assignments"]) == {"0", "1", "2", "3"}
    assert store.campaign["context"]["bootstrap_goal_state"] == {}


def test_migrated_v2_result_uses_stage_progression_instead_of_old_rotation():
    campaign = {
        "campaign_id": "cmp1",
        "account": "acct01",
        "state": "SELECTING_LINEAGE",
        "spec": valid_spec(),
        "context": {
            "stage_state": {
                "bootstrap_chara_ids": [1, 2, 3, 4],
                "stage_index": 0,
                "completed_bootstrap_stages": [],
                "final_repeat_count": 0,
                "produced": [],
            },
            "stage_goal_assignments": {
                "0": [{"category": "blue", "name": "stamina", "minimum_stars": 9, "priority": "required"}],
                "1": [],
                "2": [],
                "3": [],
            },
            "bootstrap_goal_state": {},
        },
        "version": 1,
    }
    store = FakeStore(campaign)
    svc, _, _, _ = service(store=store)

    result = svc.record_completed_veteran(
        "cmp1",
        {
            "candidate_id": "legacy-stage-result",
            "trained_chara_id": 99,
            "name": "Migrated Result",
            "spark_totals": {("blue", "stamina"): 9},
            "displayed_affinity": {"total": 10},
        },
        [],
    )

    assert result["campaign"]["context"]["stage_state"]["stage_index"] == 1
    assert result["candidate"]["evaluation"]["stage_kind"] == "bootstrap"


def test_v3_cycle_rotates_until_two_distinct_ready_parents_exist():
    store = FakeStore(_v3_campaign_for_cycle())
    svc, _, _, _ = service(store=store)

    first = svc.record_completed_veteran(
        "cmp1",
        {
            "candidate_id": "gold-1",
            "trained_chara_id": 2001,
            "name": "Gold Ship",
            "rank_score": 100,
            "spark_totals": {("blue", "stamina"): 9},
            "factor_tree": {
                "self": {"factors": [{"category": "stat", "name": "Speed", "stars": 2}]},
                "p1": {"factors": [{"category": "stat", "name": "Stamina", "stars": 3}]},
                "p2": {"factors": [{"category": "stat", "name": "Stamina", "stars": 3}]},
                "gp1": {"factors": [{"category": "stat", "name": "Stamina", "stars": 3}]},
            },
            "displayed_affinity": {"total": 100},
        },
        [],
    )
    context = first["campaign"]["context"]
    assert first["candidate"]["evaluation"]["ready_parent"] is False
    assert context["bootstrap_rotation"]["run_index"] == 1
    assert context["bootstrap_rotation"]["final_stage_active"] is False
    assert context["ready_parent_candidates"] == []

    second = svc.record_completed_veteran(
        "cmp1",
        {
            "candidate_id": "rice-1",
            "trained_chara_id": 2002,
            "name": "Rice Shower",
            "rank_score": 200,
            "factor_tree": {
                "self": {"factors": [{"category": "stat", "name": "Stamina", "stars": 3}]},
            },
            "displayed_affinity": {"total": 110},
        },
        [],
    )
    context = second["campaign"]["context"]
    assert second["candidate"]["evaluation"]["ready_parent"] is True
    assert context["bootstrap_rotation"]["run_index"] == 2
    assert context["bootstrap_rotation"]["final_stage_active"] is False
    assert [row["trained_chara_id"] for row in context["ready_parent_candidates"]] == [2002]

    third = svc.record_completed_veteran(
        "cmp1",
        {
            "candidate_id": "kitasan-1",
            "trained_chara_id": 2003,
            "name": "Kitasan Black",
            "rank_score": 300,
            "factor_tree": {
                "self": {"factors": [{"category": "stat", "name": "Stamina", "stars": 1}]},
            },
            "displayed_affinity": {"total": 120},
        },
        [],
    )
    context = third["campaign"]["context"]
    assert third["candidate"]["evaluation"]["ready_parent"] is False
    assert context["bootstrap_rotation"]["run_index"] == 3
    assert context["bootstrap_rotation"]["final_stage_active"] is False

    fourth = svc.record_completed_veteran(
        "cmp1",
        {
            "candidate_id": "gold-2",
            "trained_chara_id": 2004,
            "name": "Gold Ship",
            "rank_score": 400,
            "factor_tree": {
                "self": {"factors": [{"category": "stat", "name": "Stamina", "stars": 3}]},
            },
            "displayed_affinity": {"total": 130},
        },
        [],
    )
    context = fourth["campaign"]["context"]
    assert fourth["candidate"]["evaluation"]["ready_parent"] is True
    assert fourth["candidate"]["evaluation"]["decision"] == "enter_final"
    assert context["bootstrap_rotation"]["run_index"] == 4
    assert context["bootstrap_rotation"]["final_stage_active"] is True
    assert {row["trained_chara_id"] for row in context["ready_parent_candidates"]} == {2002, 2004}
    assert fourth["campaign"]["next_action"] == "prepare_next_run"


def test_compatible_ready_parent_pair_requires_distinct_bootstrap_characters():
    svc, *_ = service()
    spec = ParentCampaignSpec.model_validate(valid_v3_spec()).model_dump(mode="json")

    pairs = svc._compatible_ready_parent_pairs(
        spec,
        [
            {
                "trained_chara_id": 2201,
                "bootstrap_chara_id": 1001,
                "direct_base_compatibility": 15,
            },
            {
                "trained_chara_id": 2202,
                "bootstrap_chara_id": 1001,
                "direct_base_compatibility": 15,
            },
        ],
    )

    assert pairs == []


def test_v3_cycle_waits_for_compatible_ready_parent_pair():
    scores = {1001: 9, 1002: 17, 1003: 15}
    store = FakeStore(_v3_campaign_for_cycle())
    svc, _, _, _ = service(
        store=store,
        direct_compatibility=lambda _final_card_id, chara_id: scores[chara_id],
    )
    ready_factor_tree = {
        "self": {"factors": [{"category": "stat", "name": "Stamina", "stars": 3}]},
    }

    first = svc.record_completed_veteran(
        "cmp1",
        {
            "candidate_id": "weak-ready",
            "trained_chara_id": 2101,
            "name": "Weak Ready",
            "factor_tree": ready_factor_tree,
        },
        [],
    )
    second = svc.record_completed_veteran(
        "cmp1",
        {
            "candidate_id": "good-ready-a",
            "trained_chara_id": 2102,
            "name": "Good Ready A",
            "factor_tree": ready_factor_tree,
        },
        [],
    )

    context = second["campaign"]["context"]
    assert first["candidate"]["evaluation"]["decision"] == "advance"
    assert second["candidate"]["evaluation"]["decision"] == "advance"
    assert context["bootstrap_rotation"]["final_stage_active"] is False
    assert {
        row["trained_chara_id"]: row["direct_base_compatibility"]
        for row in context["ready_parent_candidates"]
    } == {2101: 9, 2102: 17}

    third = svc.record_completed_veteran(
        "cmp1",
        {
            "candidate_id": "good-ready-b",
            "trained_chara_id": 2103,
            "name": "Good Ready B",
            "factor_tree": ready_factor_tree,
        },
        [],
    )

    context = third["campaign"]["context"]
    assert third["candidate"]["evaluation"]["decision"] == "enter_final"
    assert context["bootstrap_rotation"]["final_stage_active"] is True
    assert {
        row["trained_chara_id"]: row["direct_base_compatibility"]
        for row in context["ready_parent_candidates"]
    } == {2101: 9, 2102: 17, 2103: 15}


def test_v3_cycle_dedupes_ready_parents_by_trained_chara_id():
    store = FakeStore(_v3_campaign_for_cycle())
    svc, _, _, _ = service(store=store)
    ready_factor_tree = {
        "self": {"factors": [{"category": "stat", "name": "Stamina", "stars": 3}]},
    }

    svc.record_completed_veteran(
        "cmp1",
        {
            "candidate_id": "ready-a",
            "trained_chara_id": 3001,
            "name": "Ready A",
            "factor_tree": ready_factor_tree,
        },
        [],
    )
    result = svc.record_completed_veteran(
        "cmp1",
        {
            "candidate_id": "ready-a-duplicate",
            "trained_chara_id": 3001,
            "name": "Ready A Again",
            "factor_tree": ready_factor_tree,
        },
        [],
    )

    context = result["campaign"]["context"]
    assert [row["trained_chara_id"] for row in context["ready_parent_candidates"]] == [3001]
    assert context["bootstrap_rotation"]["final_stage_active"] is False


def test_v3_cycle_final_stage_selects_best_ready_pair():
    campaign = _v3_campaign_for_cycle(final_stage_active=True)
    campaign["context"]["ready_parent_candidates"] = [
        {"candidate_id": "v11", "trained_chara_id": 11, "bootstrap_chara_id": 1001},
        {"candidate_id": "v12", "trained_chara_id": 12, "bootstrap_chara_id": 1002},
        {"candidate_id": "v13", "trained_chara_id": 13, "bootstrap_chara_id": 1003},
    ]
    store = FakeStore(campaign)
    runtime = _v3_runtime()
    runtime["display_by_id"][13] = {
        "trained_chara_id": 13,
        "tree": {
            "self": {
                "factors": [
                    {"category": "aptitude", "name": "Dirt", "stars": 2},
                    {"category": "stat", "name": "Stamina", "stars": 3},
                ]
            },
            "p1": {"factors": []},
            "p2": {"factors": []},
        },
    }

    def projected(_card_id, first, second, _saddles):
        pair = frozenset({first["trained_chara_id"], second["trained_chara_id"]})
        return {
            "total": {
                frozenset({11, 12}): 100,
                frozenset({11, 13}): 300,
                frozenset({12, 13}): 200,
            }[pair]
        }

    svc, _, _, _ = service(
        store=store,
        snapshot=lambda _account: runtime,
        projected_affinity=projected,
    )
    svc.candidate_pool = svc._default_candidates

    result = svc.prepare_next_run("cmp1")

    prepared = result["prepared_run"]
    context = store.campaign["context"]
    assert prepared["card_id"] == campaign["spec"]["final_uma"]["card_id"]
    assert [row["trained_chara_id"] for row in prepared["legacy_slots"]] == [11, 13]
    assert context["selected_ready_pair"]["trained_chara_ids"] == [11, 13]
    assert context["selected_ready_pair"]["aptitude_feasible"] is True
    assert context["selected_ready_pair"]["target_factor_valid"] is True
    assert context["selected_ready_pair"]["projected_displayed_affinity"] == 300


def test_v3_cycle_final_stage_excludes_weak_parent_even_with_higher_projected_affinity():
    campaign = _v3_campaign_for_cycle(final_stage_active=True)
    campaign["context"]["ready_parent_candidates"] = [
        {"candidate_id": "v11", "trained_chara_id": 11, "bootstrap_chara_id": 1001},
        {"candidate_id": "v12", "trained_chara_id": 12, "bootstrap_chara_id": 1002},
        {"candidate_id": "v13", "trained_chara_id": 13, "bootstrap_chara_id": 1003},
    ]
    store = FakeStore(campaign)
    runtime = _v3_runtime()
    runtime["display_by_id"][13] = deepcopy(runtime["display_by_id"][12])
    runtime["display_by_id"][13]["trained_chara_id"] = 13
    direct_scores = {1001: 9, 1002: 17, 1003: 15}

    def projected(_card_id, first, second, _saddles):
        pair = frozenset({first["trained_chara_id"], second["trained_chara_id"]})
        return {
            "total": {
                frozenset({11, 12}): 999,
                frozenset({11, 13}): 800,
                frozenset({12, 13}): 100,
            }[pair]
        }

    svc, _, _, _ = service(
        store=store,
        snapshot=lambda _account: runtime,
        projected_affinity=projected,
        direct_compatibility=lambda _final_card_id, chara_id: direct_scores[chara_id],
    )
    svc.candidate_pool = svc._default_candidates

    result = svc.prepare_next_run("cmp1")

    prepared = result["prepared_run"]
    context = store.campaign["context"]
    assert [row["trained_chara_id"] for row in prepared["legacy_slots"]] == [12, 13]
    assert context["selected_ready_pair"]["trained_chara_ids"] == [12, 13]
    assert context["selected_ready_pair"]["direct_base_compatibility"] == [17, 15]
    assert context["selected_ready_pair"]["projected_displayed_affinity"] == 100


def test_v3_cycle_final_direct_lineage_eight_stars_repeats_even_with_grandparent_power():
    campaign = _v3_campaign_for_cycle(final_stage_active=True)
    campaign["context"]["ready_parent_candidates"] = [
        {"candidate_id": "v11", "trained_chara_id": 11, "bootstrap_chara_id": 1001},
        {"candidate_id": "v12", "trained_chara_id": 12, "bootstrap_chara_id": 1002},
    ]
    store = FakeStore(campaign)
    svc, _, _, _ = service(store=store)

    result = svc.record_completed_veteran(
        "cmp1",
        {
            "candidate_id": "final-8",
            "trained_chara_id": 4001,
            "name": "Final Uma",
            "rank_score": 500,
            "factor_tree": {
                "self": {"factors": [{"category": "stat", "name": "Stamina", "stars": 2}]},
                "p1": {"factors": [{"category": "stat", "name": "Stamina", "stars": 3}]},
                "p2": {"factors": [{"category": "stat", "name": "Stamina", "stars": 3}]},
                "gp1": {"factors": [{"category": "stat", "name": "Stamina", "stars": 3}]},
            },
            "displayed_affinity": {"total": 999},
        },
        [],
    )

    assert result["campaign"]["state"] == "SELECTING_LINEAGE"
    assert result["campaign"]["context"]["bootstrap_rotation"]["final_stage_active"] is True
    assert result["campaign"]["context"]["bootstrap_rotation"]["final_repeat_count"] == 1
    assert result["candidate"]["evaluation"]["accepted"] is False
    assert result["candidate"]["evaluation"]["direct_lineage_spark_totals"] == {
        "blue:stamina": 8
    }


def test_v3_cycle_final_direct_lineage_nine_stars_completes():
    campaign = _v3_campaign_for_cycle(final_stage_active=True)
    campaign["context"]["ready_parent_candidates"] = [
        {"candidate_id": "v11", "trained_chara_id": 11, "bootstrap_chara_id": 1001},
        {"candidate_id": "v12", "trained_chara_id": 12, "bootstrap_chara_id": 1002},
    ]
    store = FakeStore(campaign)
    svc, _, _, _ = service(store=store)

    result = svc.record_completed_veteran(
        "cmp1",
        {
            "candidate_id": "final-9",
            "trained_chara_id": 4002,
            "name": "Final Uma",
            "rank_score": 600,
            "factor_tree": {
                "self": {"factors": [{"category": "stat", "name": "Stamina", "stars": 3}]},
                "p1": {"factors": [{"category": "stat", "name": "Stamina", "stars": 3}]},
                "p2": {"factors": [{"category": "stat", "name": "Stamina", "stars": 3}]},
                "gp1": {"factors": [{"category": "stat", "name": "Stamina", "stars": 3}]},
            },
            "displayed_affinity": {"total": 42},
        },
        [],
    )

    assert result["campaign"]["state"] == "COMPLETED"
    assert result["campaign"]["selected_candidate_id"] == "final-9"
    assert result["candidate"]["evaluation"]["accepted"] is True
    assert result["candidate"]["evaluation"]["direct_lineage_spark_totals"] == {
        "blue:stamina": 9
    }


def completed_candidate(affinity=150, required=9, preferred=0):
    return {
        "trained_chara_id": 501,
        "name": "Veteran",
        "spark_totals": {("blue", "stamina"): required, ("pink", "long"): preferred},
    }, [{"key": "pair", "affinity": affinity, "rental": False}]


def test_completed_candidate_persists_spark_snapshot():
    svc, _, *_ = service()
    candidate, pairings = completed_candidate(required=9, preferred=2)
    candidate["factor_tree"] = {
        "self": {
            "factors": [
                {"factor_id": 303, "category": "stat", "name": "Stamina", "stars": 3},
                {"factor_id": 2302, "category": "aptitude", "name": "Long", "stars": 2},
            ]
        }
    }

    result = svc.record_completed_veteran("cmp1", candidate, pairings)

    evaluation = result["candidate"]["evaluation"]
    assert evaluation["factor_tree"] == candidate["factor_tree"]
    assert evaluation["spark_totals"] == {
        "blue:stamina": 9,
        "pink:long": 2,
    }


def test_required_targets_and_affinity_exactly_150_complete():
    svc, store, *_ = service()
    candidate, _ = completed_candidate()
    pairings = [{"key": "pair", "rental": False}]
    result = svc.record_completed_veteran("cmp1", candidate, pairings)
    assert result["final_setup"]["status"] == "READY"
    assert store.campaign["state"] == "COMPLETED"
    assert store.campaign["selected_candidate_id"] == result["candidate"]["candidate_id"]
    assert store.campaign["context"]["rotation"]["run_index"] == 1
    assert result["candidate"]["evaluation"]["accepted"] is True


def test_ready_candidate_auto_continues_when_target_stop_is_disabled():
    svc, store, *_ = service()
    store.campaign["spec"]["strategy"]["stop_when_target_reached"] = False
    candidate, _ = completed_candidate()

    result = svc.record_completed_veteran(
        "cmp1",
        candidate,
        [{"key": "pair", "rental": False}],
    )

    assert result["final_setup"]["status"] == "READY"
    assert store.campaign["selected_candidate_id"] == result["candidate"]["candidate_id"]
    assert store.campaign["state"] == "SELECTING_LINEAGE"
    assert store.campaign["next_action"] == "prepare_next_run"
    assert store.campaign["context"]["required_target_achieved"] is True
    assert store.campaign["context"]["continue_preferred"] is True
    assert store.campaign["context"]["rotation"]["run_index"] == 1


def test_continue_preferred_context_keeps_future_ready_candidates_running():
    svc, store, *_ = service()
    store.campaign["context"]["continue_preferred"] = True
    candidate, _ = completed_candidate()

    svc.record_completed_veteran(
        "cmp1",
        candidate,
        [{"key": "pair", "rental": False}],
    )

    assert store.campaign["state"] == "SELECTING_LINEAGE"
    assert store.campaign["next_action"] == "prepare_next_run"
    assert store.campaign["context"]["continue_preferred"] is True


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
    assert store.campaign["state"] == "NEEDS_USER_INPUT"
    assert store.campaign["context"]["pending_review"]["kind"] == "candidate_tradeoff"
    assert runner.calls == []


def test_selected_candidate_is_current_best_even_when_historical_score_is_higher():
    svc, store, *_ = service()
    store.candidates.extend([
        {"candidate_id": "historical", "score": 999, "selected": False, "evaluation": {"required_progress": 1, "preferred_progress": 1, "best_affinity": 200}},
        {"candidate_id": "selected", "score": 1, "selected": True, "evaluation": {"required_progress": .5, "preferred_progress": 0, "best_affinity": 100}},
    ])
    store.campaign["selected_candidate_id"] = "selected"
    candidate, pairings = completed_candidate(affinity=140, required=8)
    result = svc.record_completed_veteran("cmp1", candidate, pairings)
    assert result["decision"] == "accept"


def test_domination_precedes_tradeoff_against_current_best():
    svc, store, *_ = service()
    store.candidates.extend([
        {"candidate_id": "best", "score": 2, "selected": True, "evaluation": {"required_progress": 1, "preferred_progress": 1, "best_affinity": 170}},
        {"candidate_id": "other", "score": 1, "selected": False, "evaluation": {"required_progress": 0, "preferred_progress": 0, "best_affinity": 0}},
    ])
    store.campaign["selected_candidate_id"] = "best"
    candidate, pairings = completed_candidate(affinity=150, required=8)
    result = svc.record_completed_veteran("cmp1", candidate, pairings)
    assert result["decision"] == "reject"


def test_record_replay_does_not_duplicate_candidate():
    svc, store, *_ = service()
    candidate, pairings = completed_candidate(affinity=100, required=8)
    candidate["candidate_id"] = "result-1"
    first = svc.record_completed_veteran("cmp1", candidate, pairings)
    second = svc.record_completed_veteran("cmp1", candidate, pairings)
    assert first["candidate"]["candidate_id"] == second["candidate"]["candidate_id"]
    assert len([row for row in store.candidates if row["candidate_id"] == "result-1"]) == 1


def test_changed_payload_replay_returns_stored_evaluation_only():
    svc, store, *_ = service()
    candidate, pairings = completed_candidate(affinity=100, required=8)
    candidate["candidate_id"] = "result-stable"
    first = svc.record_completed_veteran("cmp1", candidate, pairings)
    changed = {**candidate, "spark_totals": {("blue", "stamina"): 9}}
    second = svc.record_completed_veteran(
        "cmp1",
        changed,
        [{"key": "pair", "affinity": 200, "rental": False}],
    )
    stored = first["candidate"]["evaluation"]
    assert second["decision"] == stored["decision"]
    assert second["targets"] == stored["targets"]
    assert second["final_setup"] == stored["final_setup"]
    assert len(store.candidates) == 1


def test_tradeoff_allows_keeping_current_selected_candidate():
    svc, store, *_ = service()
    store.campaign.update({
        "state": "NEEDS_USER_INPUT",
        "next_action": "select_candidate",
        "selected_candidate_id": "candidate-current",
        "context": {
            "pending_review": {
                "kind": "candidate_tradeoff",
                "candidate_id": "candidate-challenger",
            }
        },
    })
    store.candidates.extend([
        {
            "candidate_id": "candidate-current",
            "score": 100,
            "selected": True,
            "evaluation": {"accepted": True, "final_setup": {"status": "READY"}},
        },
        {
            "candidate_id": "candidate-challenger",
            "score": 110,
            "selected": False,
            "evaluation": {"accepted": False, "final_setup": {"status": "IN_PROGRESS"}},
        },
    ])

    result = svc.select_candidate("cmp1", "candidate-current")

    assert result["candidate"]["candidate_id"] == "candidate-current"
    assert result["candidate"]["selected"] is True


def test_select_candidate_uses_stored_final_setup_semantics():
    svc, store, runner, _ = service()
    store.campaign["state"] = "NEEDS_USER_INPUT"
    store.campaign["next_action"] = "select_candidate"
    store.campaign["context"] = {
        "pending_review": {"kind": "candidate_tradeoff", "candidate_id": "candidate-ready"}
    }
    store.candidates.append({
        "candidate_id": "candidate-ready",
        "score": 1,
        "selected": False,
        "evaluation": {"accepted": True, "final_setup": {"status": "READY"}},
    })
    result = svc.select_candidate("cmp1", "candidate-ready")
    assert result["campaign"]["state"] == "COMPLETED"
    assert result["candidate"]["selected"] is True
    assert runner.calls == []


@pytest.mark.parametrize(
    "state,next_action,review",
    [
        ("COMPLETED", "", {"kind": "candidate_tradeoff", "candidate_id": "candidate-ready"}),
        ("NEEDS_USER_INPUT", "approve_run", {"kind": "prepared_run"}),
        ("NEEDS_USER_INPUT", "select_candidate", {"kind": "candidate_tradeoff", "candidate_id": "other"}),
    ],
)
def test_select_candidate_rejects_unrelated_state_or_review(state, next_action, review):
    svc, store, *_ = service()
    store.campaign.update({"state": state, "next_action": next_action})
    store.campaign["context"] = {"pending_review": review}
    store.candidates.append({
        "candidate_id": "candidate-ready",
        "score": 1,
        "selected": False,
        "evaluation": {"accepted": True, "final_setup": {"status": "READY"}},
    })
    with pytest.raises(ValueError, match="candidate selection review"):
        svc.select_candidate("cmp1", "candidate-ready")


def test_simple_runner_delegations():
    svc, _, runner, _ = service()
    assert svc.continue_for_preferred("cmp1") == {"campaign_id": "cmp1"}
    assert svc.pause("cmp1") == {"state": "PAUSED"}
    assert svc.resume("cmp1") == {"state": "SELECTING_LINEAGE"}
    assert svc.cancel("cmp1", "done") == {"state": "CANCELLED"}
    assert runner.calls[-4:] == [
        ("continue_for_preferred", "cmp1"),
        ("pause", "cmp1"),
        ("resume", "cmp1"),
        ("cancel", "cmp1", "done"),
    ]
