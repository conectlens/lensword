#!/usr/bin/env python3
"""Backfill knowledge_edges for accounts that predate #203 (issue #203 TODO 7).

Run from apps/backend, against the real configured DATABASE_URL:

    python3 scripts/backfill_knowledge_edges.py           # apply
    python3 scripts/backfill_knowledge_edges.py --dry-run # report only

New words get their edges from the moment they're created (#203's
incremental write path) — this script is only for words that existed
before that path shipped, whose knowledge_edges rows would otherwise stay
empty forever.

Idempotent and re-runnable: each account's edges are fully replaced from
its current word/mistake data, not appended to, so running this twice (or
after a partial failure) produces the same end state as running it once.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.application.use_cases.knowledge_graph import confusions_for, nodes_for  # noqa: E402
from app.domain.services.knowledge_graph import build_edges  # noqa: E402
from app.infrastructure.db import SessionLocal  # noqa: E402
from app.infrastructure.repositories import (  # noqa: E402
    SqlAlchemyKnowledgeEdgeRepository,
    SqlAlchemyMistakeEventRepository,
    SqlAlchemyUserRepository,
    SqlAlchemyWordRepository,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Report counts without writing.")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        users = SqlAlchemyUserRepository(db).list_all(search=None, limit=1_000_000, offset=0)
        word_repo = SqlAlchemyWordRepository(db)
        mistake_repo = SqlAlchemyMistakeEventRepository(db)
        edge_repo = SqlAlchemyKnowledgeEdgeRepository(db)

        total_accounts = 0
        total_edges = 0
        for user in users:
            words = word_repo.list_all_for_user(user.id)
            if not words:
                continue
            nodes = nodes_for(words)
            confusions = confusions_for(mistake_repo, user.id)
            edges = build_edges(nodes, confusions)

            total_accounts += 1
            total_edges += len(edges)
            print(f"user {user.id} ({user.username}): {len(words)} word(s) -> {len(edges)} edge(s)", file=sys.stderr)

            if not args.dry_run:
                edge_repo.replace_all_for_user(user.id, edges)

        if not args.dry_run:
            db.commit()

        print(
            f"\n{'Would write' if args.dry_run else 'Wrote'} {total_edges} edge(s) "
            f"across {total_accounts} account(s) with at least one word.",
            file=sys.stderr,
        )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
