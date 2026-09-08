from __future__ import annotations

from typing import Any

from sweepy_jobs import LeaseConflict

from .models import IndependentSetup, IndependentTrainingPreset
from .store import PresetNotFound, RunNotFound


class WorkflowConflict(RuntimeError):
    pass


_PRIVATE_KEYS = {
    "friend_viewer_id",
    "rental_viewer_id",
    "viewer_id",
    "sid",
    "device",
    "device_data",
    "steam",
    "steam_ticket",
}


def _public_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _public_value(child)
            for key, child in value.items()
            if str(key).casefold() not in _PRIVATE_KEYS
            and not str(key).casefold().endswith("viewer_id")
        }
    if isinstance(value, (list, tuple)):
        return [_public_value(child) for child in value]
    return value


def _setup_summary(setup: dict[str, Any]) -> dict[str, Any]:
    reroll = setup.get("factor_reroll") or {}
    return {
        "card_id": int(setup.get("card_id") or 0),
        "support_card_ids": [
            int(value) for value in setup.get("support_card_ids") or []
        ],
        "friend_card_id": int(setup.get("friend_card_id") or 0),
        "parent_id_1": int(setup.get("parent_id_1") or 0),
        "parent_id_2": int(setup.get("parent_id_2") or 0),
        "scenario_id": int(setup.get("scenario_id") or 0),
        "running_style": int(setup.get("running_style") or 0),
        "factor_reroll": {
            "enabled": bool(reroll.get("enabled")),
            "targets": _public_value(reroll.get("targets") or []),
        },
    }


def _public_run(run: dict[str, Any]) -> dict[str, Any]:
    result = {
        key: value
        for key, value in run.items()
        if key not in {"setup", "finalization", "factor_candidates"}
    }
    result["setup_summary"] = _setup_summary(run.get("setup") or {})
    return _public_value(result)


def _public_preset_summary(preset: dict[str, Any]) -> dict[str, Any]:
    return _public_value({
        "name": preset.get("name") or "",
        "count": int(preset.get("count") or 1),
        "tp_mode": preset.get("tp_mode") or "wait",
        "created_at": preset.get("created_at"),
        "updated_at": preset.get("updated_at"),
        "setup_summary": _setup_summary(preset.get("setup") or {}),
    })


class IndependentTrainingService:
    def __init__(
        self,
        store,
        runner,
        job_store,
        *,
        account_provider,
        dashboard_provider,
        busy_workflow_provider,
        pre_start_provider,
        lease_ttl_seconds: float = 120,
    ) -> None:
        self.store = store
        self.runner = runner
        self.job_store = job_store
        self.account_provider = account_provider
        self.dashboard_provider = dashboard_provider
        self.busy_workflow_provider = busy_workflow_provider
        self.pre_start_provider = pre_start_provider
        self.lease_ttl_seconds = float(lease_ttl_seconds)

    def _account(self) -> str:
        account = str(self.account_provider() or "").strip()
        if not account:
            raise ValueError("dashboard instance has no bound account")
        return account

    def _owner(self, account: str) -> str:
        return f"independent-training:{account}"

    def bootstrap(self) -> dict[str, Any]:
        account = self._account()
        dashboard = dict(self.dashboard_provider() or {})
        pre_start = dict(self.pre_start_provider() or {})
        status = self.status()
        return _public_value(
            {
                "account": account,
                "account_label": dashboard.get("account_label") or account,
                "trainees": dashboard.get("trainees") or [],
                "parents": dashboard.get("parents") or [],
                "support_cards": dashboard.get("support_cards") or [],
                "decks": dashboard.get("decks") or [],
                "saved_race_agendas": (
                    dashboard.get("saved_race_agendas") or []
                ),
                "reserved_race_info": (
                    pre_start.get("reserved_race_info") or []
                ),
                "last_idle_single_mode_start_info": (
                    pre_start.get("last_idle_single_mode_start_info") or {}
                ),
                "detected_tp_cost": pre_start.get("detected_tp_cost"),
                "tp_cost_source": pre_start.get("tp_cost_source") or "",
                "tp_cost_error": pre_start.get("tp_cost_error") or "",
                "presets": self.list_presets(),
                "status": status,
            }
        )

    def list_presets(self) -> list[dict[str, Any]]:
        account = self._account()
        return [
            _public_preset_summary(preset)
            for preset in self.store.list_presets(account)
        ]

    def save_preset(
        self,
        name: str,
        setup: dict[str, Any],
        *,
        count: int,
        tp_mode: str,
    ) -> dict[str, Any]:
        account = self._account()
        preset = IndependentTrainingPreset.model_validate({
            "name": name,
            "setup": setup,
            "count": count,
            "tp_mode": tp_mode,
        })
        validated_setup = preset.setup.model_dump(mode="json")
        self._validate_dashboard_setup(validated_setup)
        stored = self.store.save_preset(
            account,
            preset.name,
            validated_setup,
            count=preset.count,
            tp_mode=preset.tp_mode.value,
        )
        return _public_preset_summary(stored)

    def get_preset(self, name: str) -> dict[str, Any]:
        account = self._account()
        stored = self.store.get_preset(account, name)
        preset = IndependentTrainingPreset.model_validate({
            "name": stored["name"],
            "setup": stored["setup"],
            "count": stored["count"],
            "tp_mode": stored["tp_mode"],
        })
        setup = preset.setup.model_dump(mode="json")
        dashboard = dict(self.dashboard_provider() or {})
        self._validate_dashboard_setup(setup, allow_missing_friend=True)
        return _public_value({
            "name": preset.name,
            "setup": setup,
            "count": preset.count,
            "tp_mode": preset.tp_mode.value,
            "friend_index": self._friend_index(setup, dashboard),
        })

    def delete_preset(self, name: str) -> dict[str, Any]:
        account = self._account()
        if not self.store.delete_preset(account, name):
            raise PresetNotFound(
                f"Independent Training preset not found: {name}"
            )
        return {"deleted": True, "name": str(name).strip()}

    def enqueue(
        self,
        setup: dict[str, Any],
        *,
        count: int,
        tp_mode: str,
    ) -> dict[str, Any]:
        account = self._account()
        validated = IndependentSetup.model_validate(setup).model_dump(
            mode="json"
        )
        self._validate_dashboard_setup(validated)
        runs = self.store.enqueue(
            account,
            validated,
            count=int(count),
            tp_mode=tp_mode,
        )
        return {"runs": [_public_run(run) for run in runs]}

    def start(self, *, clear_stop: bool = False) -> dict[str, Any]:
        account = self._account()
        if clear_stop:
            # An explicit dashboard start means "run the queue"; leaving
            # stop_after_current set would park the executor in STOPPED on
            # its first tick without ever claiming a queued run.
            self.store.set_stop_after_current(account, False)
        busy = self.busy_workflow_provider()
        if busy:
            if isinstance(busy, dict):
                busy = (
                    busy.get("workflow_type")
                    or busy.get("type")
                    or busy.get("state")
                    or str(busy)
                )
            raise WorkflowConflict(
                f"Account {account} has active {busy} workflow"
            )
        try:
            lease = self.job_store.acquire_workflow_lease(
                account,
                owner=self._owner(account),
                workflow_type="independent_training",
                ttl_seconds=self.lease_ttl_seconds,
                metadata={"source": "dashboard"},
            )
        except LeaseConflict as exc:
            raise WorkflowConflict(str(exc)) from exc
        self.runner.start(account)
        return {
            "accepted": True,
            "account": account,
            "lease": _public_value(lease),
            "runner": self.runner.snapshot(),
        }

    def status(self) -> dict[str, Any]:
        account = self._account()
        reconciled = self.runner.reconcile_load_index(account)
        active = self.store.active_run(account)
        runner_state = str((self.runner.snapshot() or {}).get("state") or "")
        resume_confirmed_run = bool(
            active
            and active.get("state") == "RUNNING"
            and float(active.get("server_end_time") or 0) > 0
            and not active.get("error")
            and runner_state in {"IDLE", "NEEDS_ATTENTION", "STOPPED"}
        )
        if reconciled or resume_confirmed_run:
            self.start()
        self.store.mark_stale_unconfirmed_starts(account)
        describe = getattr(self.runner, "describe_server_run", None)
        untracked = describe(account) if callable(describe) else None
        return {
            "account": account,
            "untracked_server_run": _public_value(untracked),
            "runner": _public_value(self.runner.snapshot()),
            "control": self.store.get_control(account),
            "lease": _public_value(
                self.job_store.get_workflow_lease(account)
            ),
            "runs": [
                _public_run(run)
                for run in self.store.list_status_runs(account)
            ],
            "events": _public_value(self.store.list_events(account)),
        }

    def stop_after_current(self) -> dict[str, Any]:
        account = self._account()
        control = self.store.set_stop_after_current(account, True)
        self.runner.wake()
        return {"accepted": True, "control": control}

    def resume(self) -> dict[str, Any]:
        account = self._account()
        control = self.store.set_stop_after_current(account, False)
        started = self.start()
        return {
            "accepted": True,
            "control": control,
            "runner": started["runner"],
        }

    def cancel(self, run_id: str) -> dict[str, Any]:
        account = self._account()
        run = self.store.get(run_id)
        if run.get("account") != account:
            raise ValueError("run does not belong to bound account")
        return _public_run(self.store.cancel_queued(run_id))

    def adopt_server_run(self) -> dict[str, Any]:
        account = self._account()
        run = self.runner.adopt_server_run(account)
        if run is None:
            raise RunNotFound(
                f"No untracked server career found for {account}"
            )
        started = self.start()
        return {
            "accepted": True,
            "account": account,
            "run": _public_run(run),
            "runner": started["runner"],
        }

    def discard(
        self,
        run_id: str | None = None,
        *,
        reason: str = "",
    ) -> dict[str, Any]:
        account = self._account()
        if run_id is None:
            run = self.store.active_run(account)
            if run is None:
                raise RunNotFound(
                    f"No active Independent Training run for {account}"
                )
        else:
            run = self.store.get(run_id)
        if run.get("account") != account:
            raise ValueError("run does not belong to bound account")

        rejected_start_conflict = bool(
            run.get("start_attempted")
            and "API error 102 on idle_single_mode/start"
            in str(run.get("error") or "")
        )
        server_backed = bool(
            float(run.get("server_start_time") or 0) > 0
            or run.get("collection_attempted")
            or run.get("finish_attempted")
            or run.get("finalization")
            or (run.get("start_attempted") and not rejected_start_conflict)
        )
        if server_backed:
            if self._retry_active_reconciliation(account):
                self.start()
                return _public_run(self.store.get(run["run_id"]))
            raise WorkflowConflict(
                "Run still has confirmed server-side career state; "
                "it must be reconciled before it can be removed"
            )

        discarded = self.store.discard(run["run_id"], reason=reason)
        self.store.append_event(
            account,
            "run_discarded",
            {
                "run_id": discarded["run_id"],
                "previous_state": run.get("state"),
                "reason": discarded.get("error") or "",
            },
            run_id=discarded["run_id"],
        )
        if rejected_start_conflict:
            adopted = self.runner.adopt_server_run(account)
            if adopted is not None:
                self.start()
                return _public_run(discarded)
        self.runner.wake()
        return _public_run(discarded)

    def _retry_active_reconciliation(self, account: str) -> bool:
        return bool(
            self.runner.retry_start_reconciliation(account)
            or self.runner.retry_setup_reconciliation(account)
            or self.runner.retry_collection_reconciliation(account)
            or self.runner.retry_finish_reconciliation(account)
            or self.runner.retry_completed_reconciliation(account)
            or self.runner.retry_finalization_reconciliation(account)
        )

    def reconcile(self) -> dict[str, Any]:
        account = self._account()
        if self._retry_active_reconciliation(account):
            self.start()
        else:
            self.runner.wake()
        return {
            "accepted": True,
            "account": account,
            "runner": self.runner.snapshot(),
        }

    def heartbeat(self) -> dict[str, Any]:
        account = self._account()
        try:
            return self.job_store.heartbeat_workflow_lease(
                account,
                owner=self._owner(account),
                ttl_seconds=self.lease_ttl_seconds,
            )
        except LeaseConflict as exc:
            # The executor loop can sleep far longer than the lease TTL
            # (e.g. waiting hours for TP regen). If the lease merely lapsed
            # while we still own the workflow, re-acquire it instead of
            # parking the active run in NEEDS_ATTENTION forever.
            if self.store.active_run(account) is None:
                raise WorkflowConflict(str(exc)) from exc
            try:
                return self.job_store.acquire_workflow_lease(
                    account,
                    owner=self._owner(account),
                    workflow_type="independent_training",
                    ttl_seconds=self.lease_ttl_seconds,
                    metadata={"source": "heartbeat-reacquire"},
                )
            except LeaseConflict as reacquire_exc:
                raise WorkflowConflict(str(reacquire_exc)) from reacquire_exc

    def release_lease(self) -> bool:
        account = self._account()
        return self.job_store.release_workflow_lease(
            account,
            owner=self._owner(account),
            workflow_type="independent_training",
        )

    @staticmethod
    def _friend_index(setup: dict[str, Any], dashboard: dict[str, Any]) -> int | None:
        requested_friend = (
            int(setup.get("friend_viewer_id") or 0),
            int(setup.get("friend_card_id") or 0),
        )
        for index, row in enumerate(dashboard.get("friend_supports") or []):
            candidate = (
                int(row.get("viewer_id") or 0),
                int(
                    row.get("support_card_id")
                    or row.get("card_id")
                    or row.get("id")
                    or 0
                ),
            )
            if candidate == requested_friend:
                return index
        return None

    def _validate_dashboard_setup(
        self,
        setup: dict[str, Any],
        *,
        allow_missing_friend: bool = False,
    ) -> None:
        dashboard = dict(self.dashboard_provider() or {})
        trainee_by_card = {
            int(row.get("card_id") or row.get("id") or 0): row
            for row in dashboard.get("trainees") or []
        }
        parent_by_id = {
            int(
                row.get("trained_chara_id")
                or row.get("instance_id")
                or row.get("id")
                or 0
            ): row
            for row in dashboard.get("parents") or []
        }
        trainee = trainee_by_card.get(int(setup["card_id"]))
        if trainee is None:
            raise ValueError("selected trainee is not available in dashboard")
        parents = [
            parent_by_id.get(int(setup["parent_id_1"])),
            parent_by_id.get(int(setup["parent_id_2"])),
        ]
        if any(parent is None for parent in parents):
            raise ValueError("selected parent is not available in dashboard")

        trainee_base = int(
            trainee.get("base_chara_id")
            or trainee.get("chara_id")
            or 0
        )
        parent_bases = {
            int(
                parent.get("base_chara_id")
                or parent.get("chara_id")
                or 0
            )
            for parent in parents
            if parent is not None
        }
        if trainee_base and trainee_base in parent_bases:
            raise ValueError(
                "parent cannot use the same base character as trainee"
            )

        decks = {
            int(row.get("id") or row.get("deck_id") or 0): row
            for row in dashboard.get("decks") or []
            if int(row.get("id") or row.get("deck_id") or 0)
        }
        selected_deck = decks.get(int(setup["deck_id"]))
        if decks and selected_deck is None:
            raise ValueError("selected saved deck is not available")
        if selected_deck is not None:
            deck_supports = [
                int(
                    card.get("id")
                    or card.get("support_card_id")
                    or card.get("card_id")
                    or 0
                )
                for card in selected_deck.get("cards") or []
            ]
            if deck_supports != [
                int(value) for value in setup["support_card_ids"]
            ]:
                raise ValueError(
                    "selected support cards do not match saved deck"
                )

        available_supports = {
            int(
                row.get("support_card_id")
                or row.get("card_id")
                or row.get("id")
                or 0
            )
            for row in dashboard.get("support_cards") or []
        }
        # friend_card_id is a rental, never in owned supports; it is
        # validated separately against friend_supports below.
        selected_supports = {
            int(value) for value in setup["support_card_ids"]
        }
        if available_supports and not selected_supports.issubset(
            available_supports
        ):
            raise ValueError("selected support card is not available")

        friend_supports = list(dashboard.get("friend_supports") or [])
        if friend_supports:
            requested_friend = (
                int(setup["friend_viewer_id"]),
                int(setup["friend_card_id"]),
            )
            available_friends = {
                (
                    int(row.get("viewer_id") or 0),
                    int(
                        row.get("support_card_id")
                        or row.get("card_id")
                        or row.get("id")
                        or 0
                    ),
                )
                for row in friend_supports
            }
            if (
                requested_friend not in available_friends
                and not allow_missing_friend
            ):
                raise ValueError(
                    "selected friend support is not available in dashboard session"
                )
