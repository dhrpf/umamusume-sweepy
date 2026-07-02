"""Compare MCTS vs rule-based decisions across career logs.

Reads every career_log_*.json under uma_runtime/*/bot_logs, splits turns by
`decision_reason.startswith("MCTS")`, and reports per-group stat/final_turn.
Pick whichever log dirs to compare via positional args (default: bah).

Usage:
    ./venv/bin/python scripts/compare_mcts.py [acct_dir ...]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from statistics import mean

REPO = Path(__file__).resolve().parent.parent
RUNTIME = REPO / "uma_runtime"


def load_logs(accounts: list[str]) -> list[dict]:
    out: list[dict] = []
    for acct in accounts:
        base = RUNTIME / acct / "bot_logs"
        if not base.exists():
            print(f"[skip] {base} missing", file=sys.stderr)
            continue
        for p in sorted(base.glob("career_log_*.json")):
            try:
                out.append(json.loads(p.read_text()))
            except Exception as exc:
                print(f"[skip] {p.name}: {exc}", file=sys.stderr)
    return out


def turns_by_reason(log: dict) -> tuple[list[dict], list[dict]]:
    mcts, rule = [], []
    for t in log.get("turns") or []:
        reason = (t.get("decision_reason") or "").strip()
        (mcts if reason.startswith("MCTS") else rule).append(t)
    return mcts, rule


def last_stat(turns: list[dict], key: str) -> float:
    for t in reversed(turns):
        v = (t.get("stats") or {}).get(key)
        if v is not None:
            return float(v)
    return 0.0


def summarize(turns: list[dict], label: str) -> dict:
    if not turns:
        return {"group": label, "n": 0}
    keys = ["speed", "stamina", "power", "guts", "wiz"]
    return {
        "group": label,
        "n": len(turns),
        "final_turn": max(t.get("turn", 0) for t in turns),
        **{k: round(last_stat(turns, k), 1) for k in keys},
    }


def main() -> int:
    accounts = sys.argv[1:] or ["bah"]
    logs = load_logs(accounts)
    if not logs:
        print("no logs found", file=sys.stderr)
        return 1

    rows_mcts: list[dict] = []
    rows_rule: list[dict] = []
    for log in logs:
        m, r = turns_by_reason(log)
        rows_mcts.extend(m)
        rows_rule.extend(r)

    s_m = summarize(rows_mcts, "MCTS")
    s_r = summarize(rows_rule, "rule-based")

    print(f"accounts={accounts} logs={len(logs)}")
    print(f"MCTS        : n={s_m['n']}  final_turn={s_m.get('final_turn')}  "
          f"spd={s_m.get('speed')}  sta={s_m.get('stamina')}  pow={s_m.get('power')}  "
          f"gut={s_m.get('guts')}  wiz={s_m.get('wiz')}")
    print(f"rule-based  : n={s_r['n']}  final_turn={s_r.get('final_turn')}  "
          f"spd={s_r.get('speed')}  sta={s_r.get('stamina')}  pow={s_r.get('power')}  "
          f"gut={s_r.get('guts')}  wiz={s_r.get('wiz')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
