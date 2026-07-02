"""MCTS state/action snapshots."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
from typing import Any


STAT_TARGETS = {1: 0, 2: 1, 3: 2, 4: 3, 5: 4, 11: 5}
TRAINING_INDEX = {101: 0, 102: 1, 103: 2, 105: 3, 106: 4, 601: 0, 602: 1, 603: 2, 604: 3, 605: 4}


@dataclass(frozen=True)
class Action:
    action_type: str
    index: int
    stat_gains: tuple[float, float, float, float, float, float]
    vital_delta: float
    failure_rate: float
    partner_count: int
    command_type: int = 0
    command_id: int = 0
    command_group_id: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GameState:
    turn: int
    speed: float
    stamina: float
    power: float
    guts: float
    wiz: float
    vital: float
    max_vital: float
    motivation: int
    fans: float
    skill_points: float
    training_levels: tuple[int, ...] = (1, 1, 1, 1, 1)
    bonds: tuple[tuple[int, int], ...] = ()
    learned_skills: frozenset[int] = field(default_factory=frozenset)
    training_counts: tuple[int, ...] = (0, 0, 0, 0, 0)
    available_actions: tuple[Action, ...] = ()

    @classmethod
    def from_api(cls, api_state: dict[str, Any], training_counts: tuple[int, ...] | None = None) -> "GameState":
        data = api_state.get("data") if isinstance(api_state.get("data"), dict) else api_state
        data = data or {}
        chara = data.get("chara_info") or {}
        home = data.get("home_info") or {}
        counts = tuple(training_counts or (0, 0, 0, 0, 0))
        levels = _training_levels(home.get("command_info_array") or [])
        actions = tuple(_actions_from_commands(home.get("command_info_array") or []))
        return cls(
            turn=int(chara.get("turn") or 0),
            speed=float(chara.get("speed") or 0),
            stamina=float(chara.get("stamina") or 0),
            power=float(chara.get("power") or 0),
            guts=float(chara.get("guts") or 0),
            wiz=float(chara.get("wiz") or 0),
            vital=float(chara.get("vital") or 0),
            max_vital=float(chara.get("max_vital") or 100),
            motivation=int(chara.get("motivation") or 0),
            fans=float(chara.get("fans") or chara.get("fan_count") or 0),
            skill_points=float(chara.get("skill_point") or chara.get("skill_points") or 0),
            training_levels=levels,
            bonds=_bonds(chara),
            learned_skills=_learned_skills(chara),
            training_counts=counts,
            available_actions=actions,
        )

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["learned_skills"] = sorted(self.learned_skills)
        return d

    def stable_digest(self) -> str:
        payload = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _actions_from_commands(commands: list[dict[str, Any]]) -> list[Action]:
    actions: list[Action] = []
    for cmd in commands:
        if int(cmd.get("is_enable", 1)) != 1:
            continue
        command_type = int(cmd.get("command_type") or 0)
        command_id = int(cmd.get("command_id") or 0)
        command_group_id = int(cmd.get("command_group_id") or 0)
        if command_type == 1 and command_id in TRAINING_INDEX:
            gains, vital_delta = _gains_and_vital(cmd)
            actions.append(Action(
                "train",
                TRAINING_INDEX[command_id],
                gains,
                vital_delta if vital_delta <= 0 else -abs(vital_delta),
                _failure_rate(cmd),
                _partner_count(cmd),
                command_type,
                command_id,
                command_group_id,
            ))
        elif command_type == 7:
            actions.append(Action("rest", 0, (0.0, 0.0, 0.0, 0.0, 0.0, 0.0), 45.0, 0.0, 0, command_type, command_id, command_group_id))
        elif command_type == 3:
            actions.append(Action("outing", 0, (0.0, 0.0, 0.0, 0.0, 0.0, 0.0), 35.0, 0.0, 0, command_type, command_id, command_group_id))
    return actions


def _gains_and_vital(cmd: dict[str, Any]) -> tuple[tuple[float, float, float, float, float, float], float]:
    gains = [0.0] * 6
    vital_delta = 0.0
    for item in cmd.get("params_inc_dec_info_array") or []:
        t = int(item.get("target_type") or 0)
        v = float(item.get("value") or 0)
        if t in STAT_TARGETS:
            gains[STAT_TARGETS[t]] += v
        elif t in (10, 30):
            vital_delta += v
    return (gains[0], gains[1], gains[2], gains[3], gains[4], gains[5]), vital_delta


def _failure_rate(cmd: dict[str, Any]) -> float:
    rate = float(cmd.get("failure_rate") or 0.0)
    return rate / 100.0 if rate > 1.0 else rate


def _partner_count(cmd: dict[str, Any]) -> int:
    for key in ("support_card_array", "training_partner_array", "chara_array"):
        val = cmd.get(key)
        if isinstance(val, list):
            return len(val)
    return int(cmd.get("partner_count") or 0)


def _training_levels(commands: list[dict[str, Any]]) -> tuple[int, ...]:
    levels = [1, 1, 1, 1, 1]
    for cmd in commands:
        cid = int(cmd.get("command_id") or 0)
        if cid in TRAINING_INDEX:
            levels[TRAINING_INDEX[cid]] = int(cmd.get("level") or cmd.get("training_level") or levels[TRAINING_INDEX[cid]])
    return tuple(levels)


def _learned_skills(chara: dict[str, Any]) -> frozenset[int]:
    ids: set[int] = set()
    for key in ("skill_array", "learned_skill_array"):
        for item in chara.get(key) or []:
            sid = int(item.get("skill_id") or item.get("id") or 0)
            if sid:
                ids.add(sid)
    return frozenset(ids)


def _bonds(chara: dict[str, Any]) -> tuple[tuple[int, int], ...]:
    out = []
    for item in chara.get("evaluation_info_array") or []:
        sid = int(item.get("support_card_id") or item.get("card_id") or item.get("id") or 0)
        val = int(item.get("evaluation") or item.get("bond") or item.get("value") or 0)
        if sid:
            out.append((sid, val))
    return tuple(sorted(out))
