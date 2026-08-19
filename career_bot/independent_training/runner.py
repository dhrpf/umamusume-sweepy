from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable

from career_bot.delay import compute_regen_wait_seconds

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
_COMPLETED_RECONCILIATION_ERROR = (
    "completed server run could not be reconciled"
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
    for child_key in (
        "start_chara",
        "start_info",
        "chara_info",
        "single_mode_chara_light",
    ):
        child = progress.get(child_key)
        if isinstance(child, dict) and key in child:
            return child.get(key)
    return None


def _server_timestamp(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        pass
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


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
        tp_cost_provider,
        race_array_provider=None,
        succession_rank_point_provider=None,
        load_progress_provider=None,
        auth_recovery=None,
        heartbeat_lease=None,
        release_lease=None,
        clock: Callable[[], float] = time.time,
        wake_wait=None,
    ) -> None:
        self.store = store
        self.client_provider = client_provider
        self.finalizer_provider = finalizer_provider
        self.account_state_provider = account_state_provider
        self.refresh_account = refresh_account
        self.recover_tp = recover_tp
        self.tp_cost_provider = tp_cost_provider
        self.race_array_provider = race_array_provider
        self.succession_rank_point_provider = succession_rank_point_provider
        self.load_progress_provider = load_progress_provider
        self.auth_recovery = auth_recovery
        self.heartbeat_lease = heartbeat_lease
        self.release_lease = release_lease
        self.clock = clock
        self.wake_wait = wake_wait
        self._wake_event = threading.Event()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._account: str | None = None
        self._tp_wait_override_sec: float | None = None
        self._snapshot = {
            "state": "IDLE",
            "account": None,
            "run_id": None,
            "error": "",
            "detected_tp_cost": None,
            "tp_cost_source": "",
            "tp_cost_error": "",
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
                **self._snapshot,
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

    def reconcile_load_index(self, account: str) -> bool:
        if self.load_progress_provider is None:
            return False
        run = self.store.active_run(account)
        if (
            run is None
            or RunState(run["state"]) != RunState.STARTING
            or not run.get("start_attempted")
        ):
            return False
        progress = self.load_progress_provider(str(account)) or {}
        if not progress or not self._matches(run, progress):
            return False
        self._start_or_reconcile(str(account), run, None, progress)
        return RunState(self.store.get(run["run_id"])["state"]) == RunState.RUNNING

    def describe_server_run(self, account: str) -> dict[str, Any] | None:
        """Summarize a server career that no local run is tracking."""
        if self.load_progress_provider is None:
            return None
        if self.store.active_run(str(account)) is not None:
            return None
        progress = self.load_progress_provider(str(account)) or {}
        card_id = _nested_progress_value(progress, "card_id")
        if not card_id:
            return None
        end_time = _server_timestamp(
            _nested_progress_value(progress, "end_time") or 0
        )
        return {
            "card_id": int(card_id),
            "scenario_id": int(
                _nested_progress_value(progress, "scenario_id") or 0
            ),
            "parent_id_1": int(
                _nested_progress_value(
                    progress, "succession_trained_chara_id_1"
                ) or 0
            ),
            "parent_id_2": int(
                _nested_progress_value(
                    progress, "succession_trained_chara_id_2"
                ) or 0
            ),
            "server_start_time": _server_timestamp(
                _nested_progress_value(progress, "start_time") or 0
            ),
            "server_end_time": end_time,
            "collectable": end_time > 0 and end_time <= float(self.clock()),
        }

    def adopt_server_run(self, account: str) -> dict[str, Any] | None:
        """Track an orphaned server career so it can be collected.

        The game refuses a new ``idle_single_mode/start`` (error 102) while an
        uncollected career occupies the slot, and reconciliation cannot adopt
        it because its trainee/parents do not match any queued run.
        """
        account = str(account)
        try:
            self.refresh_account(account)
        except Exception:
            pass
        summary = self.describe_server_run(account)
        if summary is None:
            return None
        progress = self.load_progress_provider(account) or {}
        setup = {
            "card_id": summary["card_id"],
            "scenario_id": summary["scenario_id"],
            "parent_id_1": summary["parent_id_1"],
            "parent_id_2": summary["parent_id_2"],
            "support_card_ids": _support_ids(progress),
            "running_style": int(
                _nested_progress_value(progress, "running_style") or 0
            ),
            "final_skill_ids": [],
            "factor_reroll": {"enabled": False, "targets": []},
            "adopted_from_server": True,
        }
        run = self.store.adopt_server_run(
            account,
            setup,
            server_start_time=summary["server_start_time"],
            server_end_time=summary["server_end_time"],
        )
        self.store.append_event(
            account,
            "server_run_adopted",
            {
                "run_id": run["run_id"],
                "card_id": summary["card_id"],
                "scenario_id": summary["scenario_id"],
                "server_end_time": summary["server_end_time"],
            },
            run_id=run["run_id"],
        )
        self._set_snapshot(
            "RUNNING",
            account=account,
            run_id=run["run_id"],
        )
        return run

    def retry_completed_reconciliation(self, account: str) -> bool:
        run = self.store.active_run(account)
        if (
            run is None
            or RunState(run["state"]) != RunState.NEEDS_ATTENTION
            or run.get("error") != _COMPLETED_RECONCILIATION_ERROR
            or float(run.get("server_end_time") or 0) <= 0
        ):
            return False
        resumed = self.store.transition(
            run["run_id"],
            RunState.RUNNING,
            expected_version=run["version"],
            error="",
            next_action="",
        )
        self._set_snapshot(
            "RUNNING",
            account=str(account),
            run_id=resumed["run_id"],
        )
        return True

    def retry_finalization_reconciliation(self, account: str) -> bool:
        run = self.store.active_run(account)
        if (
            run is None
            or RunState(run["state"]) != RunState.NEEDS_ATTENTION
            or not str(run.get("error") or "").startswith("finalization failed:")
        ):
            return False
        retried = self.store.transition(
            run["run_id"],
            RunState.FINALIZING,
            expected_version=run["version"],
            error="",
            next_action="",
        )
        self._set_snapshot(
            "FINALIZING",
            account=str(account),
            run_id=retried["run_id"],
        )
        return True

    def retry_start_reconciliation(self, account: str) -> bool:
        run = self.store.active_run(account)
        if (
            run is None
            or RunState(run["state"]) != RunState.NEEDS_ATTENTION
            or not run.get("start_attempted")
            or not str(run.get("error") or "").startswith((
                "start result is ambiguous",
                "unconfirmed start was abandoned",
            ))
        ):
            return False

        try:
            response = self.refresh_account(account)
        except Exception as exc:
            if not self._recover_expired_session(account, exc):
                return False
            return self._reset_start_for_retry(account, run)
        data = (response or {}).get("data")
        if not isinstance(data, dict) or data.get("single_mode_chara_light"):
            return False

        progress = data.get("idle_single_mode_load_info") or {}
        if progress:
            resumed = self._start_or_reconcile(
                str(account),
                run,
                None,
                dict(progress),
            )
            return RunState(resumed["state"]) == RunState.RUNNING

        try:
            self.client_provider(account).pre_single_mode()
        except Exception as exc:
            if not self._recover_expired_session(account, exc):
                return False

        return self._reset_start_for_retry(account, run)

    def _reset_start_for_retry(self, account: str, run: dict[str, Any]) -> bool:
        retried = self.store.transition(
            run["run_id"],
            RunState.STARTING,
            expected_version=run["version"],
            start_attempted=False,
            error="",
            next_action="",
        )
        self._set_snapshot(
            "STARTING",
            account=str(account),
            run_id=retried["run_id"],
        )
        return True

    def _recover_expired_session(self, account: str, exc: Exception) -> bool:
        if "201" not in str(exc) or self.auth_recovery is None:
            return False
        try:
            return bool(self.auth_recovery(account))
        except Exception:
            return False

    def retry_setup_reconciliation(self, account: str) -> bool:
        run = self.store.active_run(account)
        if (
            run is None
            or RunState(run["state"]) != RunState.NEEDS_ATTENTION
            or not str(run.get("error") or "").startswith((
                "independent race setup unavailable:",
                "succession affinity unavailable:",
            ))
        ):
            return False
        retried = self.store.transition(
            run["run_id"],
            RunState.STARTING,
            expected_version=run["version"],
            start_attempted=False,
            error="",
            next_action="",
        )
        self._set_snapshot(
            "STARTING",
            account=str(account),
            run_id=retried["run_id"],
        )
        return True

    def retry_collection_reconciliation(self, account: str) -> bool:
        run = self.store.active_run(account)
        if (
            run is None
            or RunState(run["state"]) != RunState.NEEDS_ATTENTION
            or not run.get("collection_attempted")
            or not str(run.get("error") or "").startswith(
                "collection result is ambiguous"
            )
        ):
            return False

        client = self.client_provider(account)
        recovered = self._reconcile_collection_result(account, run, client)
        if recovered is None:
            return False
        self._set_snapshot(
            "FINALIZING",
            account=str(account),
            run_id=recovered["run_id"],
        )
        return True

    def retry_finish_reconciliation(self, account: str) -> bool:
        run = self.store.active_run(account)
        if (
            run is None
            or RunState(run["state"]) != RunState.NEEDS_ATTENTION
            or not run.get("finish_attempted")
            or not str(run.get("error") or "").startswith(
                "finish result is ambiguous"
            )
        ):
            return False

        try:
            response = self.refresh_account(account)
        except Exception:
            return False
        data = (response or {}).get("data")
        if not isinstance(data, dict) or data.get("single_mode_chara_light"):
            return False

        chara = (run.get("finalization") or {}).get("chara_info") or {}
        result = dict(run.get("result") or {})
        result.update({
            "current_turn": int(chara.get("turn") or 0),
            "selected_lottery_id": int(run.get("selected_lottery_id") or 0),
            "reconciled": True,
        })
        completed = self.store.transition(
            run["run_id"],
            RunState.COMPLETED,
            expected_version=run["version"],
            error="",
            next_action="",
            result=result,
        )
        self._set_snapshot(
            "IDLE",
            account=str(account),
            run_id=completed["run_id"],
        )
        return True

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
                try:
                    self.run_once(account)
                except Exception as exc:
                    # An escaping API error must park the run, not kill the
                    # executor thread; a dead thread leaves the dashboard
                    # reporting the last snapshot forever.
                    self._park_executor(account, exc)
            state = self.snapshot()["state"]
            timeout = 5.0
            if state == "WAITING_FOR_TP" and self._tp_wait_override_sec is not None:
                timeout = self._tp_wait_override_sec
                self._tp_wait_override_sec = None
            elif state in {"IDLE", "WAITING_FOR_TP", "STOPPED"}:
                timeout = 30.0
            self._wait(timeout)

    def _park_executor(self, account: str, error: Exception) -> None:
        message = f"executor error: {error}"
        try:
            run = self.store.active_run(str(account))
        except Exception:
            run = None
        if run is not None:
            try:
                self._needs_attention(str(account), run, message)
                return
            except Exception:
                pass
        self._set_snapshot(
            "NEEDS_ATTENTION",
            account=str(account),
            error=message,
        )

    def _wait(self, timeout: float) -> None:
        if self.wake_wait is not None:
            self.wake_wait(timeout)
            return
        self._wake_event.wait(timeout)
        self._wake_event.clear()

    def _release_lease(self, account: str) -> None:
        if self.release_lease is None:
            return
        try:
            self.release_lease(account)
        except Exception:
            return

    def run_once(self, account: str) -> dict[str, Any]:
        account = str(account)
        if self.heartbeat_lease is not None:
            try:
                self.heartbeat_lease(account)
            except Exception as exc:
                self._set_snapshot(
                    "NEEDS_ATTENTION",
                    account=account,
                    error=f"workflow lease heartbeat failed: {exc}",
                )
                return self.snapshot()

        active = self.store.active_run(account)
        control = self.store.get_control(account)
        if active is None and control.get("stop_after_current"):
            self._set_snapshot("STOPPED", account=account)
            self._release_lease(account)
            return self.snapshot()

        run = active or self.store.claim_next(account)
        if run is None:
            self._set_snapshot("IDLE", account=account)
            self._release_lease(account)
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
        scenario_id = int((run.get("setup") or {}).get("scenario_id") or 0)
        if scenario_id:
            client.current_scenario_id = scenario_id
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

            server_progress = {}
            if state == RunState.STARTING:
                if run.get("start_attempted"):
                    if self.load_progress_provider is not None:
                        server_progress = (
                            self.load_progress_provider(account) or {}
                        )
                    if server_progress:
                        run = self._start_or_reconcile(
                            account,
                            run,
                            client,
                            server_progress,
                        )
                        if RunState(run["state"]) == RunState.RUNNING:
                            state = RunState.RUNNING
                        else:
                            return self.snapshot()
                    else:
                        return self._needs_attention(
                            account,
                            run,
                            "unconfirmed start will not probe idle status",
                        )
                else:
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
                server_start_time=_server_timestamp(
                    _nested_progress_value(server_progress, "start_time") or 0
                ),
                server_end_time=_server_timestamp(
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

        setup = dict(run.get("setup") or {})
        if self.race_array_provider is not None:
            try:
                original_races = list(setup.get("race_array") or [])
                normalized_races = list(
                    self.race_array_provider(setup) or []
                )
                setup["race_array"] = normalized_races
                if normalized_races != original_races:
                    print(
                        "[independent] normalized start race_array "
                        f"({len(original_races)} -> {len(normalized_races)})",
                        flush=True,
                    )
            except Exception as exc:
                raise NeedsAttention(
                    f"independent race setup unavailable: {exc}"
                ) from exc
        required_tp = self._resolve_tp_cost(account)
        if not self._prepare_tp(account, run, required_tp):
            return run
        setup["use_tp"] = required_tp
        account_state = self.account_state_provider(account) or {}
        succession_rank_point = int(
            account_state.get("succession_rank_point") or 0
        )
        if self.succession_rank_point_provider is not None:
            try:
                succession_rank_point = int(
                    self.succession_rank_point_provider(account, setup)
                )
            except Exception as exc:
                raise NeedsAttention(
                    f"succession affinity unavailable: {exc}"
                ) from exc
        client.pre_start_independent_training(int(setup["scenario_id"]))
        marked = self.store.mark_start_attempted(
            run["run_id"],
            run["version"],
        )
        try:
            response = client.start_independent_training(
                setup=setup,
                tp_info=dict(account_state.get("tp_info") or {}),
                current_money=int(account_state.get("current_money") or 0),
                succession_rank_point=succession_rank_point,
                prepared=True,
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
            server_start_time=_server_timestamp(
                _nested_progress_value(accepted, "start_time") or 0
            ),
            server_end_time=_server_timestamp(
                _nested_progress_value(accepted, "end_time") or 0
            ),
        )
        self._set_snapshot(
            "RUNNING",
            account=account,
            run_id=run["run_id"],
        )
        return running

    def _resolve_tp_cost(self, account: str) -> int:
        try:
            resolution = self.tp_cost_provider(account)
            required = int(resolution.cost)
            if required <= 0:
                raise ValueError("resolved cost must be positive")
        except Exception as exc:
            with self._snapshot_lock:
                self._snapshot["detected_tp_cost"] = None
                self._snapshot["tp_cost_source"] = ""
                self._snapshot["tp_cost_error"] = str(exc)
            raise NeedsAttention(f"TP cost resolution failed: {exc}") from exc

        with self._snapshot_lock:
            self._snapshot["detected_tp_cost"] = required
            self._snapshot["tp_cost_source"] = str(resolution.source or "")
            self._snapshot["tp_cost_error"] = ""
        return required

    def _prepare_tp(
        self,
        account: str,
        run: dict[str, Any],
        required: int,
    ) -> bool:
        account_state = self.account_state_provider(account) or {}
        current = int(
            ((account_state.get("tp_info") or {}).get("current_tp") or 0)
        )
        if current >= required:
            return True

        mode = TpMode(run.get("tp_mode") or TpMode.WAIT.value)
        if mode == TpMode.WAIT:
            # The cached account state only updates as a side effect of some
            # other API call — it never self-refreshes. Force a live check so
            # a stale cache doesn't make us wait on TP the server already has.
            try:
                self.refresh_account(account)
            except Exception:
                pass
            account_state = self.account_state_provider(account) or {}
            current = int(
                ((account_state.get("tp_info") or {}).get("current_tp") or 0)
            )
            if current >= required:
                return True

            self._tp_wait_override_sec = compute_regen_wait_seconds(required, current)
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

    def _load_index_confirmation(
        self,
        account: str,
        run: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Reuse the ``load/index`` career window instead of probing status.

        ``idle_single_mode/status`` is not always answerable for a career that
        already ran out its clock (the server bounces it with 217), while
        ``load/index`` still reports the same window.  Only accept it when it
        describes this exact run and its end time has passed.
        """
        if self.load_progress_provider is None:
            return None
        try:
            progress = self.load_progress_provider(str(account)) or {}
        except Exception:
            return None
        if not progress or not self._matches(run, progress):
            return None
        end_time = _server_timestamp(
            _nested_progress_value(progress, "end_time") or 0
        )
        if end_time <= 0 or end_time > float(self.clock()):
            return None
        return progress

    def _advance_running(
        self,
        account: str,
        run: dict[str, Any],
        client,
        server_progress: dict[str, Any],
    ) -> dict[str, Any]:
        end_time = float(run.get("server_end_time") or 0)
        if end_time <= 0:
            return self._needs_attention(
                account,
                run,
                "running record has no confirmed server window; will not probe idle status",
            )
        if end_time > float(self.clock()):
            self._set_snapshot(
                "RUNNING",
                account=account,
                run_id=run["run_id"],
            )
            return self.snapshot()

        confirmed = self._load_index_confirmation(account, run)
        if confirmed is None:
            try:
                status = client.independent_training_status()
            except Exception as exc:
                return self._needs_attention(
                    account,
                    run,
                    f"idle status probe failed: {exc}",
                )
            confirmed = _progress(status)
            if not confirmed or not self._matches(run, confirmed):
                return self._needs_attention(
                    account,
                    run,
                    _COMPLETED_RECONCILIATION_ERROR,
                )
        confirmed_end = _server_timestamp(
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
            server_start_time=_server_timestamp(
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
            if "1503" in str(exc):
                recovered = self._reconcile_collection_result(
                    account,
                    marked,
                    client,
                )
                if recovered is not None:
                    return self._finalize(account, recovered)
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
        try:
            client.check_independent_training_progress_log()
        except Exception as exc:
            return self._needs_attention(
                account,
                marked,
                f"progress-log acknowledgement failed: {exc}",
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

    def _reconcile_collection_result(
        self,
        account: str,
        run: dict[str, Any],
        client,
    ) -> dict[str, Any] | None:
        try:
            response = client.independent_training_result()
        except Exception:
            return None
        chara = _minimal_chara(response)
        if not chara:
            return None

        try:
            self.refresh_account(account)
        except Exception:
            pass
        account_state = self.account_state_provider(account) or {}
        latest = self.store.get(run["run_id"])
        if RunState(latest["state"]) not in {
            RunState.COLLECTING,
            RunState.NEEDS_ATTENTION,
        }:
            return None
        finalization = dict(latest.get("finalization") or {})
        finalization.update({
            "chara_info": chara,
            "tp_info": dict(account_state.get("tp_info") or {}),
        })
        return self.store.transition(
            latest["run_id"],
            RunState.FINALIZING,
            expected_version=latest["version"],
            error="",
            next_action="",
            finalization=finalization,
        )

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
        expected_supports = [
            int(value) for value in setup.get("support_card_ids") or []
        ]
        if supports and supports != expected_supports:
            runtime_deck = list(supports)
            try:
                runtime_deck.remove(int(setup.get("friend_card_id") or 0))
            except ValueError:
                return False
            if runtime_deck != expected_supports:
                return False

        saved_start = run.get("server_start_time")
        server_start = _nested_progress_value(server_progress, "start_time")
        if (
            saved_start is not None
            and server_start is not None
            and float(saved_start) != _server_timestamp(server_start)
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
