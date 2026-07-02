#!/usr/bin/env python3
"""Career log analyzer for Uma Musume bot runs."""
import json
import sys
import os
from datetime import datetime

def get_chara(call):
    d = call.get("data", {})
    if isinstance(d, dict) and "data" in d and isinstance(d["data"], dict):
        return d["data"].get("chara_info")
    return None

def get_inner(call):
    d = call.get("data", {})
    if isinstance(d, dict) and "data" in d and isinstance(d["data"], dict):
        return d["data"]
    return {}

def load_race_map(base_dir):
    path = os.path.join(base_dir, "data", "race_map.json")
    try:
        with open(path) as f:
            rm = json.load(f)
        lookup = {}
        meta = rm.get("meta", {})
        for k, v in meta.items():
            if isinstance(v, dict) and "program_id" in v:
                lookup[v["program_id"]] = v.get("name", k)
        return lookup
    except Exception:
        return {}

def load_skill_data(base_dir):
    path = os.path.join(base_dir, "data", "skill_data.json")
    try:
        with open(path) as f:
            sd = json.load(f)
        lookup = {}
        if isinstance(sd, dict):
            for k, v in sd.items():
                if isinstance(v, dict):
                    lookup[v.get("id", int(k) if k.isdigit() else k)] = v.get("name", k)
                elif isinstance(v, str):
                    lookup[int(k) if k.isdigit() else k] = v
        elif isinstance(sd, list):
            for s in sd:
                if isinstance(s, dict) and "id" in s:
                    lookup[s["id"]] = s.get("name", str(s["id"]))
        return lookup
    except Exception:
        return {}

CMD_TYPE_MAP = {7: "REST", 8: "OUTING"}
CMD_ID_MAP = {
    101: "SPD", 102: "STA", 103: "POW", 105: "GUT", 106: "INT",
    601: "SPD☀", 602: "STA☀", 603: "POW☀", 604: "GUT☀", 605: "INT☀",
}
CMD_MAP = {1: "SPD", 2: "STA", 3: "POW", 4: "GUT", 5: "INT", 7: "REST", 8: "OUTING"}

def classify_command(command_type, command_id):
    if command_type == 1:
        return CMD_ID_MAP.get(command_id, f"train_{command_id}")
    if command_type <= 5:
        return CMD_MAP.get(command_type, f"type_{command_type}")
    return CMD_TYPE_MAP.get(command_type, f"type_{command_type}")
MOTIV_MAP = {1: "最悪", 2: "悪い", 3: "普通", 4: "好調", 5: "絶好調"}

def analyze(log_path):
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    with open(log_path) as f:
        log = json.load(f)

    race_map = load_race_map(base_dir)
    skill_data = load_skill_data(base_dir)
    turns = log.get("turns", [])

    # === HEADER ===
    print("=" * 60)
    print("CAREER LOG ANALYSIS")
    print("=" * 60)
    print(f"  Preset:    {log.get('preset_name', '?')}")
    print(f"  Scenario:  {log.get('scenario_id', '?')}")
    print(f"  Status:    {log.get('status', '?')}")
    err = log.get("error")
    if err:
        print(f"  Error:     {err}")
    started = log.get("started_at", "")
    ended = log.get("ended_at", "")
    if started and ended:
        try:
            t0 = datetime.fromisoformat(started)
            t1 = datetime.fromisoformat(ended)
            dur = t1 - t0
            mins = int(dur.total_seconds() // 60)
            secs = int(dur.total_seconds() % 60)
            print(f"  Duration:  {mins}m {secs}s")
        except Exception:
            pass
    print(f"  Started:   {started}")
    print(f"  Ended:     {ended}")
    print(f"  Final turn: {log.get('final_turn', '?')}")
    print(f"  Turns logged: {len(turns)}")

    # === FINAL STATS ===
    chara = None
    for turn in reversed(turns):
        for call in reversed(turn["api_calls"]):
            c = get_chara(call)
            if c:
                chara = c
                break
        if chara:
            break

    if chara:
        spd = chara.get("speed", 0)
        sta = chara.get("stamina", 0)
        pow_ = chara.get("power", 0)
        gut = chara.get("guts", 0)
        wiz = chara.get("wiz", 0)
        total = spd + sta + pow_ + gut + wiz
        print(f"\n{'=' * 60}")
        print("FINAL STATS")
        print("=" * 60)
        print(f"  SPD: {spd:>5d}")
        print(f"  STA: {sta:>5d}")
        print(f"  POW: {pow_:>5d}")
        print(f"  GUT: {gut:>5d}")
        print(f"  INT: {wiz:>5d}")
        print(f"  ─────────")
        print(f"  Total: {total:>5d}")
        print(f"  Fans: {chara.get('fans', 0):>10,}")
        print(f"  Motivation: {MOTIV_MAP.get(chara.get('motivation', 0), '?')}")
        print(f"  Skill pts: {chara.get('skill_point', 0)}")
        learned = [s for s in chara.get("skill_array", []) if s.get("level", 0) > 0]
        print(f"  Skills learned: {len(learned)}")

    # === TRAINING DISTRIBUTION ===
    print(f"\n{'=' * 60}")
    print("TRAINING DISTRIBUTION")
    print("=" * 60)
    cmd_counts = {}
    for turn in turns:
        for call in turn["api_calls"]:
            if call["direction"] == "REQ" and "exec_command" in call.get("endpoint", ""):
                d = call.get("data", {})
                payload = d.get("payload", d)
                ct = payload.get("command_type", -1)
                cid = payload.get("command_id", -1)
                label = classify_command(ct, cid)
                cmd_counts[label] = cmd_counts.get(label, 0) + 1

    display_order = ["SPD", "STA", "POW", "GUT", "INT", "SPD☀", "STA☀", "POW☀", "GUT☀", "INT☀", "REST", "OUTING"]
    for label in display_order:
        if label in cmd_counts:
            bar = "█" * cmd_counts[label]
            print(f"  {label:>7s}: {cmd_counts[label]:>3d}  {bar}")
    other = {k: v for k, v in cmd_counts.items() if k not in display_order}
    for k, v in other.items():
        print(f"  {k:>7s}: {v:>3d}")
    print(f"  {'Total':>7s}: {sum(cmd_counts.values()):>3d}")

    # === RACE RESULTS ===
    print(f"\n{'=' * 60}")
    print("RACE RESULTS")
    print("=" * 60)
    race_count = 0
    wins = 0
    for turn in turns:
        pid_start = None
        for call in turn["api_calls"]:
            if call["direction"] == "RES" and "race_start" in call.get("endpoint", ""):
                inner = get_inner(call)
                pid_start = inner.get("race_start_info", {}).get("program_id")
            if call["direction"] == "RES" and "race_end" in call.get("endpoint", ""):
                inner = get_inner(call)
                rh = inner.get("race_history", [])
                rr = inner.get("race_reward_info", {})
                pid = pid_start or (rh[0].get("program_id") if rh else None)
                rank = rh[0].get("result_rank") if rh else rr.get("result_rank")
                fans = rr.get("gained_fans", 0)
                name = race_map.get(pid, f"race_{pid}") if pid else "?"
                rank_str = f"#{rank}" if rank else "?"
                result = "  ✓" if rank == 1 else " ✗" if rank and rank > 3 else ""
                print(f"  Turn {turn['turn']:>2d}: {name:<35s} {rank_str:>3s}  (+{fans:>6,} fans){result}")
                race_count += 1
                if rank == 1:
                    wins += 1
    print(f"  ─────────")
    print(f"  {wins}/{race_count} wins")

    # === MOTIVATION TIMELINE ===
    print(f"\n{'=' * 60}")
    print("MOTIVATION CHANGES")
    print("=" * 60)
    prev_motiv = None
    for turn in turns:
        for call in turn["api_calls"]:
            c = get_chara(call)
            if c:
                m = c.get("motivation")
                if m != prev_motiv:
                    arrow = ""
                    if prev_motiv is not None:
                        arrow = " ↑" if m > prev_motiv else " ↓"
                    print(f"  Turn {turn['turn']:>2d}: {MOTIV_MAP.get(m, m)}{arrow}")
                    prev_motiv = m
                break

    # === FAILURE RATE FLAGS ===
    print(f"\n{'=' * 60}")
    print("HIGH FAILURE RATE TRAINING (game ≥20%)")
    print("=" * 60)
    risky_count = 0
    for turn in turns:
        cmd_info = None
        chosen_cmd = None
        vital = None
        max_vital = None

        for call in turn["api_calls"]:
            c = get_chara(call)
            if c:
                vital = c.get("vital")
                max_vital = c.get("max_vital")

            inner = get_inner(call)
            hi = inner.get("home_info", {})
            if "command_info_array" in hi:
                cmd_info = hi["command_info_array"]

            if call["direction"] == "REQ" and "exec_command" in call.get("endpoint", ""):
                d = call.get("data", {})
                payload = d.get("payload", d)
                chosen_cmd = payload

        if chosen_cmd and cmd_info:
            ct = chosen_cmd.get("command_type")
            cid = chosen_cmd.get("command_id")
            for cmd in cmd_info:
                if cmd.get("command_type") == ct and cmd.get("command_id") == cid:
                    fr = cmd.get("failure_rate", 0)
                    if fr >= 20:
                        label = classify_command(ct, cmd.get("command_id", -1))
                        severity = "⚠️" if fr < 50 else "🔴"
                        print(f"  {severity} Turn {turn['turn']:>2d}: {label} fail={fr}% vital={vital}/{max_vital}")
                        risky_count += 1
                    break
    if risky_count == 0:
        print("  None")
    else:
        print(f"  ─────────")
        print(f"  {risky_count} risky training actions")

    # === TRAINING FAILURES ===
    # Compare chara_info immediately before exec_command REQ vs exec_command RES
    # (NOT check_event, which may be separated by stat-modifying events)
    print(f"\n{'=' * 60}")
    print("TRAINING FAILURES (stat gain ≤5)")
    print("=" * 60)
    fail_count = 0
    training_total = 0
    for turn in turns:
        calls = turn["api_calls"]
        latest_chara = None
        for i, call in enumerate(calls):
            c = get_chara(call)
            if c:
                latest_chara = c
            if call["direction"] == "REQ" and "exec_command" in call.get("endpoint", ""):
                d = call.get("data", {})
                payload = d.get("payload", d)
                cmd_type = payload.get("command_type")
                if not cmd_type or cmd_type > 5:
                    continue
                training_total += 1
                pre = latest_chara
                post = None
                for j in range(i + 1, len(calls)):
                    if calls[j]["direction"] == "RES" and "exec_command" in calls[j].get("endpoint", ""):
                        post = get_chara(calls[j])
                        break
                if pre and post:
                    stats = ["speed", "stamina", "power", "guts", "wiz"]
                    gain = sum(post.get(s, 0) for s in stats) - sum(pre.get(s, 0) for s in stats)
                    if gain <= 5:
                        cid_for_label = payload.get("command_id", -1)
                        label = classify_command(cmd_type, cid_for_label)
                        print(f"  Turn {turn['turn']:>2d}: {label} training → gain={gain:+d}")
                        fail_count += 1
    if fail_count == 0:
        print("  None")
    else:
        print(f"  ─────────")
        print(f"  {fail_count} failures out of {training_total} training actions")

    # === STAT PROGRESSION ===
    print(f"\n{'=' * 60}")
    print("STAT PROGRESSION")
    print("=" * 60)
    checkpoints = list(range(1, log.get("final_turn", 60) + 1, 12))
    final = log.get("final_turn", 60)
    if final not in checkpoints:
        checkpoints.append(final)

    for cp in checkpoints:
        for turn in turns:
            if turn["turn"] == cp:
                for call in reversed(turn["api_calls"]):
                    c = get_chara(call)
                    if c:
                        s, st, p, g, w = c.get("speed",0), c.get("stamina",0), c.get("power",0), c.get("guts",0), c.get("wiz",0)
                        print(f"  Turn {cp:>2d}: SPD={s:>4d} STA={st:>4d} POW={p:>4d} GUT={g:>4d} INT={w:>4d}  Σ={s+st+p+g+w}")
                        break
                break

    # === SKILLS LEARNED ===
    print(f"\n{'=' * 60}")
    print("SKILLS LEARNED")
    print("=" * 60)
    if chara:
        learned = [s for s in chara.get("skill_array", []) if s.get("level", 0) > 0]
        if learned:
            for s in learned:
                sid = s["skill_id"]
                name = skill_data.get(sid, f"skill_{sid}")
                print(f"  {name} (id={sid})")
        else:
            print("  None")

    # === SUMMARY ===
    print(f"\n{'=' * 60}")
    print("ISSUES SUMMARY")
    print("=" * 60)
    issues = []
    if fail_count > 5:
        pct = round(fail_count / max(1, training_total) * 100)
        issues.append(f"🔴 {fail_count} training failures ({pct}% fail rate)")
    if risky_count > 5:
        issues.append(f"⚠️ {risky_count} high-risk training actions")
    if chara and total < 3000:
        issues.append(f"⚠️ Low total stats: {total}")
    if wins < race_count:
        losses = race_count - wins
        issues.append(f"⚠️ {losses} race loss(es)")
    training_labels = {"SPD","STA","POW","GUT","INT","SPD☀","STA☀","POW☀","GUT☀","INT☀"}
    trained_stats = set()
    for k in cmd_counts:
        if k in training_labels:
            trained_stats.add(k.replace("☀",""))
    if len(trained_stats) <= 1:
        issues.append(f"⚠️ One-dimensional training: only {', '.join(trained_stats)}")
    if log.get("error"):
        issues.append(f"🔴 Career ended with error: {log['error']}")

    if issues:
        for issue in issues:
            print(f"  {issue}")
    else:
        print("  ✓ No major issues detected")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 analyze.py <path-to-career-log.json>")
        print("typical log format: uma_runtime/<account>/bot_logs/career_log_<timestamp>")
        print("  e.g.: python3 analyze.py uma_runtime/abcde/bot_logs/career_log_1111111_2222222.json")
        sys.exit(1)
    analyze(sys.argv[1])
