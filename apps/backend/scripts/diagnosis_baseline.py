#!/usr/bin/env python3
"""Measure the Phase 0 diagnosis baseline against the golden fixture (#181 TODO 3).

Run from apps/backend:

    python3 scripts/diagnosis_baseline.py

No diagnosis engine exists yet (#183 builds it) — this measures the
always-abstain reference diagnoser (`abstain_baseline`) against the golden
fixture, which is the honest floor a real engine has to beat. Once #183
ships, point `--diagnoser` at it (or import `evaluate` directly) to measure
the real thing against the same fixture.

Writes JSON to stdout and a human summary to stderr, matching
scripts/desktop-baseline.py's split, so the numbers can be piped into a
file while a person reads the summary.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domain.services.diagnosis_evaluation import (  # noqa: E402
    DEFAULT_SEED,
    abstain_baseline,
    evaluate,
    golden_dataset,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help=f"Fixture seed (default: {DEFAULT_SEED}). Same seed always produces the same fixture.",
    )
    args = parser.parse_args()

    dataset = golden_dataset(seed=args.seed)
    metrics = evaluate(dataset, abstain_baseline)

    print(json.dumps({"seed": args.seed, "diagnoser": "abstain_baseline", **metrics.as_dict()}, indent=2))

    print(f"\n{metrics.total_cases} golden case(s), seed {args.seed}.", file=sys.stderr)
    print(
        f"  coverage={metrics.coverage:.0%}  abstention_rate={metrics.abstention_rate:.0%}  "
        f"false_cause_rate={metrics.false_cause_rate:.0%}  "
        f"precision={'n/a (no claims made)' if metrics.precision is None else f'{metrics.precision:.0%}'}",
        file=sys.stderr,
    )
    print(
        "This is the always-abstain baseline, not a real diagnosis engine — "
        "#183's rules engine is measured against this same fixture once it ships.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
