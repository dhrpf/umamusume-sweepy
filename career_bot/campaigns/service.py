from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from math import isfinite
from numbers import Real
from typing import Any

from career_bot.affinity import card_to_chara_id

from .aptitude_planner import generate_aptitude_targets
from .cycle import (
    CampaignCycleState,
    advance_bootstrap_rotation,
    enter_final_stage,
    migrate_stage_state_to_cycle,
    record_final_repeat,
)
from .factor_semantics import (
    direct_lineage_spark_totals,
    parent_pair_targets,
    ready_parent_targets,
    self_spark_totals,
)
from .final_setup import READY, READY_WITH_RENTAL, evaluate_final_setup
from .friend_support import find_trainee_deck_conflicts
from .models import ApprovalMode, CampaignState, ParentCampaignSpec, SparkPriority
from .legacy.race_planner import build_displayed_affinity_agenda
from .parent_pairs import direct_pair_compatible, rank_parent_pairs
from .planner import CampaignPlanner
from .preset_policy import build_campaign_base_preset, build_step_overrides
from .resolver import LegacyResolver, LegacySlot
from .rotation import RotationState, advance_rotation
from .stages import (
    CampaignStageState,
    build_stage_goal_assignments,
    migrate_legacy_rotation,
    record_stage_result,
)
from .targets import evaluate_spark_targets


@dataclass(frozen=True)
class _StageRunView:
    next_trainee_chara_id: int
    stage_index: int
    available_legacy_ids: tuple[str, ...] = ()


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
        projected_affinity_for_pair: Callable[..., Any] | None = None,
        direct_compatibility_for_parent: Callable[[int, int], Any] | None = None,
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
        self.projected_affinity_for_pair = projected_affinity_for_pair
        self.direct_compatibility_for_parent = direct_compatibility_for_parent
        self.start_career = start_career
        self.planner_factory = planner_factory or self._default_planner
        self.planned_slots = planned_slots or self._default_slots
        self.candidate_pool = candidate_pool or self._default_candidates
        self.race_overrides = race_overrides or self._default_races
        self.career_request = career_request or self._default_career_request

    def _direct_compatibility_score(
        self,
        final_card_id: int,
        parent_chara_id: int,
    ) -> int:
        scorer = self.direct_compatibility_for_parent
        if not callable(scorer):
            return 0
        final_card_id = self._integer_identity(final_card_id)
        parent_chara_id = self._integer_identity(parent_chara_id)
        if final_card_id <= 0 or parent_chara_id <= 0:
            return 0
        return self._integer_identity(scorer(final_card_id, parent_chara_id))

    def _compatible_chara_pairs(
        self,
        final_card_id: int,
        chara_ids: Sequence[int],
    ) -> list[tuple[int, int]] | None:
        if not callable(self.direct_compatibility_for_parent):
            return None
        normalized = sorted({
            self._integer_identity(chara_id)
            for chara_id in chara_ids
            if self._integer_identity(chara_id) > 0
        })
        scores = {
            chara_id: self._direct_compatibility_score(final_card_id, chara_id)
            for chara_id in normalized
        }
        return [
            (first, second)
            for index, first in enumerate(normalized)
            for second in normalized[index + 1:]
            if direct_pair_compatible(scores[first], scores[second])
        ]

    def _ready_parent_with_compatibility(
        self,
        spec: Mapping[str, Any],
        row: Mapping[str, Any],
    ) -> dict[str, Any]:
        result = deepcopy(dict(row))
        if "direct_base_compatibility" in result:
            score = self._integer_identity(result.get("direct_base_compatibility"))
        else:
            final_uma = spec.get("final_uma") if isinstance(spec, Mapping) else {}
            final_uma = final_uma if isinstance(final_uma, Mapping) else {}
            score = self._direct_compatibility_score(
                self._integer_identity(final_uma.get("card_id")),
                self._integer_identity(result.get("bootstrap_chara_id")),
            )
        result["direct_base_compatibility"] = score
        return result

    def _compatible_ready_parent_pairs(
        self,
        spec: Mapping[str, Any],
        rows: Sequence[Mapping[str, Any]],
    ) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        normalized = [
            self._ready_parent_with_compatibility(spec, row)
            for row in rows
            if isinstance(row, Mapping)
            and self._integer_identity(row.get("trained_chara_id")) > 0
        ]
        return [
            (first, second)
            for index, first in enumerate(normalized)
            for second in normalized[index + 1:]
            if self._integer_identity(first.get("trained_chara_id"))
            != self._integer_identity(second.get("trained_chara_id"))
            and self._integer_identity(first.get("bootstrap_chara_id"))
            != self._integer_identity(second.get("bootstrap_chara_id"))
            and direct_pair_compatible(
                self._integer_identity(first.get("direct_base_compatibility")),
                self._integer_identity(second.get("direct_base_compatibility")),
            )
        ]

    @staticmethod
    def _requires_pre_run_approval(
        spec: Mapping[str, Any],
        *,
        ambiguous: bool = False,
    ) -> bool:
        strategy = spec.get("strategy") if isinstance(spec, Mapping) else {}
        strategy = strategy if isinstance(strategy, Mapping) else {}
        approval_mode = ApprovalMode(
            strategy.get("approval_mode") or ApprovalMode.AMBIGUITY_ONLY.value
        )
        if approval_mode is ApprovalMode.PER_GENERATION:
            return True
        if approval_mode is ApprovalMode.AMBIGUITY_ONLY:
            return bool(ambiguous)
        return False

    def list_campaigns(self, account: str) -> list[dict[str, Any]]:
        return self.store.list(account=account)

    def get_campaign(self, campaign_id: str) -> dict[str, Any]:
        campaign = self.store.get(campaign_id)
        if int((campaign.get("spec") or {}).get("spec_version") or 0) >= 3:
            campaign = self._ensure_v3_cycle_migration(campaign)
        candidates = self.store.list_candidates(campaign_id, limit=30)
        try:
            runtime = self._snapshot(str(campaign.get("account") or ""))
        except Exception:
            runtime = {}
        display_by_id = runtime.get("display_by_id") if isinstance(runtime, Mapping) else {}
        display_by_id = display_by_id if isinstance(display_by_id, Mapping) else {}
        enriched_candidates = []
        for raw_candidate in candidates:
            candidate = deepcopy(raw_candidate)
            evaluation = candidate.get("evaluation")
            evaluation = deepcopy(evaluation) if isinstance(evaluation, Mapping) else {}
            if not evaluation.get("factor_tree"):
                trained_id = int(candidate.get("trained_chara_id") or 0)
                display = display_by_id.get(trained_id) or display_by_id.get(str(trained_id)) or {}
                if isinstance(display, Mapping) and display.get("tree"):
                    evaluation["factor_tree"] = deepcopy(display["tree"])
            candidate["evaluation"] = evaluation
            enriched_candidates.append(candidate)
        return {
            **campaign,
            "events": self.store.recent_events(campaign_id, limit=30),
            "candidates": enriched_candidates,
        }

    def recommend_final_parents(self, request: Mapping[str, Any]) -> Any:
        payload = dict(request)
        planner = self.planner_factory(payload)
        return planner.recommend_final_parents(limit=int(payload.get("limit", 3)))

    def recommend_bootstraps(self, request: Mapping[str, Any]) -> Any:
        payload = dict(request)
        planner = self.planner_factory(payload)
        kwargs = {"limit": int(payload.get("limit", 3))}
        if "pinned_chara_ids" in payload:
            kwargs["pinned_chara_ids"] = set(payload["pinned_chara_ids"])
        if "mdb_path" in payload:
            kwargs["mdb_path"] = payload["mdb_path"]
        return planner.recommend_bootstraps(**kwargs)

    def recommend_loops(self, request: Mapping[str, Any]) -> Any:
        payload = dict(request)
        planner = self.planner_factory(payload)
        kwargs = {"limit": int(payload.get("limit", 3))}
        if "pinned_chara_ids" in payload:
            kwargs["pinned_chara_ids"] = set(payload["pinned_chara_ids"])
        if "final_parent_chara_id" in payload:
            kwargs["final_parent_chara_id"] = int(payload["final_parent_chara_id"])
        if "mdb_path" in payload:
            kwargs["mdb_path"] = payload["mdb_path"]
        return planner.recommend_loops(**kwargs)

    def create_campaign(self, spec: ParentCampaignSpec | Mapping[str, Any]) -> dict[str, Any]:
        if isinstance(spec, Mapping):
            self._reject_boolean_integer_fields(spec)
        validated = ParentCampaignSpec.model_validate(spec)
        if validated.spec_version < 3 or len(validated.loop_members) != 3:
            raise ValueError(
                "New campaigns require spec_version 3 with exactly three bootstrap members"
            )
        if validated.final_uma.card_id <= 0:
            raise ValueError("final_uma.card_id must be positive for Web campaigns")
        if not any(row.priority is SparkPriority.REQUIRED for row in validated.spark_targets):
            raise ValueError("at least one required spark target is required")
        if any(not 1 <= row.deck_id <= 10 for row in validated.loop_members):
            raise ValueError("each manual loop member deck_id must be between 1 and 10")
        if any(row.friend_support is None for row in validated.loop_members):
            raise ValueError("each bootstrap member requires durable friend_support")
        if not 1 <= validated.final_uma.deck_id <= 10:
            raise ValueError("final_uma.deck_id must be between 1 and 10")
        if validated.final_uma.friend_support is None:
            raise ValueError("final_uma.friend_support is required")
        compatible_bootstrap_pairs = self._compatible_chara_pairs(
            validated.final_uma.card_id,
            [row.chara_id for row in validated.loop_members],
        )
        if compatible_bootstrap_pairs == []:
            raise ValueError(
                "campaign requires at least two compatible bootstrap characters "
                "for the final Uma"
            )
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
        cycle_state = CampaignCycleState.bootstrap(
            [row.chara_id for row in validated.loop_members]
        )
        initial_context = {
            "base_preset_name": base_preset_name,
            "generated_preset_name": generated_name,
            "bootstrap_rotation": cycle_state.to_dict(),
            "ready_parent_candidates": [],
            "selected_ready_pair": None,
            "cycle_migrated": True,
            "aptitude_targets": [],
            "aptitude_evidence": {},
            "aptitude_shortfalls": [],
            "aptitude_warnings": [],
            "projected_displayed_affinity": None,
            "completed_displayed_affinity": None,
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

    def _ensure_legacy_stage_migration(
        self,
        campaign: Mapping[str, Any],
    ) -> dict[str, Any]:
        context = dict(campaign.get("context") or {})
        if isinstance(context.get("stage_state"), Mapping):
            return dict(campaign)
        spec = campaign.get("spec") or {}
        if int(spec.get("spec_version") or 0) >= 3:
            return dict(campaign)
        members = spec.get("loop_members") or []
        if len(members) != 4:
            return dict(campaign)
        chara_ids = [int(row.get("chara_id") or 0) for row in members]
        stage_state = migrate_legacy_rotation(
            chara_ids,
            context.get("rotation") if isinstance(context.get("rotation"), Mapping) else {},
        )
        assignments = build_stage_goal_assignments(
            list(spec.get("spark_targets") or []),
            bootstrap_count=len(chara_ids),
        )
        return self.store.update_context(
            str(campaign["campaign_id"]),
            {
                "stage_state": stage_state.to_dict(),
                "stage_goal_assignments": assignments,
                "bootstrap_goal_state": deepcopy(context.get("bootstrap_goal_state") or {}),
                "aptitude_targets": deepcopy(context.get("aptitude_targets") or []),
                "aptitude_evidence": deepcopy(context.get("aptitude_evidence") or {}),
                "aptitude_shortfalls": deepcopy(context.get("aptitude_shortfalls") or []),
                "aptitude_warnings": deepcopy(context.get("aptitude_warnings") or []),
                "projected_displayed_affinity": context.get("projected_displayed_affinity"),
                "completed_displayed_affinity": context.get("completed_displayed_affinity"),
                "legacy_stage_migrated": True,
            },
        )

    def _ready_parent_rows_from_history(
        self,
        campaign: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        spec = campaign.get("spec") or {}
        members = spec.get("loop_members") or []
        targets = ready_parent_targets(spec.get("spark_targets") or [])
        rows: list[dict[str, Any]] = []
        seen: set[int] = set()
        for candidate in self.store.list_candidates(
            str(campaign["campaign_id"]),
            limit=500,
        ):
            evaluation = candidate.get("evaluation") or {}
            if evaluation.get("stage_kind") not in {"bootstrap", "cycle_bootstrap"}:
                continue
            trained_id = self._integer_identity(candidate.get("trained_chara_id"))
            if trained_id <= 0 or trained_id in seen:
                continue
            totals = self_spark_totals(evaluation.get("factor_tree") or {})
            target_result = evaluate_spark_targets(targets, totals)
            if not target_result["required_complete"]:
                continue
            trainee_chara_id = self._integer_identity(
                evaluation.get("trainee_chara_id")
            )
            if trainee_chara_id <= 0:
                stage_index = self._integer_identity(evaluation.get("stage_index"))
                if 0 <= stage_index < len(members):
                    trainee_chara_id = self._integer_identity(
                        members[stage_index].get("chara_id")
                    )
            ready_row = {
                "candidate_id": str(candidate["candidate_id"]),
                "trained_chara_id": trained_id,
                "bootstrap_chara_id": trainee_chara_id,
                "self_spark_totals": self._serialized_spark_totals(
                    {"spark_totals": totals}
                ),
                "rank_score": self._integer_identity(
                    evaluation.get("rank_score") or candidate.get("score")
                ),
            }
            rows.append(self._ready_parent_with_compatibility(spec, ready_row))
            seen.add(trained_id)
        return rows

    def _ensure_v3_cycle_migration(
        self,
        campaign: Mapping[str, Any],
    ) -> dict[str, Any]:
        spec = campaign.get("spec") or {}
        if int(spec.get("spec_version") or 0) < 3:
            return dict(campaign)
        context = dict(campaign.get("context") or {})
        if isinstance(context.get("bootstrap_rotation"), Mapping):
            return dict(campaign)

        members = spec.get("loop_members") or []
        chara_ids = [self._integer_identity(row.get("chara_id")) for row in members]
        if not chara_ids or any(chara_id <= 0 for chara_id in chara_ids):
            return dict(campaign)
        saved_stage = (
            context.get("stage_state")
            if isinstance(context.get("stage_state"), Mapping)
            else {}
        )
        cycle = migrate_stage_state_to_cycle(chara_ids, saved_stage)
        ready_rows = self._ready_parent_rows_from_history(campaign)
        if self._compatible_ready_parent_pairs(spec, ready_rows):
            cycle = enter_final_stage(cycle)

        return self.store.update_context(
            str(campaign["campaign_id"]),
            {
                "bootstrap_rotation": cycle.to_dict(),
                "ready_parent_candidates": ready_rows,
                "selected_ready_pair": None,
                "cycle_migrated": True,
                "stage_state": None,
                "stage_goal_assignments": None,
                "bootstrap_goal_state": None,
            },
        )

    def _ensure_progression_migration(
        self,
        campaign: Mapping[str, Any],
    ) -> dict[str, Any]:
        spec = campaign.get("spec") or {}
        if int(spec.get("spec_version") or 0) >= 3:
            return self._ensure_v3_cycle_migration(campaign)
        return self._ensure_legacy_stage_migration(campaign)

    def activate(self, campaign_id: str) -> dict[str, Any]:
        campaign = self._ensure_progression_migration(self.store.get(campaign_id))
        snapshot = self._snapshot(campaign["account"])
        current_career = self._trusted_current_career(campaign, snapshot)
        if current_career is not None:
            reconciled = self._campaign_from_reconciliation(
                self.reconcile_runtime(campaign_id, current_career)
            )
            if not self._campaign_unchanged(campaign, reconciled):
                return reconciled
        runtime = snapshot.get("runtime", snapshot)
        bot_state = snapshot.get("bot_state", snapshot)
        return self.runner.start(campaign_id, runtime=runtime, bot_state=bot_state)

    def pause(self, campaign_id: str) -> dict[str, Any]:
        return self.runner.pause(campaign_id)

    def resume(self, campaign_id: str) -> dict[str, Any]:
        campaign = self._ensure_progression_migration(self.store.get(campaign_id))
        snapshot = self._snapshot(campaign["account"])
        current_career = self._trusted_current_career(campaign, snapshot)
        if current_career is not None and current_career.get("active") is True:
            prepared_run = dict((campaign.get("context") or {}).get("prepared_run") or {})
            if self._career_matches_prepared_run(current_career, prepared_run):
                bot_state = snapshot.get("bot_state", snapshot)
                runner_state = (
                    bot_state.get("career_runner")
                    if isinstance(bot_state.get("career_runner"), Mapping)
                    else {}
                )
                if not runner_state.get("running"):
                    self.start_career(deepcopy(prepared_run))
                return self.runner.resume(campaign_id)
        if current_career is not None:
            reconciled = self._campaign_from_reconciliation(
                self.reconcile_runtime(campaign_id, current_career)
            )
            if not self._campaign_unchanged(campaign, reconciled):
                return reconciled
        return self.runner.resume(campaign_id)

    def reconcile_runtime(
        self,
        campaign_id: str,
        current_career: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        campaign = self.store.get(campaign_id)
        spec = campaign.get("spec") or {}
        context = campaign.get("context") or {}
        if int(spec.get("spec_version") or 0) >= 3:
            campaign = self._ensure_v3_cycle_migration(campaign)
        elif isinstance(context.get("rotation"), Mapping):
            campaign = self._ensure_legacy_stage_migration(campaign)
        current = dict(current_career or {})
        prepared_run = dict((campaign.get("context") or {}).get("prepared_run") or {})
        if current.get("active") is True:
            if self._career_matches_prepared_run(current, prepared_run):
                if campaign["state"] == CampaignState.PAUSED.value:
                    return campaign
                return self.store.transition(
                    campaign_id,
                    CampaignState.RUNNING_CAREER,
                    next_action="monitor_career",
                )
            error = "Current active career does not match the persisted prepared run"
            return self.store.pause_for_runtime_mismatch(
                campaign_id,
                error=error,
                expected_version=campaign.get("version"),
            )

        state = CampaignState(campaign["state"])
        if state in {
            CampaignState.PAUSED,
            CampaignState.NEEDS_USER_INPUT,
            CampaignState.COMPLETED,
            CampaignState.FAILED,
            CampaignState.CANCELLED,
        }:
            return campaign
        if state is CampaignState.RUNNING_CAREER:
            recovery = self.store.recover_missing_active_career(
                campaign_id,
                expected_version=campaign.get("version"),
            )
            return recovery["campaign"]
        if state is not CampaignState.SELECTING_LINEAGE:
            return campaign
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

    @staticmethod
    def _campaign_from_reconciliation(result: Mapping[str, Any]) -> dict[str, Any]:
        campaign = result.get("campaign", result)
        return dict(campaign) if isinstance(campaign, Mapping) else {}

    @staticmethod
    def _campaign_unchanged(
        before: Mapping[str, Any],
        after: Mapping[str, Any],
    ) -> bool:
        return all(
            after.get(key) == before.get(key)
            for key in ("state", "version", "next_action", "error")
        )

    @staticmethod
    def _cycle_state(campaign: Mapping[str, Any]) -> CampaignCycleState:
        context = campaign.get("context") or {}
        saved = (
            context.get("bootstrap_rotation")
            if isinstance(context, Mapping)
            else None
        )
        if isinstance(saved, Mapping):
            return CampaignCycleState(
                bootstrap_chara_ids=tuple(saved.get("bootstrap_chara_ids") or ()),
                run_index=int(saved.get("run_index") or 0),
                final_stage_active=bool(saved.get("final_stage_active", False)),
                final_repeat_count=int(saved.get("final_repeat_count") or 0),
                produced=tuple(
                    tuple(row)
                    for row in (saved.get("produced") or ())
                    if isinstance(row, (list, tuple)) and len(row) == 2
                ),
            )
        members = campaign.get("spec", {}).get("loop_members") or []
        return CampaignCycleState.bootstrap(
            [int(row.get("chara_id") or 0) for row in members]
        )

    @staticmethod
    def _stage_state(campaign: Mapping[str, Any]) -> CampaignStageState:
        context = campaign.get("context") or {}
        saved = context.get("stage_state") if isinstance(context, Mapping) else None
        if isinstance(saved, Mapping):
            return CampaignStageState(
                bootstrap_chara_ids=tuple(saved.get("bootstrap_chara_ids") or ()),
                stage_index=int(saved.get("stage_index") or 0),
                completed_bootstrap_stages=tuple(saved.get("completed_bootstrap_stages") or ()),
                final_repeat_count=int(saved.get("final_repeat_count") or 0),
                produced=tuple(tuple(row) for row in (saved.get("produced") or ())),
            )
        members = campaign.get("spec", {}).get("loop_members") or []
        return CampaignStageState.bootstrap([int(row.get("chara_id") or 0) for row in members])

    @classmethod
    def _owned_trainee_card_id(
        cls,
        runtime: Mapping[str, Any],
        trainee_chara_id: int,
    ) -> int:
        matches = []
        for row in runtime.get("umas") or []:
            if not isinstance(row, Mapping):
                continue
            card_id = cls._integer_identity(row.get("card_id") or row.get("id"))
            if card_id > 0 and card_to_chara_id(card_id) == int(trainee_chara_id):
                matches.append(card_id)
        return min(matches) if matches else 0

    @staticmethod
    def _display_factor_tree(display: Mapping[str, Any]) -> dict[str, Any]:
        raw_tree = display.get("tree") if isinstance(display.get("tree"), Mapping) else {}
        aliases = {
            "self": "self",
            "parent1": "parent1",
            "parent2": "parent2",
            "p1": "parent1",
            "p2": "parent2",
        }
        result = {
            "self": {"blue": [], "pink": []},
            "parent1": {"blue": [], "pink": []},
            "parent2": {"blue": [], "pink": []},
        }
        for raw_key, target_key in aliases.items():
            node = raw_tree.get(raw_key)
            if not isinstance(node, Mapping):
                continue
            for factor in node.get("factors") or []:
                if not isinstance(factor, Mapping):
                    continue
                category = str(factor.get("category") or "").strip().casefold()
                bucket = {
                    "stat": "blue",
                    "blue": "blue",
                    "aptitude": "pink",
                    "pink": "pink",
                }.get(category)
                if bucket:
                    result[target_key][bucket].append(dict(factor))
            for bucket in ("blue", "pink"):
                for factor in node.get(bucket) or []:
                    if isinstance(factor, Mapping):
                        result[target_key][bucket].append(dict(factor))
        return result

    def _stage_candidates(
        self,
        campaign: Mapping[str, Any],
        state: CampaignStageState,
        trainee_chara_id: int,
        runtime: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        view = _StageRunView(
            next_trainee_chara_id=trainee_chara_id,
            stage_index=state.stage_index,
            available_legacy_ids=tuple(legacy_id for _chara_id, legacy_id in state.produced),
        )
        display_by_id = runtime.get("display_by_id") if isinstance(runtime.get("display_by_id"), Mapping) else {}
        allow_rental = bool(campaign.get("spec", {}).get("options", {}).get("allow_rental", False))
        result = []
        for raw in self.candidate_pool(campaign, view, runtime):
            if not isinstance(raw, Mapping):
                continue
            row = dict(raw)
            trained_id = self._integer_identity(row.get("trained_chara_id") or row.get("instance_id"))
            if trained_id <= 0:
                continue
            if row.get("rental") is True and not allow_rental:
                continue
            if self._candidate_base_chara_id(row) == trainee_chara_id:
                continue
            display = display_by_id.get(trained_id) or display_by_id.get(str(trained_id)) or {}
            if isinstance(display, Mapping):
                row.setdefault("name", str(display.get("name") or ""))
                if not row.get("factor_tree"):
                    row["factor_tree"] = self._display_factor_tree(display)
            result.append(row)
        return result

    def _prepare_cycle_run(
        self,
        campaign: Mapping[str, Any],
        runtime: Mapping[str, Any],
    ) -> dict[str, Any]:
        campaign_id = str(campaign["campaign_id"])
        spec = campaign["spec"]
        context = dict(campaign.get("context") or {})
        state = self._cycle_state(campaign)
        final_stage = state.final_stage_active
        members = spec.get("loop_members") or []

        if final_stage:
            final_uma = dict(spec.get("final_uma") or {})
            trainee_card_id = self._integer_identity(final_uma.get("card_id"))
            trainee_chara_id = card_to_chara_id(trainee_card_id) if trainee_card_id else 0
            stage_setup = final_uma
            if isinstance(runtime.get("umas"), list):
                owned_cards = {
                    self._integer_identity(row.get("card_id") or row.get("id"))
                    for row in runtime.get("umas") or []
                    if isinstance(row, Mapping)
                }
                if trainee_card_id not in owned_cards:
                    paused = self.store.transition(
                        campaign_id,
                        CampaignState.PAUSED,
                        next_action="resolve_final_uma_unavailable",
                        error=f"Final Uma card {trainee_card_id} is unavailable",
                    )
                    return {"campaign": paused, "prepared_run": None, "resolved_slots": []}
            if not 1 <= int(stage_setup.get("deck_id") or 0) <= 10 or not isinstance(
                stage_setup.get("friend_support"),
                Mapping,
            ):
                paused = self.store.transition(
                    campaign_id,
                    CampaignState.PAUSED,
                    next_action="resolve_final_uma_setup",
                    error="Final Uma stage requires a durable deck and friend support",
                )
                return {"campaign": paused, "prepared_run": None, "resolved_slots": []}
            member_index = len(members)
        else:
            if not members:
                raise ValueError("Campaign has no bootstrap members")
            member_index = state.run_index % len(members)
            stage_setup = dict(members[member_index])
            trainee_chara_id = int(stage_setup.get("chara_id") or 0)
            trainee_card_id = self._owned_trainee_card_id(runtime, trainee_chara_id)

        deck_id = int(stage_setup.get("deck_id") or 0)
        runtime_deck = next(
            (
                dict(row)
                for row in (runtime.get("decks") or [])
                if isinstance(row, Mapping)
                and self._integer_identity(row.get("id") or row.get("deck_id")) == deck_id
            ),
            {},
        )
        runtime_trainee = next(
            (
                dict(row)
                for row in (runtime.get("umas") or [])
                if isinstance(row, Mapping)
                and (
                    self._integer_identity(row.get("id") or row.get("card_id")) == trainee_card_id
                    or card_to_chara_id(
                        self._integer_identity(row.get("id") or row.get("card_id"))
                    ) == trainee_chara_id
                )
            ),
            {"id": trainee_card_id, "name": ""},
        )
        deck_conflicts = find_trainee_deck_conflicts(runtime_deck, runtime_trainee)
        if deck_conflicts:
            review = {
                "kind": "stage_deck_conflict",
                "rotation_index": state.run_index,
                "stage_kind": "cycle_final" if final_stage else "cycle_bootstrap",
                "trainee_chara_id": trainee_chara_id,
                "card_id": trainee_card_id,
                "deck_id": deck_id,
                "conflicts": deck_conflicts,
            }
            persisted = self.store.update_context(
                campaign_id,
                {
                    "bootstrap_rotation": state.to_dict(),
                    "prepared_run": None,
                    "prepared_run_id": None,
                    "pending_review": review,
                    "review_required": True,
                    "run_start": None,
                },
            )
            persisted = self.runner.require_user_input(
                campaign_id,
                "resolve_stage_deck_conflict",
                review,
            )
            return {"campaign": persisted, "prepared_run": None, "resolved_slots": []}

        race_plan = spec.get("race_plan") or {}
        planned_race_ids = [
            *list(race_plan.get("core") or []),
            *list(race_plan.get("optional") or []),
            *list(race_plan.get("deferable") or []),
        ]
        static_aptitude_result = generate_aptitude_targets(
            trainee_card_id=trainee_card_id,
            race_ids=planned_race_ids,
            race_rows=runtime.get("race_rows") or [],
            base_aptitudes=runtime.get("base_aptitudes") or {},
        ) if trainee_card_id > 0 else {
            "targets": [],
            "warnings": [f"Missing exact trainee card data for character {trainee_chara_id}"],
        }

        pseudo_state = CampaignStageState(
            bootstrap_chara_ids=state.bootstrap_chara_ids,
            stage_index=(len(state.bootstrap_chara_ids) if final_stage else member_index),
            completed_bootstrap_stages=(),
            final_repeat_count=state.final_repeat_count,
            produced=state.produced,
        )
        candidates = self._stage_candidates(
            campaign,
            pseudo_state,
            trainee_chara_id,
            runtime,
        )
        ready_by_id = {
            self._integer_identity(row.get("trained_chara_id")): self._ready_parent_with_compatibility(
                spec,
                row,
            )
            for row in (context.get("ready_parent_candidates") or [])
            if isinstance(row, Mapping)
            and self._integer_identity(row.get("trained_chara_id")) > 0
        }
        if final_stage:
            eligible_ready_ids = {
                self._integer_identity(parent.get("trained_chara_id"))
                for pair in self._compatible_ready_parent_pairs(
                    spec,
                    list(ready_by_id.values()),
                )
                for parent in pair
            }
            candidates = [
                row
                for row in candidates
                if self._integer_identity(
                    row.get("trained_chara_id") or row.get("instance_id")
                ) in eligible_ready_ids
            ]

        factor_targets = parent_pair_targets(spec.get("spark_targets") or [])
        saddle_map = runtime.get("g1_saddle_program_map") or {}
        agenda_cache: dict[tuple[int, int], dict[str, Any]] = {}

        def pair_key(first, second):
            return tuple(sorted((
                self._integer_identity(first.get("trained_chara_id") or first.get("instance_id")),
                self._integer_identity(second.get("trained_chara_id") or second.get("instance_id")),
            )))

        def pair_affinity_agenda(first, second):
            key = pair_key(first, second)
            if key in agenda_cache:
                return agenda_cache[key]
            agenda = build_displayed_affinity_agenda(
                runtime.get("race_rows") or [],
                mandatory_program_ids=race_plan.get("core") or [],
                factor_program_ids=[
                    *list(race_plan.get("optional") or []),
                    *list(race_plan.get("deferable") or []),
                ],
                saddle_ids_by_program=saddle_map,
                parent1_g1_saddles=set(first.get("win_saddle_id_array") or []),
                parent2_g1_saddles=set(second.get("win_saddle_id_array") or []),
            )
            agenda_cache[key] = agenda
            return agenda

        def pair_aptitude_targets(first, second):
            if trainee_card_id <= 0:
                return static_aptitude_result
            agenda = pair_affinity_agenda(first, second)
            required_races = [
                *planned_race_ids,
                *list(agenda.get("affinity_program_ids") or []),
            ]
            return generate_aptitude_targets(
                trainee_card_id=trainee_card_id,
                race_ids=required_races,
                race_rows=runtime.get("race_rows") or [],
                base_aptitudes=runtime.get("base_aptitudes") or {},
            )

        def agenda_saddles(agenda):
            programs = {
                *list(agenda.get("mandatory_race_list") or []),
                *list(agenda.get("factor_program_ids") or []),
                *list(agenda.get("affinity_program_ids") or []),
            }
            return {
                int(saddle_id)
                for program_id in programs
                for saddle_id in (
                    saddle_map.get(int(program_id))
                    or saddle_map.get(str(program_id))
                    or set()
                )
            }

        def affinity_scorer(card_id, first, second):
            projector = getattr(self, "projected_affinity_for_pair", None)
            if callable(projector):
                agenda = pair_affinity_agenda(first, second)
                return projector(card_id, first, second, agenda_saddles(agenda))
            return self.affinity_for_setup({"card_id": card_id}, first, second)

        ranked_pairs = rank_parent_pairs(
            candidates,
            trainee_card_id=trainee_card_id,
            aptitude_targets=static_aptitude_result["targets"],
            aptitude_targets_for_pair=pair_aptitude_targets,
            factor_targets=factor_targets,
            affinity_scorer=affinity_scorer,
            factor_nodes="self",
        )
        ranked_pairs.sort(
            key=lambda row: (
                -int(bool(row["aptitude"]["feasible"])),
                -int(bool(row["factor_progress"]["required_complete"])),
                -int(row["projected_displayed_affinity"]),
                -int(row["rank_score"]),
                tuple(row["trained_chara_id"]),
            )
        )
        baseline_parent_ids = sorted({
            self._integer_identity(row.get("trained_chara_id") or row.get("instance_id"))
            for row in (runtime.get("owned_candidates") or [])
            if isinstance(row, Mapping)
            and self._integer_identity(row.get("trained_chara_id") or row.get("instance_id")) > 0
        })
        if not ranked_pairs:
            review = {
                "kind": "unresolved_parent_pair",
                "rotation_index": state.run_index,
                "stage_kind": "cycle_final" if final_stage else "cycle_bootstrap",
                "trainee_chara_id": trainee_chara_id,
                "aptitude_targets": static_aptitude_result["targets"],
            }
            persisted = self.store.update_context(
                campaign_id,
                {
                    "bootstrap_rotation": state.to_dict(),
                    "prepared_run": None,
                    "prepared_run_id": None,
                    "pending_review": review,
                    "review_required": True,
                    "run_start": None,
                    "baseline_parent_ids": baseline_parent_ids,
                    "aptitude_targets": static_aptitude_result["targets"],
                    "aptitude_warnings": static_aptitude_result["warnings"],
                },
            )
            persisted = self.runner.require_user_input(
                campaign_id,
                "prepare_next_run",
                review,
            )
            return {"campaign": persisted, "prepared_run": None, "resolved_slots": []}

        best = ranked_pairs[0]
        resolved = [
            {
                **dict(parent),
                "status": "RESOLVED",
                "replacement": False,
                "reason": (
                    "best ready parent pair"
                    if final_stage
                    else "best cyclic parent pair"
                ),
            }
            for parent in best["parents"]
        ]
        warnings = list(best.get("aptitude_warnings") or [])
        if not saddle_map:
            warnings.append(
                "G1 saddle/program mapping unavailable; projected affinity race gains omitted"
            )
        affinity_agenda = pair_affinity_agenda(resolved[0], resolved[1])
        races = {
            "mandatory_race_list": list(affinity_agenda["mandatory_race_list"]),
            "extra_race_list": list(affinity_agenda["extra_race_list"]),
            "parent_run": not final_stage,
        }
        request = {
            "account": campaign["account"],
            "preset": self.preset_store.load(spec["strategy"]["preset_name"]),
            "trainee_chara_id": trainee_chara_id,
            "card_id": trainee_card_id,
            "deck_id": int(stage_setup.get("deck_id") or 0),
            "legacy_slots": resolved,
            "race_overrides": races,
            "campaign_id": campaign_id,
        }
        friend_support = stage_setup.get("friend_support")
        if isinstance(friend_support, Mapping):
            request["friend_support"] = deepcopy(dict(friend_support))

        prepared_run_id = self._stable_id("prepared", request)
        review = {
            "kind": "prepared_run",
            "prepared_run_id": prepared_run_id,
            "prepared_run": request,
            "resolved_slots": resolved,
            "replacements": [],
            "rotation_index": state.run_index,
            "stage_kind": "cycle_final" if final_stage else "cycle_bootstrap",
            "aptitude_shortfalls": best["aptitude"]["shortfalls"],
        }
        requires_approval = self._requires_pre_run_approval(spec)
        updates: dict[str, Any] = {
            "bootstrap_rotation": state.to_dict(),
            "prepared_run": request,
            "prepared_run_id": prepared_run_id,
            "pending_review": review if requires_approval else None,
            "review_required": requires_approval,
            "run_start": None,
            "baseline_parent_ids": baseline_parent_ids,
            "aptitude_targets": deepcopy(best.get("aptitude_targets") or []),
            "aptitude_evidence": best["aptitude"]["evidence"],
            "aptitude_shortfalls": best["aptitude"]["shortfalls"],
            "aptitude_warnings": warnings,
            "projected_displayed_affinity": best["projected_displayed_affinity"],
            "affinity_agenda": affinity_agenda,
        }
        if final_stage:
            trained_ids = [
                self._integer_identity(parent.get("trained_chara_id"))
                for parent in best["parents"]
            ]
            updates["selected_ready_pair"] = {
                "candidate_ids": [
                    str(ready_by_id.get(trained_id, {}).get("candidate_id") or "")
                    for trained_id in trained_ids
                ],
                "trained_chara_ids": trained_ids,
                "aptitude_feasible": bool(best["aptitude"]["feasible"]),
                "target_factor_valid": bool(
                    best["factor_progress"]["required_complete"]
                ),
                "projected_displayed_affinity": int(
                    best["projected_displayed_affinity"]
                ),
                "direct_base_compatibility": [
                    self._integer_identity(
                        ready_by_id.get(trained_id, {}).get("direct_base_compatibility")
                    )
                    for trained_id in trained_ids
                ],
                "rank_score": int(best["rank_score"]),
            }
        persisted = self.store.update_context(campaign_id, updates)
        if requires_approval:
            persisted = self.runner.require_user_input(campaign_id, "approve_run", review)
        else:
            persisted = self.store.set_next_action(campaign_id, "start_career")
        return {"campaign": persisted, "prepared_run": request, "resolved_slots": resolved}

    def _prepare_stage_run(
        self,
        campaign: Mapping[str, Any],
        runtime: Mapping[str, Any],
    ) -> dict[str, Any]:
        campaign_id = str(campaign["campaign_id"])
        spec = campaign["spec"]
        context = dict(campaign.get("context") or {})
        state = self._stage_state(campaign)
        final_stage = state.is_final_stage

        if final_stage:
            final_uma = dict(spec.get("final_uma") or {})
            trainee_card_id = self._integer_identity(final_uma.get("card_id"))
            trainee_chara_id = card_to_chara_id(trainee_card_id) if trainee_card_id else 0
            stage_setup = final_uma
            if isinstance(runtime.get("umas"), list):
                owned_cards = {
                    self._integer_identity(row.get("card_id") or row.get("id"))
                    for row in runtime.get("umas") or []
                    if isinstance(row, Mapping)
                }
                if trainee_card_id not in owned_cards:
                    paused = self.store.transition(
                        campaign_id,
                        CampaignState.PAUSED,
                        next_action="resolve_final_uma_unavailable",
                        error=f"Final Uma card {trainee_card_id} is unavailable",
                    )
                    return {"campaign": paused, "prepared_run": None, "resolved_slots": []}
            if not 1 <= int(stage_setup.get("deck_id") or 0) <= 10 or not isinstance(
                stage_setup.get("friend_support"),
                Mapping,
            ):
                paused = self.store.transition(
                    campaign_id,
                    CampaignState.PAUSED,
                    next_action="resolve_final_uma_setup",
                    error="Final Uma stage requires a durable deck and friend support",
                )
                return {"campaign": paused, "prepared_run": None, "resolved_slots": []}
        else:
            members = spec.get("loop_members") or []
            if state.stage_index >= len(members):
                raise ValueError("Campaign stage index exceeds configured bootstrap members")
            stage_setup = dict(members[state.stage_index])
            trainee_chara_id = int(stage_setup.get("chara_id") or 0)
            trainee_card_id = self._owned_trainee_card_id(runtime, trainee_chara_id)

        deck_id = int(stage_setup.get("deck_id") or 0)
        runtime_deck = next(
            (
                dict(row)
                for row in (runtime.get("decks") or [])
                if isinstance(row, Mapping)
                and self._integer_identity(row.get("id") or row.get("deck_id")) == deck_id
            ),
            {},
        )
        runtime_trainee = next(
            (
                dict(row)
                for row in (runtime.get("umas") or [])
                if isinstance(row, Mapping)
                and (
                    self._integer_identity(row.get("id") or row.get("card_id")) == trainee_card_id
                    or card_to_chara_id(
                        self._integer_identity(row.get("id") or row.get("card_id"))
                    ) == trainee_chara_id
                )
            ),
            {"id": trainee_card_id, "name": ""},
        )
        deck_conflicts = find_trainee_deck_conflicts(runtime_deck, runtime_trainee)
        if deck_conflicts:
            review = {
                "kind": "stage_deck_conflict",
                "stage_index": state.stage_index,
                "stage_kind": "final" if final_stage else "bootstrap",
                "trainee_chara_id": trainee_chara_id,
                "card_id": trainee_card_id,
                "deck_id": deck_id,
                "conflicts": deck_conflicts,
            }
            persisted = self.store.update_context(
                campaign_id,
                {
                    "stage_state": state.to_dict(),
                    "prepared_run": None,
                    "prepared_run_id": None,
                    "pending_review": review,
                    "review_required": True,
                    "run_start": None,
                },
            )
            persisted = self.runner.require_user_input(
                campaign_id,
                "resolve_stage_deck_conflict",
                review,
            )
            return {
                "campaign": persisted,
                "prepared_run": None,
                "resolved_slots": [],
            }

        race_plan = spec.get("race_plan") or {}
        planned_race_ids = [
            *list(race_plan.get("core") or []),
            *list(race_plan.get("optional") or []),
            *list(race_plan.get("deferable") or []),
        ]
        static_aptitude_result = generate_aptitude_targets(
            trainee_card_id=trainee_card_id,
            race_ids=planned_race_ids,
            race_rows=runtime.get("race_rows") or [],
            base_aptitudes=runtime.get("base_aptitudes") or {},
        ) if trainee_card_id > 0 else {
            "targets": [],
            "warnings": [f"Missing exact trainee card data for character {trainee_chara_id}"],
        }
        factor_targets = (
            list(spec.get("spark_targets") or [])
            if final_stage
            else list((context.get("stage_goal_assignments") or {}).get(str(state.stage_index), []))
        )
        candidates = self._stage_candidates(campaign, state, trainee_chara_id, runtime)
        saddle_map = runtime.get("g1_saddle_program_map") or {}
        agenda_cache: dict[tuple[int, int], dict[str, Any]] = {}

        def pair_key(first, second):
            return tuple(sorted((
                self._integer_identity(first.get("trained_chara_id") or first.get("instance_id")),
                self._integer_identity(second.get("trained_chara_id") or second.get("instance_id")),
            )))

        def pair_affinity_agenda(first, second):
            key = pair_key(first, second)
            if key in agenda_cache:
                return agenda_cache[key]
            agenda = build_displayed_affinity_agenda(
                runtime.get("race_rows") or [],
                mandatory_program_ids=race_plan.get("core") or [],
                factor_program_ids=[
                    *list(race_plan.get("optional") or []),
                    *list(race_plan.get("deferable") or []),
                ],
                saddle_ids_by_program=saddle_map,
                parent1_g1_saddles=set(first.get("win_saddle_id_array") or []),
                parent2_g1_saddles=set(second.get("win_saddle_id_array") or []),
            )
            agenda_cache[key] = agenda
            return agenda

        def pair_aptitude_targets(first, second):
            if trainee_card_id <= 0:
                return static_aptitude_result
            agenda = pair_affinity_agenda(first, second)
            required_races = [
                *planned_race_ids,
                *list(agenda.get("affinity_program_ids") or []),
            ]
            return generate_aptitude_targets(
                trainee_card_id=trainee_card_id,
                race_ids=required_races,
                race_rows=runtime.get("race_rows") or [],
                base_aptitudes=runtime.get("base_aptitudes") or {},
            )

        def agenda_saddles(agenda):
            programs = {
                *list(agenda.get("mandatory_race_list") or []),
                *list(agenda.get("factor_program_ids") or []),
                *list(agenda.get("affinity_program_ids") or []),
            }
            return {
                int(saddle_id)
                for program_id in programs
                for saddle_id in (
                    saddle_map.get(int(program_id))
                    or saddle_map.get(str(program_id))
                    or set()
                )
            }

        def affinity_scorer(card_id, first, second):
            projector = getattr(self, "projected_affinity_for_pair", None)
            if callable(projector):
                agenda = pair_affinity_agenda(first, second)
                return projector(card_id, first, second, agenda_saddles(agenda))
            return self.affinity_for_setup({"card_id": card_id}, first, second)

        ranked_pairs = rank_parent_pairs(
            candidates,
            trainee_card_id=trainee_card_id,
            aptitude_targets=static_aptitude_result["targets"],
            aptitude_targets_for_pair=pair_aptitude_targets,
            factor_targets=factor_targets,
            affinity_scorer=affinity_scorer,
        )
        baseline_parent_ids = sorted({
            self._integer_identity(row.get("trained_chara_id") or row.get("instance_id"))
            for row in (runtime.get("owned_candidates") or [])
            if isinstance(row, Mapping)
            and self._integer_identity(row.get("trained_chara_id") or row.get("instance_id")) > 0
        })
        if not ranked_pairs:
            review = {
                "kind": "unresolved_parent_pair",
                "stage_index": state.stage_index,
                "trainee_chara_id": trainee_chara_id,
                "aptitude_targets": static_aptitude_result["targets"],
            }
            persisted = self.store.update_context(
                campaign_id,
                {
                    "stage_state": state.to_dict(),
                    "prepared_run": None,
                    "prepared_run_id": None,
                    "pending_review": review,
                    "review_required": True,
                    "run_start": None,
                    "baseline_parent_ids": baseline_parent_ids,
                    "aptitude_targets": static_aptitude_result["targets"],
                    "aptitude_warnings": static_aptitude_result["warnings"],
                },
            )
            persisted = self.runner.require_user_input(campaign_id, "prepare_next_run", review)
            return {"campaign": persisted, "prepared_run": None, "resolved_slots": []}

        best = ranked_pairs[0]
        resolved = [
            {
                **dict(parent),
                "status": "RESOLVED",
                "replacement": False,
                "reason": "best stage-aware parent pair",
            }
            for parent in best["parents"]
        ]
        warnings = list(best.get("aptitude_warnings") or [])
        if not saddle_map:
            warnings.append(
                "G1 saddle/program mapping unavailable; projected affinity race gains omitted"
            )
        affinity_agenda = pair_affinity_agenda(resolved[0], resolved[1])
        races = {
            "mandatory_race_list": list(affinity_agenda["mandatory_race_list"]),
            "extra_race_list": list(affinity_agenda["extra_race_list"]),
            "parent_run": not final_stage,
        }
        request = {
            "account": campaign["account"],
            "preset": self.preset_store.load(spec["strategy"]["preset_name"]),
            "trainee_chara_id": trainee_chara_id,
            "card_id": trainee_card_id,
            "deck_id": int(stage_setup.get("deck_id") or 0),
            "legacy_slots": resolved,
            "race_overrides": races,
            "campaign_id": campaign_id,
        }
        friend_support = stage_setup.get("friend_support")
        if isinstance(friend_support, Mapping):
            request["friend_support"] = deepcopy(dict(friend_support))

        prepared_run_id = self._stable_id("prepared", request)
        review = {
            "kind": "prepared_run",
            "prepared_run_id": prepared_run_id,
            "prepared_run": request,
            "resolved_slots": resolved,
            "replacements": [],
            "stage_index": state.stage_index,
            "stage_kind": "final" if final_stage else "bootstrap",
            "aptitude_shortfalls": best["aptitude"]["shortfalls"],
        }
        requires_approval = self._requires_pre_run_approval(spec)
        updates = {
            "stage_state": state.to_dict(),
            "prepared_run": request,
            "prepared_run_id": prepared_run_id,
            "pending_review": review if requires_approval else None,
            "review_required": requires_approval,
            "run_start": None,
            "baseline_parent_ids": baseline_parent_ids,
            "aptitude_targets": deepcopy(best.get("aptitude_targets") or []),
            "aptitude_evidence": best["aptitude"]["evidence"],
            "aptitude_shortfalls": best["aptitude"]["shortfalls"],
            "aptitude_warnings": warnings,
            "projected_displayed_affinity": best["projected_displayed_affinity"],
            "affinity_agenda": affinity_agenda,
        }
        persisted = self.store.update_context(campaign_id, updates)
        if requires_approval:
            persisted = self.runner.require_user_input(campaign_id, "approve_run", review)
        else:
            persisted = self.store.set_next_action(campaign_id, "start_career")
        return {"campaign": persisted, "prepared_run": request, "resolved_slots": resolved}

    def prepare_next_run(self, campaign_id: str) -> dict[str, Any]:
        campaign = self.store.get(campaign_id)
        spec_version = int((campaign.get("spec") or {}).get("spec_version") or 0)
        context = campaign.get("context") or {}
        if spec_version >= 3 and not isinstance(context.get("bootstrap_rotation"), Mapping):
            campaign = self._ensure_v3_cycle_migration(campaign)
        runtime = self._snapshot(campaign["account"])
        context = campaign.get("context") or {}
        if (
            int((campaign.get("spec") or {}).get("spec_version") or 0) >= 3
            or isinstance(context.get("bootstrap_rotation"), Mapping)
        ):
            return self._prepare_cycle_run(campaign, runtime)
        if isinstance(context.get("stage_state"), Mapping):
            return self._prepare_stage_run(campaign, runtime)
        rotation = self._rotation(campaign)
        resolver = LegacyResolver(allow_rental=bool(campaign["spec"]["options"]["allow_rental"]))
        candidates = [dict(row) for row in self.candidate_pool(campaign, rotation, runtime)]
        baseline_parent_ids = sorted({
            self._integer_identity(row.get("trained_chara_id") or row.get("instance_id"))
            for row in (runtime.get("owned_candidates") or [])
            if isinstance(row, Mapping)
            and self._integer_identity(row.get("trained_chara_id") or row.get("instance_id")) > 0
        })
        resolved: list[dict[str, Any]] = []
        used_trained_ids: set[int] = set()
        used_base_chara_ids: set[int] = set()
        for slot_payload in self.planned_slots(campaign, rotation, runtime):
            available = [
                row
                for row in candidates
                if self._integer_identity(row.get("trained_chara_id")) not in used_trained_ids
                and self._candidate_base_chara_id(row) != rotation.next_trainee_chara_id
                and (
                    self._candidate_base_chara_id(row) <= 0
                    or self._candidate_base_chara_id(row) not in used_base_chara_ids
                )
            ]
            result = resolver.resolve_slot(
                LegacySlot(**dict(slot_payload)),
                candidates=available,
            )
            resolved.append(result)
            if result.get("status") == "RESOLVED":
                used_trained_ids.add(
                    self._integer_identity(result.get("trained_chara_id"))
                )
                base_chara_id = self._candidate_base_chara_id(result)
                if base_chara_id > 0:
                    used_base_chara_ids.add(base_chara_id)
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
                    "baseline_parent_ids": baseline_parent_ids,
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
        auto_use_best_veteran = bool(
            campaign["spec"]["options"].get("auto_use_best_veteran", False)
        )
        requires_approval = self._requires_pre_run_approval(
            campaign["spec"],
            ambiguous=bool(replacements) and not auto_use_best_veteran,
        )
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
            "pending_review": review if requires_approval else None,
            "review_required": requires_approval,
            "run_start": None,
            "baseline_parent_ids": baseline_parent_ids,
        }
        persisted = self.store.update_context(campaign_id, updates)
        if requires_approval:
            persisted = self.runner.require_user_input(campaign_id, "approve_run", review)
        else:
            for replacement in replacements:
                self.store.append_event(
                    campaign_id,
                    "automatic_legacy_replacement",
                    {"prepared_run_id": prepared_run_id, "replacement": replacement},
                )
            persisted = self.store.set_next_action(campaign_id, "start_career")
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
        if "legacy_slots" in request and not self._prepared_run_has_two_distinct_parents(request):
            refreshed = self.prepare_next_run(campaign_id)
            request = deepcopy(refreshed.get("prepared_run"))
            if not isinstance(request, dict) or not self._prepared_run_has_two_distinct_parents(request):
                raise ValueError("Campaign could not resolve two distinct parents")
        if selection_override:
            request.update(deepcopy(dict(selection_override)))
        if "legacy_slots" in request and not self._prepared_run_has_two_distinct_parents(request):
            raise ValueError("Campaign prepared run requires two distinct resolved parents")
        operation_id = self._stable_id("prepared-start", request)
        reservation = self.store.reserve_prepared_run_start(
            campaign_id,
            operation_id,
            prepared_run=request,
        )
        if not reservation["acquired"]:
            run_start = reservation["run_start"]
            if run_start["status"] == "STARTED":
                self.runner.begin_run(campaign_id)
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
        self.runner.begin_run(campaign_id)
        return result

    def _record_cycle_completed_veteran(
        self,
        campaign: Mapping[str, Any],
        candidate: Mapping[str, Any],
    ) -> dict[str, Any]:
        campaign_id = str(campaign["campaign_id"])
        spec = campaign["spec"]
        context = dict(campaign.get("context") or {})
        state = self._cycle_state(campaign)
        if state.final_stage_active:
            direct_totals = candidate.get("direct_lineage_spark_totals")
            if not isinstance(direct_totals, Mapping):
                direct_totals = direct_lineage_spark_totals(
                    candidate.get("factor_tree") or {}
                )
            target_result = evaluate_spark_targets(
                spec.get("spark_targets") or [],
                direct_totals,
            )
            displayed = candidate.get("displayed_affinity")
            if isinstance(displayed, Mapping):
                completed_affinity = self._integer_identity(
                    displayed.get("total", displayed.get("affinity"))
                )
            else:
                completed_affinity = self._integer_identity(
                    candidate.get("completed_displayed_affinity")
                )
            candidate_id = str(
                candidate.get("candidate_id")
                or self._stable_id("candidate", dict(candidate))
            )
            trained_id = self._integer_identity(candidate.get("trained_chara_id"))
            complete = bool(target_result["required_complete"])
            next_cycle = state if complete else record_final_repeat(state)
            decision = "accept" if complete else "repeat"
            evaluation = {
                "stage_kind": "cycle_final",
                "required_progress": target_result["required_progress"],
                "preferred_progress": target_result["preferred_progress"],
                "targets": target_result,
                "completed_displayed_affinity": completed_affinity,
                "projected_displayed_affinity": context.get("projected_displayed_affinity"),
                "factor_tree": deepcopy(candidate.get("factor_tree") or {}),
                "direct_lineage_spark_totals": self._serialized_spark_totals(
                    {"spark_totals": direct_totals}
                ),
                "spark_totals": self._serialized_spark_totals(
                    {"spark_totals": direct_totals}
                ),
                "rank_score": self._integer_identity(candidate.get("rank_score")),
                "accepted": complete,
                "decision": decision,
            }
            rank_score = self._integer_identity(candidate.get("rank_score"))
            score = (
                float(evaluation["required_progress"]) * 1_000_000_000
                + float(evaluation["preferred_progress"]) * 1_000_000
                + completed_affinity * 1_000
                + rank_score
            )
            context_updates: dict[str, Any] = {
                "pending_review": None,
                "review_required": False,
                "bootstrap_rotation": next_cycle.to_dict(),
                "completed_displayed_affinity": completed_affinity,
            }
            if complete:
                final_result = {
                    "candidate_id": candidate_id,
                    "trained_chara_id": trained_id,
                    "displayed_affinity": completed_affinity,
                }
                context_updates["final_parent_result"] = final_result
                context_updates["final_uma_result"] = final_result
            persisted = self.store.persist_candidate_result(
                campaign_id,
                candidate_id=candidate_id,
                trained_chara_id=trained_id,
                name=str(candidate.get("name") or ""),
                score=score,
                evaluation=evaluation,
                select=complete,
                state=(
                    CampaignState.COMPLETED
                    if complete
                    else CampaignState.SELECTING_LINEAGE
                ),
                next_action="" if complete else "prepare_next_run",
                context_updates=context_updates,
                expected_version=campaign.get("version"),
            )
            if persisted.get("replayed"):
                stored_evaluation = persisted["candidate"].get("evaluation") or {}
                return {
                    "campaign": persisted["campaign"],
                    "candidate": persisted["candidate"],
                    "decision": stored_evaluation.get("decision", "repeat"),
                    "targets": stored_evaluation.get("targets", {}),
                    "final_setup": {},
                }
            return {
                "campaign": persisted["campaign"],
                "candidate": persisted["candidate"],
                "decision": decision,
                "targets": target_result,
                "final_setup": {},
            }

        self_targets = ready_parent_targets(spec.get("spark_targets") or [])
        self_totals = candidate.get("self_spark_totals")
        if not isinstance(self_totals, Mapping):
            self_totals = self_spark_totals(candidate.get("factor_tree") or {})
        target_result = evaluate_spark_targets(self_targets, self_totals)

        displayed = candidate.get("displayed_affinity")
        if isinstance(displayed, Mapping):
            completed_affinity = self._integer_identity(
                displayed.get("total", displayed.get("affinity"))
            )
        else:
            completed_affinity = self._integer_identity(
                candidate.get("completed_displayed_affinity")
            )
        candidate_id = str(
            candidate.get("candidate_id")
            or self._stable_id("candidate", dict(candidate))
        )
        trained_id = self._integer_identity(candidate.get("trained_chara_id"))
        trainee_chara_id = state.next_bootstrap_chara_id
        next_cycle = advance_bootstrap_rotation(
            state,
            produced_legacy_id=str(trained_id or candidate_id),
        )

        ready_rows = [
            deepcopy(row)
            for row in (context.get("ready_parent_candidates") or [])
            if isinstance(row, Mapping)
        ]
        if target_result["required_complete"] and trained_id > 0:
            ready_row = self._ready_parent_with_compatibility(
                spec,
                {
                    "candidate_id": candidate_id,
                    "trained_chara_id": trained_id,
                    "bootstrap_chara_id": trainee_chara_id,
                    "self_spark_totals": self._serialized_spark_totals(
                        {"spark_totals": self_totals}
                    ),
                    "rank_score": self._integer_identity(candidate.get("rank_score")),
                },
            )
            ready_rows = [
                row
                for row in ready_rows
                if self._integer_identity(row.get("trained_chara_id")) != trained_id
            ]
            ready_rows.append(ready_row)

        if self._compatible_ready_parent_pairs(spec, ready_rows):
            next_cycle = enter_final_stage(next_cycle)
        decision = "enter_final" if next_cycle.final_stage_active else "advance"

        evaluation = {
            "stage_kind": "cycle_bootstrap",
            "trainee_chara_id": trainee_chara_id,
            "required_progress": target_result["required_progress"],
            "preferred_progress": target_result["preferred_progress"],
            "targets": target_result,
            "completed_displayed_affinity": completed_affinity,
            "projected_displayed_affinity": context.get("projected_displayed_affinity"),
            "aptitude_targets": deepcopy(context.get("aptitude_targets") or []),
            "aptitude_evidence": deepcopy(context.get("aptitude_evidence") or {}),
            "aptitude_shortfalls": deepcopy(context.get("aptitude_shortfalls") or []),
            "factor_tree": deepcopy(candidate.get("factor_tree") or {}),
            "self_spark_totals": self._serialized_spark_totals(
                {"spark_totals": self_totals}
            ),
            "spark_totals": self._serialized_spark_totals(candidate),
            "rank_score": self._integer_identity(candidate.get("rank_score")),
            "ready_parent": bool(target_result["required_complete"]),
            "accepted": False,
            "decision": decision,
        }
        rank_score = self._integer_identity(candidate.get("rank_score"))
        score = (
            float(evaluation["required_progress"]) * 1_000_000_000
            + float(evaluation["preferred_progress"]) * 1_000_000
            + completed_affinity * 1_000
            + rank_score
        )
        context_updates = {
            "pending_review": None,
            "review_required": False,
            "bootstrap_rotation": next_cycle.to_dict(),
            "ready_parent_candidates": ready_rows,
            "completed_displayed_affinity": completed_affinity,
        }
        persisted = self.store.persist_candidate_result(
            campaign_id,
            candidate_id=candidate_id,
            trained_chara_id=trained_id,
            name=str(candidate.get("name") or ""),
            score=score,
            evaluation=evaluation,
            select=False,
            state=CampaignState.SELECTING_LINEAGE,
            next_action="prepare_next_run",
            context_updates=context_updates,
            expected_version=campaign.get("version"),
        )
        if persisted.get("replayed"):
            stored_evaluation = persisted["candidate"].get("evaluation") or {}
            return {
                "campaign": persisted["campaign"],
                "candidate": persisted["candidate"],
                "decision": stored_evaluation.get("decision", "advance"),
                "targets": stored_evaluation.get("targets", {}),
                "final_setup": {},
            }
        return {
            "campaign": persisted["campaign"],
            "candidate": persisted["candidate"],
            "decision": decision,
            "targets": target_result,
            "final_setup": {},
        }

    def _record_stage_completed_veteran(
        self,
        campaign: Mapping[str, Any],
        candidate: Mapping[str, Any],
    ) -> dict[str, Any]:
        campaign_id = str(campaign["campaign_id"])
        spec = campaign["spec"]
        context = dict(campaign.get("context") or {})
        state = self._stage_state(campaign)
        final_stage = state.is_final_stage
        factor_targets = (
            list(spec.get("spark_targets") or [])
            if final_stage
            else list((context.get("stage_goal_assignments") or {}).get(str(state.stage_index), []))
        )
        target_result = evaluate_spark_targets(
            factor_targets,
            candidate.get("spark_totals", {}),
        )
        displayed = candidate.get("displayed_affinity")
        if isinstance(displayed, Mapping):
            completed_affinity = self._integer_identity(
                displayed.get("total", displayed.get("affinity"))
            )
        else:
            completed_affinity = self._integer_identity(
                candidate.get("completed_displayed_affinity")
            )
        candidate_id = str(candidate.get("candidate_id") or self._stable_id(
            "candidate",
            dict(candidate),
        ))
        trained_id = self._integer_identity(candidate.get("trained_chara_id"))
        next_stage_state = record_stage_result(
            state,
            produced_legacy_id=str(trained_id or candidate_id),
            goal_complete=bool(target_result["required_complete"]),
        )
        decision = (
            "accept"
            if final_stage and target_result["required_complete"]
            else "advance"
            if (not final_stage and target_result["required_complete"])
            else "repeat"
        )
        evaluation = {
            "stage_index": state.stage_index,
            "stage_kind": "final" if final_stage else "bootstrap",
            "required_progress": target_result["required_progress"],
            "preferred_progress": target_result["preferred_progress"],
            "targets": target_result,
            "completed_displayed_affinity": completed_affinity,
            "projected_displayed_affinity": context.get("projected_displayed_affinity"),
            "aptitude_targets": deepcopy(context.get("aptitude_targets") or []),
            "aptitude_evidence": deepcopy(context.get("aptitude_evidence") or {}),
            "aptitude_shortfalls": deepcopy(context.get("aptitude_shortfalls") or []),
            "factor_tree": deepcopy(candidate.get("factor_tree") or {}),
            "spark_totals": self._serialized_spark_totals(candidate),
            "accepted": bool(target_result["required_complete"]),
            "decision": decision,
        }
        rank_score = self._integer_identity(candidate.get("rank_score"))
        score = (
            float(evaluation["required_progress"]) * 1_000_000_000
            + float(evaluation["preferred_progress"]) * 1_000_000
            + completed_affinity * 1_000
            + rank_score
        )
        context_updates: dict[str, Any] = {
            "pending_review": None,
            "review_required": False,
            "stage_state": next_stage_state.to_dict(),
            "completed_displayed_affinity": completed_affinity,
        }
        if final_stage:
            target_state = (
                CampaignState.COMPLETED
                if target_result["required_complete"]
                else CampaignState.SELECTING_LINEAGE
            )
            next_action = "" if target_result["required_complete"] else "prepare_next_run"
            select = bool(target_result["required_complete"])
            if select:
                context_updates["final_parent_result"] = {
                    "candidate_id": candidate_id,
                    "trained_chara_id": trained_id,
                    "displayed_affinity": completed_affinity,
                }
        else:
            goal_state = deepcopy(context.get("bootstrap_goal_state") or {})
            goal_state[str(state.stage_index)] = {
                "complete": bool(target_result["required_complete"]),
                "required_progress": target_result["required_progress"],
                "preferred_progress": target_result["preferred_progress"],
                "candidate_id": candidate_id,
                "trained_chara_id": trained_id,
            }
            context_updates["bootstrap_goal_state"] = goal_state
            target_state = CampaignState.SELECTING_LINEAGE
            next_action = "prepare_next_run"
            select = False

        persisted = self.store.persist_candidate_result(
            campaign_id,
            candidate_id=candidate_id,
            trained_chara_id=trained_id,
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
                "decision": stored_evaluation.get("decision", "repeat"),
                "targets": stored_evaluation.get("targets", {}),
                "final_setup": {},
            }
        return {
            "campaign": persisted["campaign"],
            "candidate": persisted["candidate"],
            "decision": decision,
            "targets": target_result,
            "final_setup": {},
        }

    def record_completed_veteran(
        self,
        campaign_id: str,
        candidate: Mapping[str, Any],
        final_pairings: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        campaign = self.store.get(campaign_id)
        spec = campaign["spec"]
        context = campaign.get("context") or {}
        if (
            int(spec.get("spec_version") or 0) >= 3
            and not isinstance(context.get("bootstrap_rotation"), Mapping)
        ):
            campaign = self._ensure_v3_cycle_migration(campaign)
            spec = campaign["spec"]
            context = campaign.get("context") or {}
        if (
            int(spec.get("spec_version") or 0) >= 3
            or isinstance(context.get("bootstrap_rotation"), Mapping)
        ):
            return self._record_cycle_completed_veteran(campaign, candidate)
        if isinstance(context.get("stage_state"), Mapping):
            return self._record_stage_completed_veteran(campaign, candidate)
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
            "factor_tree": deepcopy(candidate.get("factor_tree") or {}),
            "spark_totals": self._serialized_spark_totals(candidate),
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
        rotation = advance_rotation(
            self._rotation(campaign),
            produced_legacy_id=str(candidate.get("trained_chara_id") or candidate_id),
        )
        context_updates: dict[str, Any] = {
            "pending_review": None,
            "review_required": False,
            "rotation": rotation.to_dict(),
        }
        stop_when_target_reached = bool(
            spec["strategy"].get("stop_when_target_reached", True)
        ) and not bool((campaign.get("context") or {}).get("continue_preferred", False))
        if can_complete:
            select = True
            if stop_when_target_reached:
                target_state = CampaignState.COMPLETED
                next_action = ""
            else:
                target_state = CampaignState.SELECTING_LINEAGE
                next_action = "prepare_next_run"
                context_updates.update({
                    "required_target_achieved": True,
                    "continue_preferred": True,
                })
        elif decision == "tradeoff":
            target_state = CampaignState.NEEDS_USER_INPUT
            next_action = "select_candidate"
            select = False
            context_updates.update({
                "pending_review": {
                    "kind": "candidate_tradeoff",
                    "candidate_id": candidate_id,
                    "candidate_ids": [
                        value
                        for value in (
                            str(current_best.get("candidate_id") or "") if current_best else "",
                            candidate_id,
                        )
                        if value
                    ],
                    "evaluation": evaluation,
                },
                "review_required": True,
            })
        else:
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
        stop_when_target_reached = bool(
            campaign["spec"]["strategy"].get("stop_when_target_reached", True)
        ) and not bool((campaign.get("context") or {}).get("continue_preferred", False))
        should_complete = complete and stop_when_target_reached
        context_updates = {"pending_review": None, "review_required": False}
        if complete and not stop_when_target_reached:
            context_updates.update({
                "required_target_achieved": True,
                "continue_preferred": True,
            })
        allowed_candidate_ids = {
            str(campaign.get("selected_candidate_id") or ""),
        }
        allowed_candidate_ids.discard("")
        return self.store.apply_candidate_selection(
            campaign_id,
            candidate_id,
            state=CampaignState.COMPLETED if should_complete else CampaignState.SELECTING_LINEAGE,
            next_action="" if should_complete else "prepare_next_run",
            context_updates=context_updates,
            allowed_candidate_ids=allowed_candidate_ids,
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
    def _serialized_spark_totals(candidate: Mapping[str, Any]) -> dict[str, int]:
        result: dict[str, int] = {}
        for raw_key, raw_value in (candidate.get("spark_totals") or {}).items():
            if isinstance(raw_key, tuple) and len(raw_key) == 2:
                category, name = raw_key
            else:
                category, separator, name = str(raw_key).partition(":")
                if not separator:
                    continue
            normalized_category = str(category or "").strip().lower()
            normalized_name = str(name or "").strip().lower()
            if not normalized_category or not normalized_name:
                continue
            try:
                stars = max(0, int(raw_value or 0))
            except (TypeError, ValueError):
                stars = 0
            result[f"{normalized_category}:{normalized_name}"] = stars
        return result

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
        nested = prepared_run.get("career_request")
        expected = dict(nested) if isinstance(nested, Mapping) else dict(prepared_run)
        if not expected:
            return False
        for key in ("account", "campaign_id"):
            if key not in expected and prepared_run.get(key):
                expected[key] = prepared_run[key]
        expected_card = cls._career_card_id(expected)
        if expected_card:
            if cls._career_card_id(current_career) != expected_card:
                return False
        else:
            expected_trainee = int(expected.get("trainee_chara_id") or 0)
            current_trainee = cls._integer_identity(current_career.get("trainee_chara_id"))
            if current_trainee <= 0:
                current_card = cls._career_card_id(current_career)
                current_trainee = current_card // 100 if current_card >= 100000 else current_card
            if not expected_trainee or current_trainee != expected_trainee:
                return False
        expected_parents = cls._prepared_parent_ids(expected)
        identity = {
            "deck_id": cls._integer_identity(expected.get("deck_id")),
            "parent_id_1": expected_parents[0],
            "parent_id_2": expected_parents[1],
        }
        for key, expected_value in identity.items():
            if cls._integer_identity(current_career.get(key)) != expected_value:
                return False
        for key in ("account", "campaign_id"):
            expected_value = str(expected.get(key) or "")
            current_value = str(current_career.get(key) or "")
            if expected_value and current_value != expected_value:
                return False
        return True

    @staticmethod
    def _trusted_current_career(
        campaign: Mapping[str, Any],
        snapshot: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        if "current_career" not in snapshot:
            return None
        current = snapshot.get("current_career")
        if current is None:
            current = {"active": False}
        if not isinstance(current, Mapping):
            return None
        return {
            **dict(current),
            "account": str(campaign["account"]),
            "campaign_id": str(campaign["campaign_id"]),
        }

    @staticmethod
    def _career_card_id(career: Mapping[str, Any]) -> int:
        trainee = career.get("trainee")
        nested = trainee.get("card_id") if isinstance(trainee, Mapping) else 0
        return CampaignService._integer_identity(
            career.get("card_id") or career.get("trainee_card_id") or nested
        )

    @staticmethod
    def _integer_identity(value: Any) -> int:
        if isinstance(value, bool):
            return 0
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    @classmethod
    def _prepared_parent_ids(cls, prepared_run: Mapping[str, Any]) -> tuple[int, int]:
        direct = (
            cls._integer_identity(prepared_run.get("parent_id_1")),
            cls._integer_identity(prepared_run.get("parent_id_2")),
        )
        slots = prepared_run.get("legacy_slots") or prepared_run.get("parents") or []
        resolved = [
            cls._integer_identity(row.get("trained_chara_id"))
            for row in slots
            if isinstance(row, Mapping)
        ]
        return (
            direct[0] or (resolved[0] if resolved else 0),
            direct[1] or (resolved[1] if len(resolved) > 1 else 0),
        )

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
    def _default_slots(campaign: Mapping[str, Any], rotation: RotationState, _runtime: Mapping[str, Any]) -> list[dict[str, Any]]:
        target = campaign["spec"].get("final_parent") or {}
        trained_id = int(target.get("trained_chara_id") or 0)
        target_chara_id = int(target.get("chara_id") or 0)
        lock_target = bool(
            trained_id
            and target_chara_id
            and target_chara_id != rotation.next_trainee_chara_id
        )
        return [
            {
                "role": "parent1",
                "mode": "LOCKED" if lock_target else "FLEXIBLE",
                "trained_chara_id": trained_id if lock_target else 0,
            },
            {"role": "parent2", "mode": "FLEXIBLE", "trained_chara_id": 0},
        ]

    @classmethod
    def _candidate_base_chara_id(cls, row: Mapping[str, Any]) -> int:
        direct = cls._integer_identity(
            row.get("base_chara_id") or row.get("chara_id")
        )
        if direct > 0:
            return direct
        card_id = cls._integer_identity(
            row.get("card_id") or row.get("race_cloth_id")
        )
        return card_id // 100 if card_id >= 100000 else 0

    @classmethod
    def _prepared_run_has_two_distinct_parents(
        cls,
        prepared_run: Mapping[str, Any],
    ) -> bool:
        parent1, parent2 = cls._prepared_parent_ids(prepared_run)
        return parent1 > 0 and parent2 > 0 and parent1 != parent2

    @staticmethod
    def _candidate_score(row: Mapping[str, Any]) -> float:
        for key in ("score", "rank_score", "rank"):
            value = row.get(key)
            if isinstance(value, bool):
                continue
            if isinstance(value, Real) and isfinite(value):
                return float(value)
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                continue
            if isfinite(numeric):
                return numeric
        return 0.0

    @classmethod
    def _default_candidates(cls, campaign: Mapping[str, Any], rotation: RotationState, runtime: Mapping[str, Any]) -> list[dict[str, Any]]:
        del rotation
        context = campaign.get("context") or {}
        sources = (
            (runtime.get("owned_candidates") or [], False),
            (context.get("campaign_candidates") or [], None),
            (runtime.get("rental_candidates") or [], True),
        )
        unique: dict[int, dict[str, Any]] = {}
        for rows, rental_override in sources:
            for raw in rows:
                if not isinstance(raw, Mapping):
                    continue
                trained_id = cls._integer_identity(
                    raw.get("trained_chara_id") or raw.get("instance_id")
                )
                if trained_id <= 0 or trained_id in unique:
                    continue
                rental = raw.get("rental") is True if rental_override is None else rental_override
                unique[trained_id] = {
                    **dict(raw),
                    "trained_chara_id": trained_id,
                    "score": cls._candidate_score(raw),
                    "rental": rental,
                }
        return [unique[key] for key in sorted(unique)]

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
        request = {
            "account": campaign["account"],
            "preset": self.preset_store.load(spec["strategy"]["preset_name"]),
            "trainee_chara_id": rotation.next_trainee_chara_id,
            "deck_id": deck_id,
            "legacy_slots": list(resolved),
            "race_overrides": deepcopy(dict(races) if isinstance(races, Mapping) else list(races)),
            "campaign_id": campaign["campaign_id"],
        }
        friend_support = (member or {}).get("friend_support")
        if isinstance(friend_support, Mapping):
            request["friend_support"] = deepcopy(dict(friend_support))
        return request


__all__ = ["CampaignService"]
