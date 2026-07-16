from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
import hashlib
import json
from typing import Any

from .final_setup import READY, READY_WITH_RENTAL, evaluate_final_setup
from .models import CampaignState, ParentCampaignSpec, SparkPriority
from .planner import CampaignPlanner
from .preset_policy import build_campaign_base_preset, build_step_overrides
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
        race_overrides: Callable[..., Any] | None = None,
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
        campaign = self.store.get(campaign_id)
        return {
            **campaign,
            "events": self.store.recent_events(campaign_id, limit=30),
            "candidates": self.store.list_candidates(campaign_id, limit=30),
        }

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
        if isinstance(spec, Mapping):
            self._reject_boolean_integer_fields(spec)
        validated = ParentCampaignSpec.model_validate(spec)
        if validated.final_uma.card_id <= 0:
            raise ValueError("final_uma.card_id must be positive for Web campaigns")
        if not any(row.priority is SparkPriority.REQUIRED for row in validated.spark_targets):
            raise ValueError("at least one required spark target is required")
        if len(validated.loop_members) != 4:
            raise ValueError("loop_members must contain exactly four members")
        if any(not 1 <= row.deck_id <= 10 for row in validated.loop_members):
            raise ValueError("each manual loop member deck_id must be between 1 and 10")
        base_preset_name = validated.strategy.preset_name
        base_preset = deepcopy(self.preset_store.load(base_preset_name))
        digest = hashlib.sha256(
            json.dumps(validated.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()[:10]
        generated_name = f"campaign-{validated.account.lower()}-{digest}"
        policy = build_campaign_base_preset(
            name=generated_name,
            running_style=base_preset.get("running_style"),
            scenario_id=base_preset.get("scenario_id"),
            spark_targets=validated.spark_targets,
            core_races=validated.race_plan.core,
            optional_races=validated.race_plan.optional,
        )
        generated = {**base_preset, **policy}
        for key in ("deck", "deck_id", "support_card_ids", "support_card_id_array"):
            generated.pop(key, None)
        stats = list(base_preset.get("expect_attribute") or [0, 0, 0, 0, 0])[:5]
        stats += [0] * (5 - len(stats))
        for index, name in enumerate(("speed", "stamina", "power", "guts", "wisdom")):
            if f"expect_{name}" in policy:
                stats[index] = max(int(stats[index]), int(policy[f"expect_{name}"]))
            generated.pop(f"expect_{name}", None)
        generated["expect_attribute"] = stats
        self.preset_store.save(generated)
        validated.strategy.preset_name = generated_name
        initial_context = {
            "base_preset_name": base_preset_name,
            "generated_preset_name": generated_name,
            "race_agenda": {
                "CORE": list(validated.race_plan.core),
                "OPTIONAL": list(validated.race_plan.optional),
                "DEFERABLE": list(validated.race_plan.deferable),
            },
            "step_race_overrides": build_step_overrides(
                core_races=validated.race_plan.core,
                optional_races=validated.race_plan.optional,
                parent_run=True,
            ),
        }
        return self.store.create(validated, initial_context=initial_context)

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

    def reconcile_runtime(
        self,
        campaign_id: str,
        current_career: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        campaign = self.store.get(campaign_id)
        current = dict(current_career or {})
        prepared_run = dict((campaign.get("context") or {}).get("prepared_run") or {})
        if bool(current.get("active")):
            if self._career_matches_prepared_run(current, prepared_run):
                return self.store.transition(
                    campaign_id,
                    CampaignState.RUNNING_CAREER,
                    next_action="monitor_career",
                )
            error = "Current active career does not match the persisted prepared run"
            self.store.append_event(
                campaign_id,
                "runtime_reconciliation_mismatch",
                {"error": error},
            )
            return self.store.transition(
                campaign_id,
                CampaignState.PAUSED,
                next_action="inspect_current_career",
                error=error,
                context_updates={"runtime_reconciliation": {"status": "MISMATCH"}},
            )

        if campaign["state"] == CampaignState.RUNNING_CAREER.value:
            self.store.transition(
                campaign_id,
                CampaignState.SELECTING_LINEAGE,
                next_action="prepare_next_run",
            )
        recovered = self.prepare_next_run(campaign_id)
        unresolved = [
            row for row in recovered.get("resolved_slots", [])
            if row.get("status") != "RESOLVED"
        ]
        if any("locked veteran unavailable" in str(row.get("reason") or "") for row in unresolved):
            recovered["campaign"] = self.store.transition(
                campaign_id,
                CampaignState.NEEDS_USER_INPUT,
                next_action="resolve_missing_locked_veteran",
                error="Persisted locked veteran is unavailable",
            )
        elif unresolved and self._prepared_run_used_rental(prepared_run):
            recovered["campaign"] = self.store.transition(
                campaign_id,
                CampaignState.NEEDS_USER_INPUT,
                next_action="review_unavailable_rental",
                error="Persisted rental is unavailable and no valid fallback was found",
            )
        return recovered

    def prepare_next_run(self, campaign_id: str) -> dict[str, Any]:
        campaign = self.store.get(campaign_id)
        runtime = self._snapshot(campaign["account"])
        rotation = self._rotation(campaign)
        resolver = LegacyResolver(allow_rental=bool(campaign["spec"]["options"]["allow_rental"]))
        candidates = [dict(row) for row in self.candidate_pool(campaign, rotation, runtime)]
        resolved = [
            resolver.resolve_slot(LegacySlot(**dict(slot)), candidates=candidates)
            for slot in self.planned_slots(campaign, rotation, runtime)
        ]
        unresolved = [row for row in resolved if row.get("status") != "RESOLVED"]
        if unresolved:
            review = {
                "kind": "unresolved_legacy_slots",
                "unresolved_slots": unresolved,
                "resolved_slots": resolved,
            }
            persisted = self.store.update_context(
                campaign_id,
                {
                    "rotation": rotation.to_dict(),
                    "prepared_run": None,
                    "prepared_run_id": None,
                    "pending_review": review,
                    "review_required": True,
                    "run_start": None,
                },
            )
            persisted = self.runner.require_user_input(
                campaign_id,
                "prepare_next_run",
                review,
            )
            return {"campaign": persisted, "prepared_run": None, "resolved_slots": resolved}
        races = deepcopy(self.race_overrides(campaign, rotation, runtime))
        request = self.career_request(campaign, rotation, resolved, races, runtime)
        prepared_run_id = self._stable_id("prepared", request)
        replacements = [row for row in resolved if row.get("replacement")]
        auto = bool(campaign["spec"]["options"].get("auto_use_best_veteran", False))
        review = {
            "kind": "prepared_run",
            "prepared_run_id": prepared_run_id,
            "prepared_run": request,
            "resolved_slots": resolved,
            "replacements": replacements,
        }
        updates = {
            "rotation": rotation.to_dict(),
            "prepared_run": request,
            "prepared_run_id": prepared_run_id,
            "pending_review": None if auto else review,
            "review_required": not auto,
            "run_start": None,
        }
        persisted = self.store.update_context(campaign_id, updates)
        if auto:
            for replacement in replacements:
                self.store.append_event(
                    campaign_id,
                    "automatic_legacy_replacement",
                    {"prepared_run_id": prepared_run_id, "replacement": replacement},
                )
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
        request = deepcopy(context.get("prepared_run"))
        if not isinstance(request, dict):
            raise ValueError("campaign has no persisted prepared_run")
        if selection_override:
            allowed = {"race_overrides", "legacy_slots", "friend_support"}
            unknown = set(selection_override) - allowed
            if unknown:
                raise ValueError(f"unsupported selection override fields: {sorted(unknown)}")
            request.update(deepcopy(dict(selection_override)))
        operation_id = self._stable_id("prepared-start", request)
        reservation = self.store.reserve_prepared_run_start(
            campaign_id,
            operation_id,
            prepared_run=request,
        )
        if not reservation["acquired"]:
            run_start = reservation["run_start"]
            if run_start["status"] == "STARTED":
                return run_start.get("result")
            return {
                "status": "STARTING",
                "operation_id": run_start["operation_id"],
            }
        try:
            result = self.start_career(request)
        except Exception as exc:
            self.store.finish_prepared_run_start(
                campaign_id,
                operation_id,
                status="FAILED",
                error=str(exc),
            )
            raise
        self.store.finish_prepared_run_start(
            campaign_id,
            operation_id,
            status="STARTED",
            result=result,
        )
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
        current_best = self._current_best(campaign, previous)
        decision = self._candidate_decision(evaluation, current_best)
        can_complete = final_result["status"] == READY or (
            final_result["status"] == READY_WITH_RENTAL
            and bool(spec["options"].get("allow_rental", False))
        )
        evaluation["accepted"] = can_complete
        evaluation["decision"] = decision
        score = (
            evaluation["required_progress"] * 1000
            + evaluation["preferred_progress"] * 100
            + evaluation["best_affinity"]
        )
        candidate_id = str(candidate.get("candidate_id") or self._stable_id(
            "candidate",
            {"candidate": dict(candidate), "pairings": list(final_pairings)},
        ))
        context_updates: dict[str, Any] = {"pending_review": None, "review_required": False}
        if can_complete:
            target_state = CampaignState.COMPLETED
            next_action = ""
            select = True
        elif decision == "tradeoff":
            target_state = CampaignState.NEEDS_USER_INPUT
            next_action = "select_candidate"
            select = False
            context_updates = {
                "pending_review": {
                    "kind": "candidate_tradeoff",
                    "candidate_id": candidate_id,
                    "evaluation": evaluation,
                },
                "review_required": True,
            }
        else:
            rotation = advance_rotation(
                self._rotation(campaign),
                produced_legacy_id=str(candidate.get("trained_chara_id") or candidate_id),
            )
            context_updates["rotation"] = rotation.to_dict()
            target_state = CampaignState.SELECTING_LINEAGE
            next_action = "prepare_next_run"
            select = False
        persisted = self.store.persist_candidate_result(
            campaign_id,
            candidate_id=candidate_id,
            trained_chara_id=int(candidate.get("trained_chara_id") or 0),
            name=str(candidate.get("name") or ""),
            score=score,
            evaluation=evaluation,
            select=select,
            state=target_state,
            next_action=next_action,
            context_updates=context_updates,
            expected_version=campaign.get("version"),
        )
        if persisted.get("replayed"):
            stored_evaluation = persisted["candidate"].get("evaluation") or {}
            return {
                "campaign": persisted["campaign"],
                "candidate": persisted["candidate"],
                "decision": stored_evaluation.get("decision", "accept"),
                "targets": stored_evaluation.get("targets", {}),
                "final_setup": stored_evaluation.get("final_setup", {}),
            }
        return {
            "campaign": persisted["campaign"],
            "candidate": persisted["candidate"],
            "decision": decision,
            "targets": target_result,
            "final_setup": final_result,
        }

    def select_candidate(self, campaign_id: str, candidate_id: str) -> dict[str, Any]:
        campaign = self.store.get(campaign_id)
        candidate = self.store.get_candidate(campaign_id, candidate_id)
        evaluation = candidate.get("evaluation") or {}
        final_status = (evaluation.get("final_setup") or {}).get("status")
        allow_rental = bool(campaign["spec"]["options"].get("allow_rental", False))
        complete = final_status == READY or (
            final_status == READY_WITH_RENTAL and allow_rental
        )
        return self.store.apply_candidate_selection(
            campaign_id,
            candidate_id,
            state=CampaignState.COMPLETED if complete else CampaignState.SELECTING_LINEAGE,
            next_action="" if complete else "prepare_next_run",
            context_updates={"pending_review": None, "review_required": False},
        )

    def continue_for_preferred(self, campaign_id: str) -> dict[str, Any]:
        return self.runner.continue_for_preferred(campaign_id)

    def cancel(self, campaign_id: str, reason: str = "") -> dict[str, Any]:
        return self.runner.cancel(campaign_id, reason=reason)

    def _snapshot(self, account: str) -> dict[str, Any]:
        return self.runtime_snapshot(account)

    @staticmethod
    def _reject_boolean_integer_fields(spec: Mapping[str, Any]) -> None:
        scalar_paths = (
            ("spec_version",),
            ("trainee", "card_id"),
            ("deck", "deck_id"),
            ("final_uma", "card_id"),
            ("final_parent", "chara_id"),
            ("final_parent", "trained_chara_id"),
            ("strategy", "maximum_runs"),
            ("strategy", "maximum_carats"),
            ("strategy", "maximum_clocks"),
        )
        for path in scalar_paths:
            value: Any = spec
            for part in path:
                if not isinstance(value, Mapping) or part not in value:
                    break
                value = value[part]
            else:
                if isinstance(value, bool):
                    raise ValueError(f"{'.'.join(path)} must be an integer")
        for collection, fields in (
            ("loop_members", ("chara_id", "deck_id")),
            ("spark_targets", ("minimum_stars",)),
        ):
            for index, row in enumerate(spec.get(collection) or []):
                if not isinstance(row, Mapping):
                    continue
                for field in fields:
                    if isinstance(row.get(field), bool):
                        raise ValueError(
                            f"{collection}[{index}].{field} must be an integer"
                        )
        goal = spec.get("goal")
        if isinstance(goal, Mapping):
            for index, row in enumerate(goal.get("target_factors") or []):
                if isinstance(row, Mapping) and isinstance(row.get("minimum_stars"), bool):
                    raise ValueError(
                        f"goal.target_factors[{index}].minimum_stars must be an integer"
                    )

    @staticmethod
    def _rotation(campaign: Mapping[str, Any]) -> RotationState:
        context = campaign.get("context") or {}
        saved = context.get("rotation") if isinstance(context, Mapping) else None
        if isinstance(saved, Mapping):
            return RotationState(**dict(saved))
        members = campaign["spec"]["loop_members"]
        return RotationState.bootstrap([int(row["chara_id"]) for row in members])

    @staticmethod
    def _current_best(
        campaign: Mapping[str, Any],
        previous: Sequence[Mapping[str, Any]],
    ) -> Mapping[str, Any] | None:
        selected_id = str(campaign.get("selected_candidate_id") or "")
        if selected_id:
            selected = next(
                (row for row in previous if row.get("candidate_id") == selected_id),
                None,
            )
            if selected is not None:
                return selected
        return previous[0] if previous else None

    @staticmethod
    def _candidate_decision(
        evaluation: Mapping[str, Any],
        previous: Mapping[str, Any] | None,
    ) -> str:
        dimensions = ("required_progress", "preferred_progress", "best_affinity")
        current = tuple(float(evaluation[key]) for key in dimensions)
        if previous is None:
            return "accept"
        old = previous.get("evaluation") or {}
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

    @staticmethod
    def _stable_id(prefix: str, value: Any) -> str:
        encoded = repr(value)
        return f"{prefix}-{hashlib.sha256(encoded.encode()).hexdigest()[:24]}"

    @classmethod
    def _career_matches_prepared_run(
        cls,
        current_career: Mapping[str, Any],
        prepared_run: Mapping[str, Any],
    ) -> bool:
        expected = prepared_run.get("career_request") or prepared_run
        if not isinstance(expected, Mapping):
            return False
        expected_card = cls._career_card_id(expected)
        if expected_card:
            if cls._career_card_id(current_career) != expected_card:
                return False
        else:
            expected_trainee = int(expected.get("trainee_chara_id") or 0)
            if not expected_trainee or int(current_career.get("trainee_chara_id") or 0) != expected_trainee:
                return False
        for key in ("deck_id", "parent_id_1", "parent_id_2"):
            expected_value = int(expected.get(key) or 0)
            if expected_value and int(current_career.get(key) or 0) != expected_value:
                return False
        return True

    @staticmethod
    def _career_card_id(career: Mapping[str, Any]) -> int:
        trainee = career.get("trainee")
        nested = trainee.get("card_id") if isinstance(trainee, Mapping) else 0
        return int(career.get("card_id") or career.get("trainee_card_id") or nested or 0)

    @staticmethod
    def _prepared_run_used_rental(prepared_run: Mapping[str, Any]) -> bool:
        request = prepared_run.get("career_request") or prepared_run
        if not isinstance(request, Mapping):
            return False
        slots = request.get("legacy_slots") or request.get("parents") or []
        return any(isinstance(row, Mapping) and row.get("rental") is True for row in slots)

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
    def _default_races(campaign: Mapping[str, Any], _rotation: RotationState, _runtime: Mapping[str, Any]) -> Any:
        return deepcopy((campaign.get("context") or {}).get("step_race_overrides") or [])

    def _default_career_request(
        self,
        campaign: Mapping[str, Any],
        rotation: RotationState,
        resolved: Sequence[Mapping[str, Any]],
        races: Any,
        _runtime: Mapping[str, Any],
    ) -> dict[str, Any]:
        spec = campaign["spec"]
        members = spec.get("loop_members") or []
        member = next((row for row in members if int(row.get("chara_id") or 0) == rotation.next_trainee_chara_id), None)
        deck_id = int((member or {}).get("deck_id") or 0)
        if not member or not 1 <= deck_id <= 10:
            raise ValueError(f"No valid manual deck for trainee {rotation.next_trainee_chara_id}")
        return {
            "account": campaign["account"],
            "preset": self.preset_store.load(spec["strategy"]["preset_name"]),
            "trainee_chara_id": rotation.next_trainee_chara_id,
            "deck_id": deck_id,
            "legacy_slots": list(resolved),
            "race_overrides": deepcopy(dict(races) if isinstance(races, Mapping) else list(races)),
            "campaign_id": campaign["campaign_id"],
        }


__all__ = ["CampaignService"]
