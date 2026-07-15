from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from typing import Any

from .final_setup import READY, READY_WITH_RENTAL, evaluate_final_setup
from .models import CampaignState, ParentCampaignSpec, SparkPriority
from .planner import CampaignPlanner
from .resolver import LegacyResolver, LegacySlot
from .rotation import RotationState, advance_rotation
from .targets import evaluate_spark_targets


class CampaignService:
    """Dependency-injected application layer for parent campaigns."""

    def __init__(
        self,
        *,
        store: Any,
        runner: Any,
        preset_store: Any,
        runtime_snapshot: Callable[..., dict[str, Any]],
        affinity_for_setup: Callable[..., Any],
        start_career: Callable[[dict[str, Any]], Any],
        planner_factory: Callable[[Mapping[str, Any]], Any] | None = None,
        planned_slots: Callable[..., Sequence[Mapping[str, Any]]] | None = None,
        candidate_pool: Callable[..., Sequence[Mapping[str, Any]]] | None = None,
        race_overrides: Callable[..., Sequence[Any]] | None = None,
        career_request: Callable[..., dict[str, Any]] | None = None,
    ) -> None:
        self.store = store
        self.runner = runner
        self.preset_store = preset_store
        self.runtime_snapshot = runtime_snapshot
        self.affinity_for_setup = affinity_for_setup
        self.start_career = start_career
        self.planner_factory = planner_factory or self._default_planner
        self.planned_slots = planned_slots or self._default_slots
        self.candidate_pool = candidate_pool or self._default_candidates
        self.race_overrides = race_overrides or self._default_races
        self.career_request = career_request or self._default_career_request

    def list_campaigns(self, account: str) -> list[dict[str, Any]]:
        return self.store.list(account=account)

    def get_campaign(self, campaign_id: str) -> dict[str, Any]:
        return self.store.get(campaign_id)

    def recommend_final_parents(self, request: Mapping[str, Any]) -> Any:
        payload = dict(request)
        planner = self.planner_factory(payload)
        return planner.recommend_final_parents(limit=int(payload.get("limit", 3)))

    def recommend_loops(self, request: Mapping[str, Any]) -> Any:
        payload = dict(request)
        planner = self.planner_factory(payload)
        kwargs = {"limit": int(payload.get("limit", 3))}
        if "pinned_chara_ids" in payload:
            kwargs["pinned_chara_ids"] = set(payload["pinned_chara_ids"])
        if "mdb_path" in payload:
            kwargs["mdb_path"] = payload["mdb_path"]
        return planner.recommend_loops(**kwargs)

    def create_campaign(self, spec: ParentCampaignSpec | Mapping[str, Any]) -> dict[str, Any]:
        validated = ParentCampaignSpec.model_validate(spec)
        if validated.final_uma.card_id <= 0:
            raise ValueError("final_uma.card_id must be positive for Web campaigns")
        if not any(row.priority is SparkPriority.REQUIRED for row in validated.spark_targets):
            raise ValueError("at least one required spark target is required")
        if len(validated.loop_members) != 4:
            raise ValueError("loop_members must contain exactly four members")
        if any(not 1 <= row.deck_id <= 10 for row in validated.loop_members):
            raise ValueError("each manual loop member deck_id must be between 1 and 10")
        return self.store.create(validated)

    def activate(self, campaign_id: str) -> dict[str, Any]:
        campaign = self.store.get(campaign_id)
        snapshot = self._snapshot(campaign["account"])
        runtime = snapshot.get("runtime", snapshot)
        bot_state = snapshot.get("bot_state", snapshot)
        return self.runner.start(campaign_id, runtime=runtime, bot_state=bot_state)

    def pause(self, campaign_id: str) -> dict[str, Any]:
        return self.runner.pause(campaign_id)

    def resume(self, campaign_id: str) -> dict[str, Any]:
        return self.runner.resume(campaign_id)

    def prepare_next_run(self, campaign_id: str) -> dict[str, Any]:
        campaign = self.store.get(campaign_id)
        runtime = self._snapshot(campaign["account"])
        context = dict(campaign.get("context") or {})
        rotation = self._rotation(campaign)
        resolver = LegacyResolver(allow_rental=bool(campaign["spec"]["options"]["allow_rental"]))
        candidates = [dict(row) for row in self.candidate_pool(campaign, rotation, runtime)]
        resolved = [
            resolver.resolve_slot(LegacySlot(**dict(slot)), candidates=candidates)
            for slot in self.planned_slots(campaign, rotation, runtime)
        ]
        races = list(self.race_overrides(campaign, rotation, runtime))
        request = self.career_request(campaign, rotation, resolved, races, runtime)
        replacements = [row for row in resolved if row.get("replacement")]
        auto = bool(campaign["spec"]["options"].get("auto_use_best_veteran", False))
        audit_events = list(context.get("audit_events") or [])
        audit_events.extend(
            {"event": "legacy_replaced", "role": row.get("role"), "details": row}
            for row in replacements
        )
        review = {"prepared_run": request, "resolved_slots": resolved, "replacements": replacements}
        updates = {
            "rotation": rotation.to_dict(),
            "prepared_run": request,
            "pending_review": False if auto else True,
            "audit_events": audit_events,
            "approval_started": False,
        }
        persisted = self.store.update_context(campaign_id, updates)
        if auto:
            persisted = self.store.set_next_action(campaign_id, "start_career")
        else:
            persisted = self.runner.require_user_input(campaign_id, "approve_run", review)
        return {"campaign": persisted, "prepared_run": request, "resolved_slots": resolved}

    def approve_run(
        self,
        campaign_id: str,
        selection_override: Mapping[str, Any] | None = None,
    ) -> Any:
        campaign = self.store.get(campaign_id)
        context = dict(campaign.get("context") or {})
        if context.get("approval_started"):
            return context.get("start_result")
        request = deepcopy(context.get("prepared_run"))
        if not isinstance(request, dict):
            raise ValueError("campaign has no persisted prepared_run")
        if selection_override:
            request.update(deepcopy(dict(selection_override)))
        self.store.update_context(
            campaign_id,
            {"prepared_run": request, "pending_review": False, "approval_started": True},
        )
        result = self.start_career(request)
        self.store.update_context(campaign_id, {"start_result": result})
        return result

    def record_completed_veteran(
        self,
        campaign_id: str,
        candidate: Mapping[str, Any],
        final_pairings: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        campaign = self.store.get(campaign_id)
        spec = campaign["spec"]
        target_result = evaluate_spark_targets(spec["spark_targets"], candidate.get("spark_totals", {}))
        evaluated_pairings = [
            self._pairing_with_affinity(spec, candidate, pairing)
            for pairing in final_pairings
        ]
        final_result = evaluate_final_setup(
            target_result["required_complete"],
            evaluated_pairings,
            bool(spec["options"].get("allow_rental", False)),
        )
        evaluation = {
            "required_progress": target_result["required_progress"],
            "preferred_progress": target_result["preferred_progress"],
            "best_affinity": final_result["best_affinity"],
            "targets": target_result,
            "final_setup": final_result,
        }
        previous = self.store.list_candidates(campaign_id)
        decision = self._candidate_decision(evaluation, previous)
        score = (
            evaluation["required_progress"] * 1000
            + evaluation["preferred_progress"] * 100
            + evaluation["best_affinity"]
        )
        stored = self.store.add_candidate(
            campaign_id,
            trained_chara_id=int(candidate.get("trained_chara_id") or 0),
            name=str(candidate.get("name") or ""),
            score=score,
            evaluation={**evaluation, "decision": decision},
        )
        can_complete = final_result["status"] == READY or (
            final_result["status"] == READY_WITH_RENTAL
            and bool(spec["options"].get("allow_rental", False))
        )
        if can_complete:
            campaign = self.store.transition(campaign_id, CampaignState.COMPLETED, next_action="")
        elif decision == "tradeoff":
            campaign = self.runner.require_user_input(
                campaign_id,
                "select_candidate",
                {"candidate": stored, "evaluation": evaluation},
            )
        else:
            rotation = advance_rotation(
                self._rotation(campaign),
                produced_legacy_id=str(candidate.get("trained_chara_id") or stored["candidate_id"]),
            )
            self.store.update_context(campaign_id, {"rotation": rotation.to_dict()})
            campaign = self.store.transition(
                campaign_id,
                CampaignState.SELECTING_LINEAGE,
                next_action="prepare_next_run",
            )
        return {
            "campaign": campaign,
            "candidate": stored,
            "decision": decision,
            "targets": target_result,
            "final_setup": final_result,
        }

    def select_candidate(self, campaign_id: str, candidate_id: str) -> dict[str, Any]:
        return self.runner.select_candidate(campaign_id, candidate_id)

    def continue_for_preferred(self, campaign_id: str) -> dict[str, Any]:
        return self.runner.continue_for_preferred(campaign_id)

    def cancel(self, campaign_id: str, reason: str = "") -> dict[str, Any]:
        return self.runner.cancel(campaign_id, reason=reason)

    def _snapshot(self, account: str) -> dict[str, Any]:
        try:
            return self.runtime_snapshot(account)
        except TypeError:
            return self.runtime_snapshot()

    @staticmethod
    def _rotation(campaign: Mapping[str, Any]) -> RotationState:
        context = campaign.get("context") or {}
        saved = context.get("rotation") if isinstance(context, Mapping) else None
        if isinstance(saved, Mapping):
            return RotationState(**dict(saved))
        members = campaign["spec"]["loop_members"]
        return RotationState.bootstrap([int(row["chara_id"]) for row in members])

    @staticmethod
    def _candidate_decision(evaluation: Mapping[str, Any], previous: Sequence[Mapping[str, Any]]) -> str:
        dimensions = ("required_progress", "preferred_progress", "best_affinity")
        current = tuple(float(evaluation[key]) for key in dimensions)
        for row in previous:
            old = row.get("evaluation") or {}
            prior = tuple(float(old.get(key, 0)) for key in dimensions)
            if all(left <= right for left, right in zip(current, prior)) and any(
                left < right for left, right in zip(current, prior)
            ):
                return "reject"
            if any(left > right for left, right in zip(current, prior)) and any(
                left < right for left, right in zip(current, prior)
            ):
                return "tradeoff"
        return "accept"

    def _pairing_with_affinity(
        self,
        spec: Mapping[str, Any],
        candidate: Mapping[str, Any],
        pairing: Mapping[str, Any],
    ) -> dict[str, Any]:
        row = dict(pairing)
        if any(key in row for key in ("affinity", "total_affinity", "score")):
            return row
        affinity = self.affinity_for_setup(spec["final_uma"], candidate, row)
        if isinstance(affinity, Mapping):
            affinity = affinity.get("total", affinity.get("affinity", 0))
        row["affinity"] = int(affinity or 0)
        return row

    @staticmethod
    def _default_planner(request: Mapping[str, Any]) -> CampaignPlanner:
        return CampaignPlanner(**{key: value for key, value in request.items() if key != "limit"})

    @staticmethod
    def _default_slots(campaign: Mapping[str, Any], _rotation: RotationState, _runtime: Mapping[str, Any]) -> list[dict[str, Any]]:
        target = campaign["spec"].get("final_parent") or {}
        trained_id = int(target.get("trained_chara_id") or 0)
        return [{"role": "parent1", "mode": "LOCKED" if trained_id else "FLEXIBLE", "trained_chara_id": trained_id}]

    @staticmethod
    def _default_candidates(campaign: Mapping[str, Any], rotation: RotationState, runtime: Mapping[str, Any]) -> list[dict[str, Any]]:
        context = campaign.get("context") or {}
        rows = [
            *(runtime.get("owned_candidates") or []),
            *(context.get("campaign_candidates") or []),
            *(runtime.get("rental_candidates") or []),
        ]
        return [dict(row) for row in rows]

    @staticmethod
    def _default_races(campaign: Mapping[str, Any], _rotation: RotationState, _runtime: Mapping[str, Any]) -> list[Any]:
        return list((campaign.get("context") or {}).get("step_race_overrides") or [])

    def _default_career_request(
        self,
        campaign: Mapping[str, Any],
        rotation: RotationState,
        resolved: Sequence[Mapping[str, Any]],
        races: Sequence[Any],
        _runtime: Mapping[str, Any],
    ) -> dict[str, Any]:
        spec = campaign["spec"]
        return {
            "account": campaign["account"],
            "preset": self.preset_store.load(spec["strategy"]["preset_name"]),
            "trainee_chara_id": rotation.next_trainee_chara_id,
            "legacy_slots": list(resolved),
            "race_overrides": list(races),
            "campaign_id": campaign["campaign_id"],
        }


__all__ = ["CampaignService"]
