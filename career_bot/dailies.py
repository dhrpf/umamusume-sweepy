from __future__ import annotations

import base64
import copy
import gzip
import re
import sqlite3
import struct
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from career_bot import master_data


TEAM_TRIAL_CAP = 8
DAILY_RACE_CAP = 3
GOLD_ITEM_ID = 59

_STYLE_APT_KEYS = {
    1: "proper_running_style_nige",
    2: "proper_running_style_senko",
    3: "proper_running_style_sashi",
    4: "proper_running_style_oikomi",
}
_CURRENCY_NAMES = {GOLD_ITEM_ID: "gold"}


def best_running_style(vet: dict[str, Any]) -> int:
    """Return the first running style with the highest aptitude."""
    return max(_STYLE_APT_KEYS, key=lambda style: int(vet.get(_STYLE_APT_KEYS[style]) or 0))


def parse_race_result_array(
    scenario_b64: str,
    horses: list[dict[str, Any]],
) -> list[dict[str, int]]:
    """Reconstruct the replay-check result array from a race scenario blob."""
    blob = gzip.decompress(base64.b64decode(scenario_b64))
    offset = 0

    if len(blob) < 4:
        raise ValueError("Race scenario is missing its header length")
    header_len = struct.unpack_from("<i", blob, offset)[0]
    offset += 4 + header_len

    if header_len < 0 or len(blob) < offset + 16:
        raise ValueError("Race scenario header is truncated")
    _distance_diff_max, horse_num, _horse_frame_size, horse_result_size = struct.unpack_from(
        "<fiii", blob, offset
    )
    offset += 16

    if horse_num < 0 or horse_result_size < 31 or len(blob) < offset + 4:
        raise ValueError("Race scenario horse metadata is invalid")
    pad = struct.unpack_from("<i", blob, offset)[0]
    offset += 4 + pad

    if pad < 0 or len(blob) < offset + 8:
        raise ValueError("Race scenario frame metadata is truncated")
    frame_count, frame_size = struct.unpack_from("<ii", blob, offset)
    if frame_count < 0 or frame_size < 0:
        raise ValueError("Race scenario frame metadata is invalid")
    offset += 8 + frame_count * frame_size

    if len(blob) < offset + 4:
        raise ValueError("Race scenario result padding is truncated")
    pad = struct.unpack_from("<i", blob, offset)[0]
    offset += 4 + pad
    if pad < 0:
        raise ValueError("Race scenario result padding is invalid")

    if len(blob) < offset + horse_num * horse_result_size:
        raise ValueError("Race scenario result rows are truncated")

    viewer_by_index = {
        int(horse.get("frame_order") or 0) - 1: int(horse.get("viewer_id") or 0)
        for horse in horses
        if int(horse.get("frame_order") or 0) > 0
    }
    rows: list[dict[str, int]] = []
    for index in range(horse_num):
        base = offset + index * horse_result_size
        finish_order = struct.unpack_from("<i", blob, base)[0] + 1
        finish_time = round(struct.unpack_from("<f", blob, base + 4)[0] * 10000)
        finish_time_raw = round(struct.unpack_from("<f", blob, base + 27)[0] * 10000)
        rows.append(
            {
                "viewer_id": viewer_by_index.get(index, 0),
                "finish_order": finish_order,
                "finish_time": finish_time,
                "finish_time_raw": finish_time_raw,
                "bashin_diff_from_behind": 0,
            }
        )

    by_order = sorted(rows, key=lambda row: row["finish_order"])
    for index, row in enumerate(by_order[:-1]):
        nxt = by_order[index + 1]
        raw_gap = max(0, nxt["finish_time_raw"] - row["finish_time_raw"])
        row["bashin_diff_from_behind"] = round(raw_gap * 7.08)
    return rows


def _fmt_get_list_time(servertime: int | float) -> str:
    dt = datetime.fromtimestamp(float(servertime or 0), tz=timezone.utc)
    return f"{dt.year:04d}/{dt.month:02d}/{dt.day:02d} {dt.hour}:{dt.minute:02d}:{dt.second:02d}"


def _error_code(exc: BaseException) -> int | None:
    text = str(exc)
    patterns = (
        r'"result_code"\s*:\s*(\d+)',
        r'"response_code"\s*:\s*(\d+)',
        r"\b(?:error|result|response)[ _-]?code\D{0,8}(\d+)\b",
        r"\b(102|1053)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def _find_value(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        if key in value:
            return value[key]
        for child in value.values():
            found = _find_value(child, key)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_value(child, key)
            if found is not None:
                return found
    return None


def _data(response: Any) -> dict[str, Any]:
    if not isinstance(response, dict):
        return {}
    data = response.get("data")
    return data if isinstance(data, dict) else response


class DailiesRunner:
    """Run account-level daily content in a background thread."""

    def __init__(self, base_dir: str | Path | None = None):
        self.base_dir = Path(base_dir or Path(__file__).resolve().parents[1])
        self.lock = threading.Lock()
        self.thread: threading.Thread | None = None
        self.stop_requested = False
        self.status = self._idle_status()

    @staticmethod
    def _idle_status() -> dict[str, Any]:
        return {
            "running": False,
            "task": "",
            "tasks": [],
            "log": [],
            "results": {},
            "finished": False,
            "error": "",
        }

    @property
    def running(self) -> bool:
        with self.lock:
            return bool(self.status.get("running"))

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return copy.deepcopy(self.status)

    def _set(self, **values: Any) -> None:
        with self.lock:
            self.status.update(values)

    def _log(self, message: str, level: str = "info") -> None:
        with self.lock:
            log = self.status.setdefault("log", [])
            log.append({"ts": time.time(), "level": level, "msg": str(message)})
            if len(log) > 300:
                del log[:-300]

    def start(
        self,
        client: Any,
        tasks: dict[str, bool],
        trained_chara_id: int = 0,
        opponent_strength: int = 1,
        legend_race_id: int = 0,
    ) -> bool:
        with self.lock:
            if self.status.get("running"):
                return False
            selected = [name for name, enabled in tasks.items() if enabled]
            self.stop_requested = False
            self.status = self._idle_status()
            self.status.update(running=True, tasks=selected)

        self.thread = threading.Thread(
            target=self._run,
            args=(
                client,
                dict(tasks),
                int(trained_chara_id or 0),
                max(1, min(3, int(opponent_strength or 1))),
                int(legend_race_id or 0),
            ),
            daemon=True,
            name="sweepy-dailies",
        )
        self.thread.start()
        return True

    def stop(self) -> None:
        self.stop_requested = True
        if self.running:
            self._log("Stop requested.", "warning")

    def _run(
        self,
        client: Any,
        tasks: dict[str, bool],
        trained_chara_id: int,
        opponent_strength: int,
        legend_race_id: int,
    ) -> None:
        results: dict[str, Any] = {}
        errors: list[str] = []

        def run_mode(key: str, label: str, fn: Any) -> None:
            if not tasks.get(key) or self.stop_requested:
                return
            try:
                results[key] = fn()
            except Exception as exc:  # API failures are reported per mode.
                code = _error_code(exc)
                if code == 102:
                    detail = f"{label}: unavailable right now (already cleared or closed) — skipped."
                    self._log(detail, "warning")
                    results[key] = {"skipped": True, "detail": "unavailable (102)"}
                    return
                detail = f"{label} error ({code or 'unknown'}): {exc}"
                self._log(detail, "error")
                errors.append(detail)
                results[key] = {"error": str(exc), "error_code": code}

        try:
            run_mode(
                "team_trials",
                "Team Trials",
                lambda: self._team_trials(client, opponent_strength),
            )
            run_mode(
                "daily_races",
                "Daily Races",
                lambda: self._daily_races(client, trained_chara_id),
            )
            run_mode(
                "legend_races",
                "Legend Race",
                lambda: self._legend_races(client, trained_chara_id, legend_race_id),
            )
            run_mode("daily_shop", "Daily Shop", lambda: self._daily_shop(client))

            if self.stop_requested:
                self._log("Stopped by user.", "warning")
            elif errors:
                self._log(f"Dailies finished with issues: {len(errors)}.", "warning")
            else:
                self._log("All selected dailies complete.")
        finally:
            self._set(
                running=False,
                finished=True,
                results=results,
                error="; ".join(errors),
                task="",
            )

    def _load_vet(self, client: Any, trained_chara_id: int) -> dict[str, Any] | None:
        response = client.trained_chara_load()
        rows = _find_value(response, "trained_chara_array") or _find_value(
            response, "user_trained_chara_array"
        )
        for row in rows or []:
            if int(row.get("trained_chara_id") or 0) == int(trained_chara_id or 0):
                return row
        return None

    def _team_trials(self, client: Any, strength: int) -> dict[str, int]:
        self._set(task="Team Trials")
        races = 0
        strength = max(1, min(3, int(strength or 1)))
        index = client.team_stadium_index()
        current_rp = _find_value(index, "current_rp")
        if current_rp is not None and int(current_rp or 0) <= 0:
            self._log("Team Trials: no more RP — done.")
            return {"races": 0}

        for _attempt in range(TEAM_TRIAL_CAP):
            if self.stop_requested:
                break
            response = client.team_stadium_opponent_list()
            opponents = _find_value(response, "opponent_info_array") or []
            if not opponents:
                self._log("Team Trials: no more RP — done.")
                break
            opponent = next(
                (
                    row
                    for row in opponents
                    if int(row.get("strength") or 0) == strength
                ),
                opponents[0],
            )
            client.team_stadium_decide_frame_order(opponent)
            start = client.team_stadium_start(item_id_array=[])
            client.team_stadium_replay_check(round=5)
            end = client.team_stadium_all_race_end()
            races += 1

            rp = _find_value(end, "current_rp")
            if rp is None:
                rp = _find_value(start, "current_rp")
            win_type = _find_value(end, "final_win_type")
            ranking = _find_value(end, "ranking_rank")
            detail = f"Team Trial {races}: result {win_type}, ranking #{ranking}"
            if rp is not None:
                detail += f", {rp} RP left"
            self._log(detail + ".")

            if rp is not None and int(rp or 0) <= 0:
                self._log(f"Team Trials: no more RP (server said {rp}). Ran {races}.")
                break

        self._log(f"Team Trials: ran {races} race(s).")
        return {"races": races}

    def _run_one_daily(
        self,
        client: Any,
        race_id: int,
        trained_chara_id: int,
        style: int,
    ) -> int:
        entry = client.daily_race_race_entry(race_id, trained_chara_id)
        horses = _find_value(entry, "race_horse_data_array") or []
        client.daily_race_reflect_item_effect(item_id_array=[])
        start = client.daily_race_race_start(style, is_short=0)
        scenario = _find_value(start, "race_scenario")
        if not scenario:
            raise RuntimeError("daily_race/race_start returned no race_scenario")
        race_results = parse_race_result_array(scenario, horses)
        checked = client.daily_race_replay_check(race_results)
        rank = _find_value(checked, "rank")
        if rank is None:
            player_ids = {
                int(row.get("viewer_id") or 0)
                for row in horses
                if row.get("viewer_id") is not None
            }
            player = next(
                (
                    row
                    for row in race_results
                    if int(row.get("viewer_id") or 0) in player_ids
                ),
                race_results[0] if race_results else {},
            )
            rank = player.get("finish_order", 0)
        return int(rank or 0)

    def _daily_races(self, client: Any, trained_chara_id: int) -> dict[str, Any]:
        self._set(task="Daily Races")
        vet = self._load_vet(client, trained_chara_id)
        if not vet:
            self._log("Daily Races: no veteran selected — skipping.", "warning")
            return {"completed": [], "detail": "no veteran"}
        style = best_running_style(vet)
        response = client.daily_race_index()
        records = _find_value(response, "daily_race_record_array") or []
        race_ids = [
            int(row.get("daily_race_id") or row.get("id") or 0)
            for row in records
            if int(row.get("daily_race_id") or row.get("id") or 0)
        ]
        self._log(
            f"Daily Races: {len(race_ids)} race slots (style {style}, cap {DAILY_RACE_CAP})."
        )
        completed: list[dict[str, int]] = []

        while len(completed) < DAILY_RACE_CAP and not self.stop_requested:
            played = False
            for race_id in race_ids:
                try:
                    rank = self._run_one_daily(client, race_id, trained_chara_id, style)
                except Exception as exc:
                    if _error_code(exc) == 102:
                        continue
                    self._log(f"Daily Races stopped: {exc}", "warning")
                    return {"completed": completed, "detail": str(exc)}
                completed.append({"id": race_id, "rank": rank})
                self._log(
                    f"Daily race {race_id}: finished (rank {rank}) "
                    f"[{len(completed)}/{DAILY_RACE_CAP}]."
                )
                played = True
                break
            if not played:
                self._log("Daily Races: no more attempts available.")
                break

        self._log(f"Daily Races: ran {len(completed)}.")
        return {"completed": completed}

    def _legend_races(
        self,
        client: Any,
        trained_chara_id: int,
        legend_race_id: int,
    ) -> dict[str, Any]:
        self._set(task="Legend Races")
        vet = self._load_vet(client, trained_chara_id)
        if not vet:
            self._log("Legend Race: no veteran selected — skipping.", "warning")
            return {"completed": [], "detail": "no veteran"}
        if not legend_race_id:
            self._log("Legend Race: none selected — skipping.", "warning")
            return {"completed": [], "detail": "no selection"}
        style = best_running_style(vet)
        try:
            client.daily_legend_race_race_entry(legend_race_id, trained_chara_id)
            client.daily_legend_race_reflect_item_effect(item_id_array=[])
            client.daily_legend_race_race_start(style, is_short=0)
            checked = client.daily_legend_race_replay_check()
            rank = int(_find_value(checked, "rank") or 0)
        except Exception as exc:
            if _error_code(exc) == 1053:
                self._log("Legend Race: already done today (one per day).", "warning")
                return {"completed": [], "detail": "already done today"}
            raise
        self._log(f"Legend race {legend_race_id}: cleared (rank {rank}).")
        return {"completed": [{"id": legend_race_id, "rank": rank}]}

    def _load_shop_catalog(
        self,
    ) -> tuple[dict[int, int] | None, dict[int, dict[str, int]] | None]:
        db_path = master_data.configured_master_mdb_path(self.base_dir)
        if not db_path.exists():
            return None, None
        try:
            connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            try:
                cursor = connection.cursor()
                reward_to_exchange = {
                    int(reward_id): int(exchange_id)
                    for reward_id, exchange_id in cursor.execute(
                        "select id, item_exchange_id from limited_exchange_reward"
                    )
                }
                catalog = {
                    int(exchange_id): {
                        "pay_item": int(pay_item_id or 0),
                        "pay_num": int(pay_item_num or 0),
                        "limit": int(change_item_limit_num or 0),
                        "reward_item": int(change_item_id or 0),
                        "reward_num": int(change_item_num or 0),
                    }
                    for (
                        exchange_id,
                        pay_item_id,
                        pay_item_num,
                        change_item_limit_num,
                        change_item_id,
                        change_item_num,
                    ) in cursor.execute(
                        "select id, pay_item_id, pay_item_num, "
                        "change_item_limit_num, change_item_id, change_item_num "
                        "from item_exchange"
                    )
                }
                return reward_to_exchange, catalog
            finally:
                connection.close()
        except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
            self._log(f"Daily Shop: couldn't read shop catalog: {exc}", "warning")
            return None, None

    def _daily_shop(self, client: Any) -> dict[str, Any]:
        self._set(task="Daily Shop")
        reward_to_exchange, catalog = self._load_shop_catalog()
        if not reward_to_exchange or not catalog:
            self._log(
                "Daily Shop: game master data not found — cannot map shop items.",
                "warning",
            )
            return {"bought": [], "detail": "no master data"}

        response = client.item_show_exchange()
        data = _data(response)
        headers = response.get("data_headers", {}) if isinstance(response, dict) else {}
        servertime = headers.get("servertime") or _find_value(response, "servertime") or 0
        disabled = {
            int(value)
            for value in (_find_value(data, "disabled_id_array") or [])
            if str(value).lstrip("-").isdigit()
        }
        goods = _find_value(data, "limited_goods_info_array") or []

        plan: list[dict[str, Any]] = []
        for source_index, good in enumerate(goods):
            reward_id = int(good.get("reward_id") or good.get("id") or 0)
            exchange_id = int(reward_to_exchange.get(reward_id) or 0)
            info = catalog.get(exchange_id)
            if (
                not exchange_id
                or exchange_id in disabled
                or reward_id in disabled
                or not info
                or int(info.get("pay_item") or 0) != GOLD_ITEM_ID
            ):
                continue
            open_count = int(good.get("open_count") or 0)
            exchange_count = int(good.get("exchange_count") or 0)
            if open_count <= 0 or exchange_count > 0:
                continue
            plan.append(
                {
                    "exchange_id": exchange_id,
                    "count": 1,
                    "ex_param": {"open_count": open_count},
                    "cost": int(info.get("pay_num") or 0),
                    "pay_item": GOLD_ITEM_ID,
                    "disp_order": int(good.get("disp_order") or 0),
                    "source_index": source_index,
                }
            )

        if not plan:
            self._log("Daily Shop: nothing new to buy (already cleared today).")
            return {"bought": [], "detail": "already cleared"}

        plan.sort(key=lambda row: (row["cost"], row["exchange_id"]))
        starting_gold = int(getattr(client, "item_map", {}).get(GOLD_ITEM_ID, 0) or 0)
        remaining = starting_gold
        selected_rows: list[dict[str, Any]] = []
        bought: list[int] = []
        spend = 0
        skipped = 0
        for row in plan:
            cost = int(row["cost"])
            if cost < 0 or cost > remaining:
                skipped += 1
                continue
            remaining -= cost
            spend += cost
            bought.append(int(row["exchange_id"]))
            selected_rows.append({**row, "selection_index": len(selected_rows)})

        if not selected_rows:
            self._log("Daily Shop: not enough gold to buy anything.", "warning")
            return {"bought": [], "detail": "insufficient currency"}

        selected_rows.sort(
            key=lambda row: (
                0 if int(row.get("disp_order") or 0) > 0 else 1,
                int(row.get("disp_order") or row.get("selection_index") or 0),
                -int((row.get("ex_param") or {}).get("open_count") or 0),
                int(row.get("source_index") or 0),
            )
        )
        purchases = [
            {
                "exchange_id": int(row["exchange_id"]),
                "count": 1,
                "ex_param": dict(row["ex_param"]),
            }
            for row in selected_rows
        ]

        balances = [{"item_id": GOLD_ITEM_ID, "number": starting_gold}]
        result = client.item_exchange_multi(
            purchases,
            balances,
            _fmt_get_list_time(servertime),
        )
        rewards = _find_value(result, "add_item_list") or []
        tail = f"; skipped {skipped} (can't afford)" if skipped else ""
        self._log(
            f"Daily Shop: bought {len(bought)} item(s) for {spend} gold{tail}."
        )
        return {"bought": bought, "spend": {GOLD_ITEM_ID: spend}, "rewards": len(rewards)}
