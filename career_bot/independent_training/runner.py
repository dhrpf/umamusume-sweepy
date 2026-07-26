from __future__ import annotations

import threading
import time
from typing import Any, Callable

from .finalizer import NeedsAttention
from .models import RunState, TpMode


_CHARA_FIELDS = (
    "turn",
    "skill_point",
    "speed",
    "stamina",
    "power",
    "guts",
    "wiz",
    "skill_array",
    "skill_tips_array",
)


def _progress(response: dict[str, Any]) -> dict[str, Any]:
    data = (response or {}).get("data") or {}
    for key in (
        "progress_info",
        "idle_single_mode_progress_info",
        "idle_single_mode_start_info",
    ):
        value = data.get(key)
        if isinstance(value, dict) and value:
            return value
    for value in data.values():
        if (
            isinstance(value, dict)
            and "start_time" in value
            and "end_time" in value
        ):
            return value
    return {}


def _nested_progress_value(progress: dict[str, Any], key: str) -> Any:
    if key in progress:
        return progress.get(key)
    for child_key in ("start_chara", "start_info", "chara_info"):
        child = progress.get(child_key)
        if isinstance(child, dict) and key in child:
            return child.get(key)
    return None


def _support_ids(progress: dict[str, Any]) -> list[int]:
    raw = _nested_progress_value(progress, "support_card_ids")
    if raw is None:
        raw = _nested_progress_value(progress, "support_card_array")
    rows = []
    for item in raw or []:
        if isinstance(item, dict):
            value = (
                item.get("support_card_id")
                or item.get("card_id")
                or item.get("id")
            )
        else:
            value = item
        if value is not None:
            rows.append(int(value))
    return rows


def _minimal_chara(response: dict[str, Any]) -> dict[str, Any]:
    data = (response or {}).get("data") or {}
    end_info = data.get("end_info") or {}
    chara = (
        end_info.get("chara_info")
        or data.get("chara_info")
        or data.get("single_mode_chara_light")
        or {}
    )
    return {key: chara[key] for key in _CHARA_FIELDS if key in chara}


class IndependentTrainingRunner:
    def __init__(
        self,
        store,
        *,
        client_provider,
        finalizer_provider,
        account_state_provider,
        refresh_account,
        recover_tp,
        clock: Callable[[], float] = time.time,
        wake_wait=None,
    ) -> None:
        self.store = store
        self.client_provider = client_provider
        self.finalizer_provider = finalizer_provider
        self.account_state_provider = account_state_provider
        self.refresh_account = refresh_account
        self.recover_tp = recover_tp
        self.clock = clock
        self.wake_wait = wake_wait
        self._wake_event = threading.Event()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._account: str | None = None
        self._snapshot = {
            "state": "IDLE",
            "account": None,
            "run_id": None,
            "error": "",
        }
        self._snapshot_lock = threading.Lock()

    def snapshot(self) -> dict[str, Any]:
        with self._snapshot_lock:
            return dict(self._snapshot)

    def _set_snapshot(
        self,
        state: str,
        *,
        account: str,
        run_id: str | None = None,
        error: str = "",
    ) -> None:
        with self._snapshot_lock:
            self._snapshot = {
                "state": state,
                "account": account,
                "run_id": run_id,
                "error": str(error or ""),
            }

    def start(self, account: str) -> dict[str, Any]:
        self._account = str(account)
        self._stop_event.clear()
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(
                target=self._loop,
                name="independent-training-runner",
                daemon=True,
            )
            self._thread.start()
        self.wake()
        return self.snapshot()

    def wake(self) -> None:
        self._wake_event.set()

    def stop(self) -> None:
        self._stop_event.set()
        self.wake()
        thread = self._thread
        if (
            thread is not None
            and thread.is_alive()
            and thread is not threading.current_thread()
        ):
            thread.join(timeout=2.0)

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            account = self._account
            if account:
                self.run_once(account)
            timeout = 5.0
            if self.snapshot()["state"] in {
                "IDLE",
                "WAITING_FOR_TP",
                "STOPPED",
            }:
                timeout = 30.0
            self._wait(timeout)

    def _wait(self, timeout: float) -> None:
        if self.wake_wait is not None:
            self.wake_wait(timeout)
            return
        self._wake_event.wait(timeout)
        self._wake_event.clear()

    def run_once(self, account: str) -> dict[str, Any]:
        account = str(account)
        active = self.store.active_run(account)
        control = self.store.get_control(account)
        if active is None and control.get("stop_after_current"):
            self._set_snapshot("STOPPED", account=account)
            return self.snapshot()

        run = active or self.store.claim_next(account)
        if run is None:
            self._set_snapshot("IDLE", account=account)
            return self.snapshot()

        state = RunState(run["state"])
        if state == RunState.NEEDS_ATTENTION:
            self._set_snapshot(
                "NEEDS_ATTENTION",
                account=account,
                run_id=run["run_id"],
                error=run.get("error") or "",
            )
            return self.snapshot()
        if state in {RunState.FAILED, RunState.CANCELLED}:
            self._set_snapshot(
                state.value,
                account=account,
                run_id=run["run_id"],
                error=run.get("error") or "",
            )
            return self.snapshot()

        client = self.client_provider(account)
        try:
            if state == RunState.FINALIZING:
                return self._finalize(account, run)
            if state == RunState.COLLECTING:
                if run.get("collection_attempted"):
                    return self._needs_attention(
                        account,
                        run,
                        "collection result is ambiguous; end will not be retried",
                    )
                return self._collect(account, run, client)

            status = client.independent_training_status()
            server_progress = _progress(status)
            if state == RunState.STARTING:
                run = self._start_or_reconcile(
                    account,
                    run,
                    client,
                    server_progress,
                )
                if RunState(run["state"]) != RunState.RUNNING:
                    return self.snapshot()
                state = RunState.RUNNING
                server_progress = {
                    "start_time": run.get("server_start_time"),
                    "end_time": run.get("server_end_time"),
                    **{
                        key: value
                        for key, value in (server_progress or {}).items()
                        if key not in {"start_time", "end_time"}
                    },
                }

            if state == RunState.RUNNING:
                return self._advance_running(
                    account,
                    run,
                    client,
                    server_progress,
                )
        except NeedsAttention as exc:
            latest = self.store.get(run["run_id"])
            return self._needs_attention(account, latest, str(exc))
        return self.snapshot()

    def _start_or_reconcile(
        self,
        account: str,
        run: dict[str, Any],
        client,
        server_progress: dict[str, Any],
    ) -> dict[str, Any]:
        if server_progress:
            if not run.get("start_attempted"):
                self._needs_attention(
                    account,
                    run,
                    "server already has an independent run",
                )
                return self.store.get(run["run_id"])
            if not self._matches(run, server_progress):
                self._needs_attention(
                    account,
                    run,
                    "server run does not match queued setup",
                )
                return self.store.get(run["run_id"])
            resumed = self.store.transition(
                run["run_id"],
                RunState.RUNNING,
                expected_version=run["version"],
                server_start_time=float(
                    _nested_progress_value(server_progress, "start_time") or 0
                ),
                server_end_time=float(
                    _nested_progress_value(server_progress, "end_time") or 0
                ),
            )
            self._set_snapshot(
                "RUNNING",
                account=account,
                run_id=run["run_id"],
            )
            return resumed

        if run.get("start_attempted"):
            self._needs_attention(
                account,
                run,
                "start result is ambiguous and server reports no matching run",
            )
            return self.store.get(run["run_id"])

        if not self._prepare_tp(account, run):
            return run

        setup = run.get("setup") or {}
        client.pre_start_independent_training(int(setup["scenario_id"]))
        marked = self.store.mark_start_attempted(
            run["run_id"],
            run["version"],
        )
        account_state = self.account_state_provider(account) or {}
        try:
            response = client.start_independent_training(
                setup=setup,
                tp_info=dict(account_state.get("tp_info") or {}),
                current_money=int(account_state.get("current_money") or 0),
                succession_rank_point=int(
                    account_state.get("succession_rank_point") or 0
                ),
            )
        except Exception as exc:
            self._needs_attention(
                account,
                marked,
                f"start result is ambiguous: {exc}",
            )
            return self.store.get(run["run_id"])

        accepted = _progress(response)
        if not accepted or not self._matches(marked, accepted):
            self._needs_attention(
                account,
                marked,
                "start response could not be matched to queued setup",
            )
            return self.store.get(run["run_id"])
        running = self.store.transition(
            run["run_id"],
            RunState.RUNNING,
            expected_version=marked["version"],
            server_start_time=float(
                _nested_progress_value(accepted, "start_time") or 0
            ),
            server_end_time=float(
                _nested_progress_value(accepted, "end_time") or 0
            ),
        )
        self._set_snapshot(
            "RUNNING",
            account=account,
            run_id=run["run_id"],
        )
        return running

    def _prepare_tp(self, account: str, run: dict[str, Any]) -> bool:
        setup = run.get("setup") or {}
        required = int(setup.get("use_tp") or 30)
        account_state = self.account_state_provider(account) or {}
        current = int(
            ((account_state.get("tp_info") or {}).get("current_tp") or 0)
        )
        if current >= required:
            return True

        mode = TpMode(run.get("tp_mode") or TpMode.WAIT.value)
        if mode == TpMode.WAIT:
            self._set_snapshot(
                "WAITING_FOR_TP",
                account=account,
                run_id=run["run_id"],
            )
            return False
        if mode == TpMode.STOP:
            self._set_snapshot(
                "STOPPED",
                account=account,
                run_id=run["run_id"],
            )
            return False

        recovered = bool(self.recover_tp(account))
        account_state = self.account_state_provider(account) or {}
        current = int(
            ((account_state.get("tp_info") or {}).get("current_tp") or 0)
        )
        if not recovered or current < required:
            raise NeedsAttention("TP recovery failed")
        return True

    def _advance_running(
        self,
        account: str,
        run: dict[str, Any],
        client,
        server_progress: dict[str, Any],
    ) -> dict[str, Any]:
        end_time = float(run.get("server_end_time") or 0)
        if end_time > float(self.clock()):
            self._set_snapshot(
                "RUNNING",
                account=account,
                run_id=run["run_id"],
            )
            return self.snapshot()

        status = client.independent_training_status()
        confirmed = _progress(status)
        if not confirmed or not self._matches(run, confirmed):
            return self._needs_attention(
                account,
                run,
                "completed server run could not be reconciled",
            )
        confirmed_end = float(
            _nested_progress_value(confirmed, "end_time") or 0
        )
        if confirmed_end > float(self.clock()):
            self._set_snapshot(
                "RUNNING",
                account=account,
                run_id=run["run_id"],
            )
            return self.snapshot()

        collecting = self.store.transition(
            run["run_id"],
            RunState.COLLECTING,
            expected_version=run["version"],
            server_start_time=float(
                _nested_progress_value(confirmed, "start_time") or 0
            ),
            server_end_time=confirmed_end,
        )
        return self._collect(account, collecting, client)

    def _collect(
        self,
        account: str,
        run: dict[str, Any],
        client,
    ) -> dict[str, Any]:
        if run.get("collection_attempted"):
            return self._needs_attention(
                account,
                run,
                "collection result is ambiguous; end will not be retried",
            )
        marked = self.store.mark_collection_attempted(
            run["run_id"],
            run["version"],
        )
        try:
            response = client.end_independent_training()
        except Exception as exc:
            return self._needs_attention(
                account,
                marked,
                f"collection result is ambiguous: {exc}",
            )
        chara = _minimal_chara(response)
        if not chara:
            return self._needs_attention(
                account,
                marked,
                "collection response did not include chara_info",
            )
        data = (response or {}).get("data") or {}
        finalizing = self.store.transition(
            run["run_id"],
            RunState.FINALIZING,
            expected_version=marked["version"],
            finalization={
                "chara_info": chara,
                "tp_info": dict(data.get("tp_info") or {}),
            },
        )
        return self._finalize(account, finalizing)

    def _finalize(
        self,
        account: str,
        run: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            result = self.finalizer_provider(account).run(run)
        except NeedsAttention as exc:
            latest = self.store.get(run["run_id"])
            return self._needs_attention(account, latest, str(exc))
        except Exception as exc:
            latest = self.store.get(run["run_id"])
            return self._needs_attention(
                account,
                latest,
                f"finalization failed: {exc}",
            )

        self.refresh_account(account)
        latest = self.store.get(run["run_id"])
        completed = self.store.transition(
            run["run_id"],
            RunState.COMPLETED,
            expected_version=latest["version"],
            result=result,
        )
        control = self.store.get_control(account)
        state = (
            "STOPPED"
            if control.get("stop_after_current")
            else "IDLE"
        )
        self._set_snapshot(
            state,
            account=account,
            run_id=completed["run_id"],
        )
        return self.snapshot()

    def _matches(
        self,
        run: dict[str, Any],
        server_progress: dict[str, Any],
    ) -> bool:
        setup = run.get("setup") or {}
        fields = (
            "card_id",
            "parent_id_1",
            "parent_id_2",
            "scenario_id",
        )
        for field in fields:
            server_value = _nested_progress_value(server_progress, field)
            if server_value is not None and int(server_value) != int(
                setup.get(field) or 0
            ):
                return False

        supports = _support_ids(server_progress)
        if supports and supports != [
            int(value) for value in setup.get("support_card_ids") or []
        ]:
            return False

        saved_start = run.get("server_start_time")
        server_start = _nested_progress_value(server_progress, "start_time")
        if (
            saved_start is not None
            and server_start is not None
            and float(saved_start) != float(server_start)
        ):
            return False
        return True

    def _needs_attention(
        self,
        account: str,
        run: dict[str, Any],
        message: str,
    ) -> dict[str, Any]:
        current = self.store.get(run["run_id"])
        if RunState(current["state"]) != RunState.NEEDS_ATTENTION:
            current = self.store.transition(
                current["run_id"],
                RunState.NEEDS_ATTENTION,
                expected_version=current["version"],
                error=message,
                next_action="reconcile",
            )
        self._set_snapshot(
            "NEEDS_ATTENTION",
            account=account,
            run_id=current["run_id"],
            error=message,
        )
        return self.snapshot()
