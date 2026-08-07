"""The real background executor behind `companion_tasks.py` (#197 TODO 3).

Before this module, `CompanionTask` was a solid, well-tested state machine
with nothing driving it: progress and cancellation existed as bookkeeping
only, with no process ever actually advancing `completed_units` on its own.
This job is that process.

Design, and why it looks like the other dispatchers in this package
(`acquisition_dispatch.py`, `reminder_dispatch.py`): rather than register one
APScheduler job per task — which would need a request handler with access to
the live scheduler instance, and would leave nothing to re-register a task's
job after a restart short of re-implementing `restore_reminder_jobs` for
tasks too — this is a single recurring *poll* job, registered once at
startup exactly like the others. Every tick it asks
`CompanionTaskRepository.list_runnable` for outstanding EXTRACTION tasks and
runs each one to completion (or until it is cancelled/expires/hits this
tick's unit budget) in a synchronous loop that persists progress after
*every single unit*.

Only EXTRACTION runs here — not PLAN_GENERATION, even though
`CompanionTaskType` has that member too. Discovered while rebasing this
change onto `development`: #194 TODO 4 already gave `plan_generation` tasks
a real, synchronous lifecycle of its own
(`app/api/routers/companion_tasks.py`'s `generate-plan`/`confirm-plan`
endpoints, backed by `companion_planning.py`'s context-aware planner) —
`generate-plan` calls `task.complete(...)` directly inside the request that
creates the task, so a `plan_generation` task is essentially never left
sitting in PENDING/RUNNING waiting for a poller. Having this executor also
pick up that task type would race that existing flow (this executor would
`start()` a task the very next `generate-plan` call expects to still be
PENDING, then fail it for missing the `input` shape that flow never sets) —
exactly the "reuse, don't reinvent" a second competing implementation would
violate. `list_runnable` is scoped to EXTRACTION only for this reason.

That last property is what makes restart-survival, cancellation, and partial
results all fall out of the same mechanism instead of needing three:

* Restart survival: nothing about a task's progress lives only in memory.
  A crash between units loses at most one unit of work; the next tick (after
  the process comes back and `register_jobs` runs again) resumes from
  `completed_units`, not from zero.
* Cancellation: a task is cancelled by the existing `/tasks/{id}/cancel`
  endpoint or MCP tool, which flips `status` in the database immediately and
  independently of this job. Before starting each unit, the loop re-reads
  the task's current status; a status that is no longer RUNNING/PENDING
  stops the loop without claiming a unit it did not do.
* Partial results: `record_partial_result` is called after every unit with
  a `"partial": True` marker, so a task's `result` field always reflects
  real completed work, and only the final `complete()` call — reached only
  when every unit finished — drops that marker. A cancelled or
  still-running task can never look completed by glancing at `result` alone.

What this deliberately is NOT: a queue, a worker pool, or a second job
system. It is one more interval job on the same in-process APScheduler
`register_jobs` already builds, following the same
poll-claim-with-`job_claims`-execute shape `AcquisitionDispatcher` uses. It
does not survive more than one backend instance being exclusively correct
without `job_claims` (handled below), and it does not run outside this
process — there is no separate worker fleet here, by design, matching what
the rest of this codebase already does for background work.

Also deliberately NOT here: AI-provider-backed extraction enrichment.
EXTRACTION's per-unit work is deterministic candidate-term processing
(`companion_task_execution.extract_candidate_terms`, the same tokenizer
`ExtractVocabularyUseCase`'s fallback path already uses) — proving the
executor mechanism, not replacing the existing synchronous
`lensword.extract_vocabulary` MCP tool for AI-backed extraction. Wiring an
AI provider into this loop is future work, not silently claimed here.
"""
from __future__ import annotations

import logging
from typing import Callable

from sqlalchemy.orm import Session

from app.domain.services.companion_tasks import CompanionTask, CompanionTaskStatus, CompanionTaskType
from app.domain.value_objects import utcnow
from app.infrastructure.job_claims import claim
from app.infrastructure.repositories import SqlAlchemyCompanionTaskRepository

logger = logging.getLogger(__name__)

JOB_ID = "dispatch_companion_tasks"

# Bounds how many tasks one tick advances, so a burst of created tasks cannot
# make a single poll run unboundedly long. A task not reached this tick is
# simply picked up on the next one — nothing about correctness depends on
# finishing everything in one pass.
MAX_TASKS_PER_TICK = 10


class CompanionTaskExecutor:
    """Callable job body: `executor()` advances every runnable companion task."""

    def __init__(self, session_factory: Callable[[], Session], exclusive: bool = True):
        self.session_factory = session_factory
        # Off only in tests that assert single-instance execution behaviour
        # directly, mirroring every other dispatcher's identical parameter.
        self.exclusive = exclusive

    def __call__(self) -> None:
        db = self.session_factory()
        try:
            task_repo = SqlAlchemyCompanionTaskRepository(db)
            now = utcnow()
            for task in task_repo.list_runnable(now, limit=MAX_TASKS_PER_TICK):
                try:
                    if self.exclusive and not self._claim(db, task):
                        continue
                    self._run(db, task_repo, task)
                except Exception:  # noqa: BLE001 - one bad task must not stop the rest
                    logger.exception(
                        "companion task %s could not be advanced and was skipped", task.id
                    )
        finally:
            db.close()

    def _claim(self, db: Session, task: CompanionTask) -> bool:
        # Named by id and the row's own `updated_at`, so two instances
        # racing the same still-stale task collide on the same key and only
        # one proceeds; once that one persists a unit, `updated_at` moves and
        # the next tick's key is naturally different — exactly
        # `AcquisitionDispatcher._claim`'s shape.
        return claim(db, f"companion_task:{task.id}", task.updated_at.isoformat())

    def _run(self, db: Session, task_repo: SqlAlchemyCompanionTaskRepository, task: CompanionTask) -> None:
        now = utcnow()
        if task.expire_if_due(now):
            task_repo.update(task)
            db.commit()
            return
        if task.status is CompanionTaskStatus.PENDING:
            task.start(now)
            task_repo.update(task)
            db.commit()

        if task.task_type is CompanionTaskType.EXTRACTION:
            self._run_extraction(db, task_repo, task)
        # Other task types (PLAN_GENERATION, SESSION_PREPARATION) are not
        # picked up by `list_runnable` at all, so nothing reaches this
        # branch for them — see the module docstring for why PLAN_GENERATION
        # in particular is deliberately excluded.

    # -- EXTRACTION -----------------------------------------------------

    def _run_extraction(
        self, db: Session, task_repo: SqlAlchemyCompanionTaskRepository, task: CompanionTask
    ) -> None:
        candidates = list((task.input or {}).get("candidates") or [])
        if len(candidates) != task.total_units:
            task.fail("extraction task input does not match its declared total_units", utcnow())
            task_repo.update(task)
            db.commit()
            return
        items: list[str] = list((task.result or {}).get("items") or [])

        while task.completed_units < task.total_units:
            fresh = task_repo.get(task.user_id, task.session_id, task.id)
            if fresh is None or fresh.status is not CompanionTaskStatus.RUNNING:
                return  # cancelled, expired, or otherwise no longer runnable
            task = fresh
            index = task.completed_units
            items.append(candidates[index])
            now = utcnow()
            if index + 1 == task.total_units:
                task.complete({"partial": False, "items": items}, now)
            else:
                task.update_progress(index + 1, now)
                task.record_partial_result({"partial": True, "items": items}, now)
            task_repo.update(task)
            # Committed after every single unit, not once at the end: a
            # crash here loses at most this one unit of work, and the next
            # tick resumes from exactly what was last committed — see the
            # module docstring's "restart survival" paragraph.
            db.commit()
