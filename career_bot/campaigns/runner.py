from __future__ import annotations

from typing import Any

from .models import ApprovalMode, CampaignState, ParentGoal
from .parent_evaluator import evaluate_parent_candidate
from .store import BudgetExceeded, CampaignStore, InvalidTransition


class CampaignRunner:
    """Deterministic campaign coordinator.

    It advances coarse campaign state only. Sweepy's existing CareerRunner remains
    responsible for turn-by-turn gameplay and API recovery.
    """

    def __init__(self, store: CampaignStore) -> None:
        self.store = store

    @staticmethod
    def _runtime_flag(runtime: dict[str, Any], name: str) -> bool:
        if name in runtime:
            return bool(runtime.get(name))
        api = runtime.get("api") if isinstance(runtime.get("api"), dict) else {}
        if name == "api_reachable":
            return bool(api.get("reachable"))
        if name == "logged_in":
            return bool(api.get("logged_in"))
        return False

    @staticmethod
    def _bot_logged_in(bot_state: dict[str, Any]) -> bool:
        session = bot_state.get("session") if isinstance(bot_state.get("session"), dict) else {}
        return bool(session.get("logged_in"))

    @staticmethod
    def _career_running(bot_state: dict[str, Any]) -> bool:
        runner = (
            bot_state.get("career_runner")
            if isinstance(bot_state.get("career_runner"), dict)
            else {}
        )
        return bool(runner.get("running"))

    @staticmethod
    def _dailies_running(bot_state: dict[str, Any]) -> bool:
        dailies = bot_state.get("dailies") if isinstance(bot_state.get("dailies"), dict) else {}
        return bool(dailies.get("running"))

    def start(
        self,
        campaign_id: str,
        *,
        runtime: dict[str, Any],
        bot_state: dict[str, Any],
    ) -> dict[str, Any]:
        campaign = self.store.get(campaign_id)
        state = CampaignState(campaign["state"])
        if state is CampaignState.DRAFT:
            campaign = self.store.transition(
                campaign_id,
                CampaignState.READY,
                next_action="inspect_runtime",
            )
        elif state in {
            CampaignState.COMPLETED,
            CampaignState.FAILED,
            CampaignState.CANCELLED,
        }:
            return campaign
        elif state is CampaignState.PAUSED:
            raise InvalidTransition(f"Campaign {campaign_id} is paused")
        return self.reconcile(campaign_id, runtime=runtime, bot_state=bot_state)

    def reconcile(
        self,
        campaign_id: str,
        *,
        runtime: dict[str, Any],
        bot_state: dict[str, Any],
    ) -> dict[str, Any]:
        campaign = self.store.get(campaign_id)
        state = CampaignState(campaign["state"])
        if state in {
            CampaignState.COMPLETED,
            CampaignState.FAILED,
            CampaignState.CANCELLED,
            CampaignState.PAUSED,
        }:
            return campaign

        try:
            self.store.assert_within_budget(campaign_id)
        except BudgetExceeded as exc:
            if state is CampaignState.DRAFT:
                campaign = self.store.transition(campaign_id, CampaignState.READY)
            return self.store.transition(
                campaign_id,
                CampaignState.FAILED,
                error=str(exc),
            )

        if self._dailies_running(bot_state):
            if state in {
                CampaignState.SELECTING_LINEAGE,
                CampaignState.EVALUATING_RESULT,
                CampaignState.NEEDS_USER_INPUT,
            }:
                return self.store.transition(
                    campaign_id,
                    CampaignState.NEEDS_USER_INPUT,
                    next_action="stop_dailies_or_pause_campaign",
                    error="Dailies are active on the campaign account",
                )
            return campaign

        api_reachable = self._runtime_flag(runtime, "api_reachable")
        logged_in = self._runtime_flag(runtime, "logged_in") or self._bot_logged_in(bot_state)

        if state is CampaignState.READY:
            campaign = self.store.transition(
                campaign_id,
                CampaignState.STARTING_BOT,
                next_action="launch_bot" if not api_reachable else "inspect_login",
            )
            state = CampaignState(campaign["state"])

        if state is CampaignState.STARTING_BOT:
            if not api_reachable:
                return campaign
            if not logged_in:
                return self.store.transition(
                    campaign_id,
                    CampaignState.WAITING_FOR_LOGIN,
                    next_action="wait_for_login",
                )
            return self.store.transition(
                campaign_id,
                CampaignState.SELECTING_LINEAGE,
                next_action="select_lineage",
            )

        if state is CampaignState.WAITING_FOR_LOGIN:
            if not logged_in:
                return campaign
            return self.store.transition(
                campaign_id,
                CampaignState.SELECTING_LINEAGE,
                next_action="select_lineage",
            )

        if state is CampaignState.RUNNING_CAREER:
            if self._career_running(bot_state):
                return campaign
            return self.store.transition(
                campaign_id,
                CampaignState.EVALUATING_RESULT,
                next_action="evaluate_result",
            )

        if state is CampaignState.WAITING_FOR_TP:
            session = bot_state.get("session") if isinstance(bot_state.get("session"), dict) else {}
            account = session.get("account") if isinstance(session.get("account"), dict) else {}
            tp = account.get("tp") if isinstance(account.get("tp"), dict) else {}
            if int(tp.get("current") or 0) >= 30:
                return self.store.transition(
                    campaign_id,
                    CampaignState.SELECTING_LINEAGE,
                    next_action="select_lineage",
                )

        return campaign

    def begin_run(self, campaign_id: str) -> dict[str, Any]:
        campaign = self.store.get(campaign_id)
        state = CampaignState(campaign["state"])
        if state not in {CampaignState.SELECTING_LINEAGE, CampaignState.WAITING_FOR_TP}:
            raise InvalidTransition(
                f"Campaign {campaign_id} cannot begin a run from {state.value}"
            )
        self.store.assert_within_budget(campaign_id)
        self.store.add_usage(campaign_id, runs=1)
        return self.store.transition(
            campaign_id,
            CampaignState.RUNNING_CAREER,
            next_action="monitor_career",
        )

    def record_candidate(
        self,
        campaign_id: str,
        candidate: dict[str, Any],
        *,
        baseline_score: float | None = None,
    ) -> dict[str, Any]:
        campaign = self.store.get(campaign_id)
        state = CampaignState(campaign["state"])
        if state is not CampaignState.EVALUATING_RESULT:
            raise InvalidTransition(
                f"Campaign {campaign_id} cannot record a candidate from {state.value}"
            )

        if baseline_score is None:
            existing = self.store.list_candidates(campaign_id)
            if existing:
                baseline_score = max(float(row["score"]) for row in existing)

        goal = ParentGoal.model_validate(campaign["spec"]["goal"])
        evaluation = evaluate_parent_candidate(
            goal,
            candidate,
            baseline_score=baseline_score,
        )
        stored_candidate = self.store.add_candidate(
            campaign_id,
            trained_chara_id=int(candidate.get("trained_chara_id") or 0),
            name=str(candidate.get("name") or ""),
            score=float(evaluation["score"]),
            evaluation=evaluation,
        )

        strategy = campaign["spec"]["strategy"]
        approval_mode = ApprovalMode(strategy["approval_mode"])
        requires_user = (
            approval_mode is ApprovalMode.PER_GENERATION
            or (
                approval_mode is ApprovalMode.AMBIGUITY_ONLY
                and evaluation["decision"] == "ambiguous"
            )
        )

        if evaluation["accepted"] and evaluation["decision"] != "reject":
            if requires_user:
                updated = self.store.transition(
                    campaign_id,
                    CampaignState.NEEDS_USER_INPUT,
                    next_action="select_candidate",
                )
            else:
                stored_candidate = self.store.select_candidate(
                    campaign_id,
                    stored_candidate["candidate_id"],
                )
                if bool(strategy.get("stop_when_target_reached", True)):
                    updated = self.store.transition(
                        campaign_id,
                        CampaignState.COMPLETED,
                        next_action="",
                    )
                else:
                    updated = self.store.transition(
                        campaign_id,
                        CampaignState.SELECTING_LINEAGE,
                        next_action="select_lineage",
                    )
        else:
            maximum_runs = int(strategy["maximum_runs"])
            if int(campaign["usage"]["runs"]) >= maximum_runs:
                updated = self.store.transition(
                    campaign_id,
                    CampaignState.FAILED,
                    error=f"maximum_runs exhausted ({maximum_runs}) without an accepted candidate",
                )
            else:
                updated = self.store.transition(
                    campaign_id,
                    CampaignState.SELECTING_LINEAGE,
                    next_action="select_lineage",
                )

        return {
            "campaign": updated,
            "candidate": stored_candidate,
            "evaluation": evaluation,
        }

    def select_candidate(
        self,
        campaign_id: str,
        candidate_id: str,
    ) -> dict[str, Any]:
        campaign = self.store.get(campaign_id)
        state = CampaignState(campaign["state"])
        if state is not CampaignState.NEEDS_USER_INPUT:
            raise InvalidTransition(
                f"Campaign {campaign_id} cannot select a candidate from {state.value}"
            )
        candidate = self.store.select_candidate(campaign_id, candidate_id)
        strategy = campaign["spec"]["strategy"]
        if candidate["accepted"] and bool(strategy.get("stop_when_target_reached", True)):
            updated = self.store.transition(
                campaign_id,
                CampaignState.COMPLETED,
                next_action="",
            )
        else:
            updated = self.store.transition(
                campaign_id,
                CampaignState.SELECTING_LINEAGE,
                next_action="select_lineage",
            )
        return {"campaign": updated, "candidate": candidate}

    def pause(self, campaign_id: str) -> dict[str, Any]:
        return self.store.pause(campaign_id)

    def resume(self, campaign_id: str) -> dict[str, Any]:
        return self.store.resume(campaign_id)

    def cancel(self, campaign_id: str, *, reason: str = "") -> dict[str, Any]:
        return self.store.cancel(campaign_id, reason=reason)
