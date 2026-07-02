"""Extract URA simulator calibration samples from career logs."""

from __future__ import annotations

from dataclasses import dataclass, field
import glob
import json
from pathlib import Path
from typing import Any

STAT_KEYS = ["speed", "stamina", "power", "guts", "wiz"]
STAT_TARGETS = {1: 0, 2: 1, 3: 2, 4: 3, 5: 4, 11: 5}


@dataclass(frozen=True)
class TrainingSample:
    command_id: int
    level: int
    forecast_gains: tuple[float, float, float, float, float, float]
    vital_delta: float
    failure_rate: float
    vital_ratio: float
    actual_gains: tuple[float, float, float, float, float, float] | None = None


@dataclass
class CalibrationExtract:
    scenario_id: int
    logs_scanned: int = 0
    logs_used: int = 0
    turns_scanned: int = 0
    training_samples: list[TrainingSample] = field(default_factory=list)
    rest_recoveries: list[float] = field(default_factory=list)
    outing_recoveries: list[float] = field(default_factory=list)
    level_observations: dict[int, list[tuple[int, int]]] = field(default_factory=dict)
    discarded_event_contaminated: int = 0
    skip_reasons: dict[str, int] = field(default_factory=dict)

    def merge(self, other: "CalibrationExtract") -> "CalibrationExtract":
        self.logs_scanned += other.logs_scanned
        self.logs_used += other.logs_used
        self.turns_scanned += other.turns_scanned
        self.training_samples.extend(other.training_samples)
        self.rest_recoveries.extend(other.rest_recoveries)
        self.outing_recoveries.extend(other.outing_recoveries)
        self.discarded_event_contaminated += other.discarded_event_contaminated
        for k, v in other.skip_reasons.items():
            self.skip_reasons[k] = self.skip_reasons.get(k, 0) + v
        for k, vals in other.level_observations.items():
            self.level_observations.setdefault(k, []).extend(vals)
        return self


def extract_from_paths(paths: list[str], scenario_id: int) -> CalibrationExtract:
    out = CalibrationExtract(scenario_id=scenario_id)
    expanded: list[str] = []
    for p in paths:
        pp = Path(p)
        if pp.is_dir():
            expanded.extend(glob.glob(str(pp / "**" / "career_log_*.json"), recursive=True))
        else:
            expanded.extend(glob.glob(p))
    for p in sorted(set(expanded)):
        try:
            with open(p, "r", encoding="utf-8") as f:
                log = json.load(f)
        except Exception:
            out.logs_scanned += 1
            out.skip_reasons["bad_json"] = out.skip_reasons.get("bad_json", 0) + 1
            continue
        out.merge(extract_from_log(log, scenario_id=scenario_id))
    return out


def extract_from_log(log: dict[str, Any], scenario_id: int) -> CalibrationExtract:
    out = CalibrationExtract(scenario_id=scenario_id, logs_scanned=1)
    if int(log.get("scenario_id") or -1) != int(scenario_id):
        out.skip_reasons["scenario_mismatch"] = 1
        return out
    out.logs_used = 1
    counts: dict[int, int] = {}
    last_check: dict[str, Any] | None = None
    for turn in log.get("turns") or []:
        out.turns_scanned += 1
        cur = turn.get("current_command") or {}
        ctype = int(cur.get("command_type") or 0)
        cid = int(cur.get("command_id") or 0)
        calls = turn.get("api_calls") or []
        pre = _decision_state(turn) or _find_pre_command_check(calls, cur) or last_check
        post_exec = _find_post_exec(calls)
        post_check = _find_post_check(calls)
        if not cid:
            if post_check:
                last_check = post_check
            continue
        if ctype == 1:
            if not pre:
                out.skip_reasons["missing_pre_check"] = out.skip_reasons.get("missing_pre_check", 0) + 1
                continue
            command = _find_command(pre, cid)
            if not command:
                out.skip_reasons["missing_command_forecast"] = out.skip_reasons.get("missing_command_forecast", 0) + 1
                continue
            level = int(command.get("level") or command.get("training_level") or 1)
            gains, vital_delta = _forecast(command)
            chara = (pre.get("chara_info") or {}) if isinstance(pre, dict) else {}
            vital = float(chara.get("vital") or cur.get("current_vital") or 0)
            max_vital = float(chara.get("max_vital") or 100)
            failure_rate = _failure_rate(command)
            actual = None
            contaminated = _has_event(post_exec) or _has_event(post_check)
            if contaminated:
                out.discarded_event_contaminated += 1
            elif post_exec:
                actual = _actual_diff(chara, (post_exec.get("chara_info") or {}) if isinstance(post_exec, dict) else {})
            out.training_samples.append(TrainingSample(cid, level, gains, vital_delta, failure_rate, vital / max_vital if max_vital else 1.0, actual))
            counts[cid] = counts.get(cid, 0) + 1
            if post_check:
                next_cmd = _find_command(post_check, cid)
                if next_cmd:
                    out.level_observations.setdefault(cid, []).append((counts[cid], int(next_cmd.get("level") or level)))
        elif ctype == 7 and post_exec and pre:
            delta = _vital(post_exec) - _vital(pre)
            if delta > 0:
                out.rest_recoveries.append(delta)
        elif ctype == 3 and post_exec and pre:
            delta = _vital(post_exec) - _vital(pre)
            if delta > 0:
                out.outing_recoveries.append(delta)
        if post_check:
            last_check = post_check
        elif post_exec:
            last_check = post_exec
    return out


def _decision_state(turn: dict[str, Any]) -> dict[str, Any] | None:
    snap = turn.get("decision_state") or {}
    if not snap:
        return None
    return {
        "chara_info": snap.get("chara_info") or {},
        "home_info": {"command_info_array": snap.get("command_info_array") or []},
        "unchecked_event_array": [],
    }


def _unwrap(data):
    d = data or {}
    inner = d.get("data") if isinstance(d, dict) else None
    if isinstance(inner, dict) and ("chara_info" in inner or "home_info" in inner):
        return inner
    if isinstance(inner, dict):
        deeper = inner.get("data") if isinstance(inner.get("data"), dict) else None
        if deeper and ("chara_info" in deeper or "home_info" in deeper):
            return deeper
    return d


def _charm_info(data):
    return (data or {}).get("chara_info") or {}


def _vital_from(data):
    return float(_charm_info(data).get("vital") or 0)


def _find_command(data, command_id):
    for cmd in (((data or {}).get("home_info") or {}).get("command_info_array") or []):
        if int(cmd.get("command_id") or 0) == int(command_id) and int(cmd.get("command_type") or 0) == 1:
            return cmd
    return None


def _find_pre_command_check(calls, cur):
    current_turn = int(cur.get("current_turn") or cur.get("turn") or 0)
    candidates = []
    for c in calls:
        if c.get("direction") != "RES" or not c.get("endpoint", "").endswith("/check_event"):
            continue
        data = _unwrap(c.get("data"))
        chara = _charm_info(data)
        turn = int(chara.get("turn") or c.get("turn") or 0)
        if not current_turn or turn <= current_turn:
            candidates.append(data)
    return candidates[-1] if candidates else None


def _find_post_exec(calls):
    for c in calls:
        if c.get("direction") == "RES" and c.get("endpoint", "").endswith("/exec_command"):
            return _unwrap(c.get("data"))
    return None


def _find_post_check(calls):
    checks = [_unwrap(c.get("data")) for c in calls if c.get("direction") == "RES" and c.get("endpoint", "").endswith("/check_event")]
    return checks[-1] if checks else None


def _forecast(command):
    gains = [0.0] * 6
    vital = 0.0
    for item in command.get("params_inc_dec_info_array") or []:
        t = int(item.get("target_type") or 0)
        v = float(item.get("value") or 0)
        if t in STAT_TARGETS:
            gains[STAT_TARGETS[t]] += v
        elif t in (10, 30):
            vital += v
    return (gains[0], gains[1], gains[2], gains[3], gains[4], gains[5]), vital


def _actual_diff(pre, post):
    vals = [float(post.get(k) or 0) - float(pre.get(k) or 0) for k in STAT_KEYS]
    vals.append(float(post.get("skill_point") or 0) - float(pre.get("skill_point") or 0))
    return (vals[0], vals[1], vals[2], vals[3], vals[4], vals[5])


def _failure_rate(command):
    r = float(command.get("failure_rate") or 0.0)
    return r / 100.0 if r > 1.0 else r


def _vital(data):
    return float(((data or {}).get("chara_info") or {}).get("vital") or 0)


def _has_event(data):
    return bool((data or {}).get("unchecked_event_array"))
