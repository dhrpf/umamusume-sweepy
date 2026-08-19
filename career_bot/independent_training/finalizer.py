from __future__ import annotations

from contextlib import nullcontext
from typing import Any

from .factors import choose_factor_candidate, normalize_factor_candidates


class NeedsAttention(RuntimeError):
    """A mutating request may have succeeded and must be reconciled."""


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


def _common(response: dict[str, Any], suffix: str) -> dict[str, Any]:
    data = (response or {}).get("data") or {}
    for key, value in data.items():
        if str(key).endswith(suffix) and isinstance(value, dict):
            return value
    return {}


def _minimal_chara(chara: dict[str, Any]) -> dict[str, Any]:
    return {
        key: chara[key]
        for key in _CHARA_FIELDS
        if key in chara
    }


def _factor_rows(response: dict[str, Any]) -> list[dict[str, Any]]:
    common = _common(response, "factor_select_common")
    rows = list(common.get("factor_select_info_array") or [])
    if not rows:
        rows = list(common.get("factor_relottery_info_array") or [])
    return rows


class IndependentFinalizer:
    def __init__(
        self,
        *,
        store,
        client,
        skill_buyer,
        factor_map: dict[str, Any],
    ) -> None:
        self.store = store
        self.client = client
        self.skill_buyer = skill_buyer
        self.factor_map = factor_map

    def run(self, run: dict[str, Any]) -> dict[str, Any]:
        current = dict(run)
        setup = current.get("setup") or {}
        progress = current.get("finalization") or {}
        chara = dict(progress.get("chara_info") or {})
        if not chara:
            raise ValueError("finalization requires collected chara_info")
        current_turn = int(chara.get("turn") or 0)

        if not progress.get("skills_completed"):
            result_response = self.client.independent_training_result()
            fresh_chara = (
                ((result_response or {}).get("data") or {}).get("end_info") or {}
            ).get("chara_info") or {}
            if fresh_chara:
                chara = _minimal_chara(fresh_chara)
                current_turn = int(chara.get("turn") or current_turn)
                current = self.store.update_finalization(
                    current["run_id"],
                    current["version"],
                    {"chara_info": chara},
                )
                progress = current.get("finalization") or {}

            pacing = getattr(self.client, "independent_skill_pacing", None)
            with (pacing() if callable(pacing) else nullcontext()):
                state, bought = self.skill_buyer.final_purchase(
                    self.client,
                    {"data": {"chara_info": chara}},
                    priority_skill_ids=[
                        int(skill_id)
                        for skill_id in setup.get("final_skill_ids") or []
                    ],
                    running_style=int(setup.get("running_style") or 0),
                )
            if bought == 0 and self.skill_buyer.last_result.get("result") == "failed":
                raise RuntimeError(
                    "skill purchase attempt failed: "
                    f"{self.skill_buyer.last_result.get('error')}"
                )

            updated_chara = (
                (state.get("data") or {}).get("chara_info")
                or chara
            )
            chara = _minimal_chara(updated_chara)
            current_turn = int(chara.get("turn") or current_turn)
            current = self.store.update_finalization(
                current["run_id"],
                current["version"],
                {
                    "skills_completed": True,
                    "skills_bought": int(bought),
                    "chara_info": chara,
                },
            )
            progress = current.get("finalization") or {}

        targets = list(
            ((setup.get("factor_reroll") or {}).get("targets") or [])
        )
        initial_raw: list[dict[str, Any]] = []
        candidates = list(current.get("factor_candidates") or [])
        factor_common: dict[str, Any] = {}
        if not progress.get("factor_select_completed"):
            response = self.client.select_independent_factors(current_turn)
            factor_common = _common(response, "factor_select_common")
            initial_raw = _factor_rows(response)
            candidates = normalize_factor_candidates(
                initial_raw,
                self.factor_map,
                targets,
            )
            current = self.store.update_finalization(
                current["run_id"],
                current["version"],
                {
                    "factor_select_completed": True,
                    "factor_candidates": candidates,
                    "lottery_count": int(
                        factor_common.get("lottery_count") or 0
                    ),
                    "lottery_remain_num": int(
                        factor_common.get("lottery_remain_num") or 0
                    ),
                },
            )
            progress = current.get("finalization") or {}
        elif not candidates:
            candidates = list(progress.get("factor_candidates") or [])

        if not candidates:
            raise ValueError("factor selection did not return a candidate")

        selected = choose_factor_candidate(candidates)
        reroll = setup.get("factor_reroll") or {}
        should_reroll = bool(reroll.get("enabled")) and not bool(
            selected.get("all_targets_matched")
        )
        skip_reason = ""
        if should_reroll:
            remain = int(progress.get("lottery_remain_num") or 0)
            tp_info = dict(progress.get("tp_info") or {})
            if remain <= 0:
                skip_reason = "no_lottery_remaining"
            elif int(tp_info.get("current_tp") or 0) < 30:
                skip_reason = "insufficient_tp"
            elif current.get("factor_lottery_attempted"):
                if current.get("selected_lottery_id") is None:
                    raise NeedsAttention(
                        "factor lottery result is ambiguous; reconcile before retry"
                    )
                should_reroll = False
            else:
                current = self.store.mark_factor_lottery_attempted(
                    current["run_id"],
                    current["version"],
                )
                try:
                    response = self.client.reroll_independent_factors(
                        int(progress.get("lottery_count") or 0),
                        tp_info,
                        use_tp=30,
                    )
                except Exception as exc:
                    raise NeedsAttention(
                        "factor lottery result is ambiguous"
                    ) from exc
                rerolled_raw = _factor_rows(response)
                if initial_raw:
                    original_id = int(initial_raw[0].get("lottery_id") or 0)
                    if not any(
                        int(row.get("lottery_id") or 0) == original_id
                        for row in rerolled_raw
                    ):
                        rerolled_raw = [initial_raw[0], *rerolled_raw]
                candidates = normalize_factor_candidates(
                    rerolled_raw,
                    self.factor_map,
                    targets,
                )
                selected = choose_factor_candidate(candidates)

        if skip_reason:
            current = self.store.update_finalization(
                current["run_id"],
                current["version"],
                {"factor_lottery_skip": skip_reason},
            )
        if current.get("selected_lottery_id") is None:
            current = self.store.save_factor_candidates(
                current["run_id"],
                current["version"],
                candidates,
                selected_lottery_id=int(selected["lottery_id"]),
            )

        selected_lottery_id = int(
            current.get("selected_lottery_id")
            or selected.get("lottery_id")
            or 0
        )
        if current.get("finish_attempted"):
            result = dict(current.get("result") or {})
            if result.get("trained_chara_id"):
                return result
            raise NeedsAttention(
                "finish result is ambiguous; reconcile before retry"
            )

        current = self.store.mark_finish_attempted(
            current["run_id"],
            current["version"],
        )
        try:
            response = self.client.finish_independent_training(
                current_turn,
                selected_lottery_id,
            )
        except Exception as exc:
            raise NeedsAttention("finish result is ambiguous") from exc

        result = self._result_summary(
            response,
            current_turn=current_turn,
            selected_lottery_id=selected_lottery_id,
        )
        current = self.store.save_result(
            current["run_id"],
            current["version"],
            result,
        )
        return dict(current.get("result") or result)

    @staticmethod
    def _result_summary(
        response: dict[str, Any],
        *,
        current_turn: int,
        selected_lottery_id: int,
    ) -> dict[str, Any]:
        data = (response or {}).get("data") or {}
        common = _common(response, "finish_common")
        trained_chara_id = int(common.get("trained_chara_id") or 0)
        rows = data.get("trained_chara") or []
        if isinstance(rows, dict):
            rows = [rows]
        trained = next(
            (
                row
                for row in rows
                if int(row.get("trained_chara_id") or 0)
                == trained_chara_id
            ),
            {},
        )
        return {
            "trained_chara_id": trained_chara_id,
            "card_id": int(trained.get("card_id") or 0),
            "rank": int(trained.get("rank") or 0),
            "current_turn": int(current_turn),
            "selected_lottery_id": int(selected_lottery_id),
        }
