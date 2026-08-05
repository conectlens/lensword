"""SCRATCH: verifying issue #164's branch-protection gate. Do not merge.

Fails only when run against Postgres, passes on SQLite — the same dialect
divergence #164 describes, produced deliberately rather than by reintroducing
a real bug (the real #136 regression, test_deleting_the_conversation_takes_
the_attempt_with_it, is now caught on both dialects by its own assertion,
so it is no longer a clean demonstrator of Postgres-only failure on its own).
"""
from tests.conftest import _USING_POSTGRES


def test_scratch_this_only_fails_on_postgres():
    assert not _USING_POSTGRES, "expected failure: proving the Postgres-only CI job blocks a merge"
