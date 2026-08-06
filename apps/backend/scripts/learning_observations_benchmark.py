#!/usr/bin/env python3
"""Benchmark learning_observations query performance (issue #182 TODO 4).

Run from apps/backend:

    python3 scripts/learning_observations_benchmark.py

Seeds a scratch database (a temp SQLite file by default; pass --database-url
to point at a real Postgres instance for production-realistic numbers — the
query planner and index behavior genuinely differ between the two) with
synthetic observations, then reports p50/p95/max latency for each of the
five query axes issue #182 TODO 4 names: word, pair, time window, modality,
and intervention.

WHAT THIS SCRIPT CANNOT DO
---------------------------
The issue's own verify line asks for "p95 query time... below the agreed
threshold" without stating what that threshold is anywhere in the issue,
its parent (#180), or the epic ADR (0007). There is nothing to pass or
fail against. This script reports real, reproducible numbers instead of
inventing a threshold to assert against — the number a team can actually
agree on belongs in a follow-up once someone states it.

Default scale is modest (2,000 words / 20,000 observations) so this runs in
seconds during normal use; pass --words/--observations for the issue's
stated 10,000-word / 100,000-observation scale, which takes longer to seed.
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.domain.services.diagnosis_contracts import LearningObservation  # noqa: E402
from app.domain.value_objects import ReviewOutcome, SessionMode  # noqa: E402
from app.infrastructure.db import Base  # noqa: E402
from app.infrastructure.models import UserModel  # noqa: E402
from app.infrastructure.repositories import SqlAlchemyLearningObservationRepository  # noqa: E402

MODALITIES = ["typing", "speaking", "multiple_choice", "cloze", None]
BASE_TIME = datetime(2026, 1, 1)


def _seed(session_factory, words: int, observations: int, seed: int) -> int:
    rng = random.Random(seed)
    with session_factory() as db:
        db.add(
            UserModel(
                id=1, username="bench", email="bench@example.com", hashed_password="x",
                role="user", created_at=BASE_TIME, is_active=True,
            )
        )
        db.commit()

        repo = SqlAlchemyLearningObservationRepository(db)
        for i in range(observations):
            word_id = rng.randint(1, words)
            repo.add(
                LearningObservation(
                    observation_id=f"seed-{i}",
                    word_id=word_id,
                    user_id=1,
                    outcome=rng.choice(list(ReviewOutcome)),
                    session_mode=SessionMode.STANDARD,
                    observed_at=BASE_TIME + timedelta(minutes=rng.randint(0, 500_000)),
                    operation_id=f"op-{i}",
                    modality=rng.choice(MODALITIES),
                    intervention_plan_ref=f"plan-{rng.randint(1, 20)}" if rng.random() < 0.3 else None,
                )
            )
        db.commit()
    return words


def _timed(fn, repeats: int) -> dict:
    samples = []
    for _ in range(repeats):
        start = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - start) * 1000)
    samples.sort()
    return {
        "p50_ms": round(statistics.median(samples), 2),
        "p95_ms": round(samples[int(len(samples) * 0.95) - 1], 2),
        "max_ms": round(max(samples), 2),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--database-url", default=None, help="Defaults to a fresh temp SQLite file.")
    parser.add_argument("--words", type=int, default=2_000)
    parser.add_argument("--observations", type=int, default=20_000)
    parser.add_argument("--repeats", type=int, default=20, help="Samples per query for the percentile estimate.")
    parser.add_argument("--seed", type=int, default=20260806)
    args = parser.parse_args()

    tmp_path = None
    database_url = args.database_url
    if database_url is None:
        tmp_path = Path(tempfile.mkstemp(suffix=".db")[1])
        database_url = f"sqlite:///{tmp_path}"

    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    print(f"Seeding {args.observations} observations across {args.words} words...", file=sys.stderr)
    _seed(session_factory, args.words, args.observations, args.seed)

    with session_factory() as db:
        repo = SqlAlchemyLearningObservationRepository(db)
        results = {
            "list_for_word": _timed(lambda: repo.list_for_word(1, random.randint(1, args.words)), args.repeats),
            "list_for_pair": _timed(
                lambda: repo.list_for_pair(1, random.randint(1, args.words), random.randint(1, args.words)),
                args.repeats,
            ),
            "list_in_window": _timed(
                lambda: repo.list_in_window(1, BASE_TIME, BASE_TIME + timedelta(days=30)), args.repeats
            ),
            "list_by_modality": _timed(lambda: repo.list_by_modality(1, "typing"), args.repeats),
            "list_by_intervention": _timed(lambda: repo.list_by_intervention(1, "plan-1"), args.repeats),
        }

    if tmp_path is not None:
        tmp_path.unlink(missing_ok=True)

    print(json.dumps({"words": args.words, "observations": args.observations, "queries": results}, indent=2))
    print(
        "\nNo threshold to pass/fail against — issue #182 TODO 4 asks for a benchmark "
        "below 'the agreed threshold' without stating one anywhere in the issue, #180, "
        "or ADR 0007. These are real, reproducible numbers for that threshold to be set "
        "against once someone states it.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
