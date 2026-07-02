"""Fit URA simulator params from calibration extracts."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
import json
from pathlib import Path
from statistics import mean
from typing import Any

from career_bot.mcts.calibration.extract import CalibrationExtract, TrainingSample

DEFAULT_FAILURE_CURVE = [[1.0, 0.00], [0.7, 0.05], [0.5, 0.15], [0.3, 0.30], [0.1, 0.50]]


def fit_params(extracts: list[CalibrationExtract], scenario_id: int) -> dict[str, Any]:
    samples: list[TrainingSample] = []
    rest: list[float] = []
    outing: list[float] = []
    logs_used = 0
    level_obs: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for e in extracts:
        samples.extend(e.training_samples)
        rest.extend(e.rest_recoveries)
        outing.extend(e.outing_recoveries)
        logs_used += e.logs_used
        for cid, vals in e.level_observations.items():
            level_obs[cid].extend(vals)

    gains: dict[str, dict[str, list[float]]] = {}
    grouped: dict[tuple[int, int], list[tuple[float, ...]]] = defaultdict(list)
    vital_costs: dict[int, list[float]] = defaultdict(list)
    failure_points: dict[float, list[float]] = defaultdict(list)
    for s in samples:
        grouped[(s.command_id, s.level)].append(s.forecast_gains)
        if s.vital_delta < 0:
            vital_costs[s.command_id].append(abs(s.vital_delta))
        bucket = _nearest_bucket(s.vital_ratio)
        failure_points[bucket].append(s.failure_rate)
    for (cid, lvl), vals in grouped.items():
        gains.setdefault(str(cid), {})[str(lvl)] = [_round(mean(v[i] for v in vals)) for i in range(6)]

    vital_cost = {str(cid): _round(mean(vals)) for cid, vals in vital_costs.items() if vals}
    failure_curve = [[bucket, _round(mean(vals), 4)] for bucket, vals in sorted(failure_points.items(), reverse=True) if vals]
    if not failure_curve:
        failure_curve = DEFAULT_FAILURE_CURVE

    level_up_counts = _infer_level_thresholds(level_obs)
    confidence = "high" if logs_used >= 20 else "warning" if logs_used >= 10 else "disabled"
    return {
        "scenario_id": scenario_id,
        "training_gains": gains,
        "vital_cost": vital_cost,
        "failure_curve": failure_curve,
        "rest_recovery": _round(mean(rest)) if rest else 45.0,
        "outing_recovery": _round(mean(outing)) if outing else 35.0,
        "bond_per_interaction": 7,
        "level_up_counts": level_up_counts,
        "calibrated_from": logs_used,
        "calibrated_at": date.today().isoformat(),
        "confidence": confidence,
    }


def write_params(params: dict[str, Any], path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(params, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _nearest_bucket(ratio: float) -> float:
    buckets = [1.0, 0.7, 0.5, 0.3, 0.1]
    return min(buckets, key=lambda b: abs(b - ratio))


def _infer_level_thresholds(obs: dict[int, list[tuple[int, int]]]) -> dict[str, list[int]]:
    out: dict[str, list[int]] = {}
    for cid, vals in obs.items():
        thresholds: dict[int, int] = {}
        for count, level in sorted(vals):
            if level > 1 and level not in thresholds:
                thresholds[level] = count
        if thresholds:
            out[str(cid)] = [thresholds[level] for level in sorted(thresholds)]
    return out


def _round(v: float, ndigits: int = 2) -> float:
    return round(float(v), ndigits)
