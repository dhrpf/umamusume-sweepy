#!/usr/bin/env python3
"""Calibrate MCTS simulator params from career logs."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from career_bot.mcts.calibration.extract import extract_from_paths
from career_bot.mcts.calibration.fit import fit_params, write_params


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Calibrate MCTS URA simulator params")
    parser.add_argument("--scenario-id", type=int, required=True)
    parser.add_argument("--logs", nargs="+", required=True, help="log dirs/globs/files")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    extracted = extract_from_paths(args.logs, scenario_id=args.scenario_id)
    params = fit_params([extracted], scenario_id=args.scenario_id)
    write_params(params, args.out)

    print(f"logs_scanned={extracted.logs_scanned}")
    print(f"logs_used={extracted.logs_used}")
    print(f"turns_scanned={extracted.turns_scanned}")
    print(f"training_samples={len(extracted.training_samples)}")
    print(f"discarded_event_contaminated={extracted.discarded_event_contaminated}")
    print(f"confidence={params['confidence']}")
    if extracted.skip_reasons:
        print(f"skip_reasons={extracted.skip_reasons}")
    print(f"out={args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
