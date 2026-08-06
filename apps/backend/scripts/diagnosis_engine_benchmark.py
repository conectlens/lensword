#!/usr/bin/env python3
"""Measure the real diagnosis engine against the golden fixture (#183 TODO 6).

Run from apps/backend:

    python3 scripts/diagnosis_engine_benchmark.py

Unlike scripts/diagnosis_baseline.py (the Phase 0 always-abstain floor),
this runs the actual rules engine (`real_engine`) and tags the artifact
with `rules_version` — TODO 6's "store benchmark artifacts by ruleset
version" — so a later rule change that shifts these numbers is a diffable
fact against a prior run, not something noticed only by accident.

Exits non-zero when the false-cause rate fails the release gate
(`FALSE_CAUSE_RATE_GATE`), matching the same check
`test_the_real_engine_passes_its_own_release_gate` makes in CI.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domain.services.diagnosis_engine import RULES_VERSION  # noqa: E402
from app.domain.services.diagnosis_evaluation import (  # noqa: E402
    DEFAULT_SEED,
    FALSE_CAUSE_RATE_GATE,
    evaluate,
    evaluate_per_class,
    golden_dataset,
    passes_release_gate,
    real_engine,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help=f"Fixture seed (default: {DEFAULT_SEED}). Same seed always produces the same fixture.",
    )
    args = parser.parse_args()

    dataset = golden_dataset(seed=args.seed)
    metrics = evaluate(dataset, real_engine)
    per_class = evaluate_per_class(dataset, real_engine)
    passed = passes_release_gate(metrics)

    artifact = {
        "seed": args.seed,
        "diagnoser": "real_engine",
        "rules_version": RULES_VERSION,
        "false_cause_rate_gate": FALSE_CAUSE_RATE_GATE,
        "passes_release_gate": passed,
        **metrics.as_dict(),
        "per_class": {
            category: {
                "support": m.support,
                "true_positives": m.true_positives,
                "false_positives": m.false_positives,
                "false_negatives": m.false_negatives,
                "precision": m.precision,
                "recall": m.recall,
            }
            for category, m in per_class.items()
        },
    }
    print(json.dumps(artifact, indent=2))

    print(f"\nrules_version={RULES_VERSION}, {metrics.total_cases} golden case(s), seed {args.seed}.", file=sys.stderr)
    print(
        f"  coverage={metrics.coverage:.0%}  abstention_rate={metrics.abstention_rate:.0%}  "
        f"false_cause_rate={metrics.false_cause_rate:.0%} (gate: <= {FALSE_CAUSE_RATE_GATE:.0%})  "
        f"precision={'n/a (no claims made)' if metrics.precision is None else f'{metrics.precision:.0%}'}",
        file=sys.stderr,
    )
    print(f"  release gate: {'PASS' if passed else 'FAIL'}", file=sys.stderr)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
