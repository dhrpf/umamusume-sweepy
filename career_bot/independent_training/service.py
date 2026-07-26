from __future__ import annotations

from typing import Any

from sweepy_jobs import LeaseConflict

from .models import IndependentSetup


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
                "saved_race_agendas": (
                    dashboard.get("saved_race_agendas") or []
                ),
                "reserved_race_info": (
                    pre_start.get("reserved_race_info") or []
                ),
                "last_idle_single_mode_start_info": (
                    pre_start.get("last_idle_single_mode_start_info") or {}
                ),
                "status": status,
            }
        )

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

    def start(self) -> dict[str, Any]:
        account = self._account()
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
        return {
            "account": account,
            "runner": _public_value(self.runner.snapshot()),
            "control": self.store.get_control(account),
            "lease": _public_value(
                self.job_store.get_workflow_lease(account)
            ),
            "runs": [
                _public_run(run)
                for run in self.store.list_runs(account)
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

    def reconcile(self) -> dict[str, Any]:
        account = self._account()
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
            raise WorkflowConflict(str(exc)) from exc

    def release_lease(self) -> bool:
        account = self._account()
        return self.job_store.release_workflow_lease(
            account,
            owner=self._owner(account),
            workflow_type="independent_training",
        )

    def _validate_dashboard_setup(self, setup: dict[str, Any]) -> None:
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

        available_supports = {
            int(
                row.get("support_card_id")
                or row.get("card_id")
                or row.get("id")
                or 0
            )
            for row in dashboard.get("support_cards") or []
        }
        selected_supports = {
            *[int(value) for value in setup["support_card_ids"]],
            int(setup["friend_card_id"]),
        }
        if available_supports and not selected_supports.issubset(
            available_supports
        ):
            raise ValueError("selected support card is not available")
