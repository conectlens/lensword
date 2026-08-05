"""Cloud/local scheduler failover (issue #87).

The issue's verification: a simulated outage spanning a reminder fires exactly
once, reconnect does not replay acknowledged jobs, and edits made offline
converge to the latest valid revision. All three are decided by the policy
here, which is why it takes states and revisions rather than a scheduler.

The Rust-side local scheduler that would *act* on these decisions is not
tested — it cannot be run in this environment. What is tested is every choice
it would be asked to make.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.domain.services.scheduler_failover import (
    BackendState,
    DeliveryReport,
    Executor,
    FailoverPolicy,
    ReminderIntent,
)

NOW = datetime(2026, 8, 2, 9, 0)


def _intent(reminder_id: int = 1, revision: int = 1, enabled: bool = True) -> ReminderIntent:
    return ReminderIntent(
        reminder_id=reminder_id,
        revision=revision,
        trigger_time="09:00",
        time_zone="Europe/Istanbul",
        enabled=enabled,
    )


def _report(reminder_id: int = 1, revision: int = 1, key: str = "2026-08-02T09:00:00"):
    return DeliveryReport(
        reminder_id=reminder_id, occurrence_key=key, delivered_at=NOW, revision=revision
    )


# --- Who owns an occurrence ------------------------------------------------


def test_the_backend_owns_occurrences_while_it_is_reachable():
    assert FailoverPolicy.executor_for(BackendState.AVAILABLE, _intent()) is Executor.BACKEND


def test_the_shell_takes_over_only_when_the_backend_is_unreachable():
    assert FailoverPolicy.executor_for(BackendState.OFFLINE, _intent()) is Executor.LOCAL


def test_a_degraded_backend_keeps_ownership():
    """The case worth stating. A deploy or a rate limit looks like a good
    moment to take over, and taking over is exactly what produces a duplicate
    once it ends."""
    assert FailoverPolicy.executor_for(BackendState.DEGRADED, _intent()) is Executor.BACKEND


@pytest.mark.parametrize("state", list(BackendState))
def test_a_disabled_reminder_is_fired_by_nobody(state):
    assert FailoverPolicy.executor_for(state, _intent(enabled=False)) is Executor.NONE


def test_exactly_one_executor_is_chosen_in_every_state():
    """The property the whole design exists for: never two, and never — for an
    enabled reminder — zero."""
    for state in BackendState:
        assert FailoverPolicy.executor_for(state, _intent()) in {Executor.BACKEND, Executor.LOCAL}


# --- Local registration ----------------------------------------------------


def test_the_shell_registers_jobs_even_while_the_backend_is_available():
    """A job registered only at the moment connectivity drops would miss any
    occurrence during the gap. Registration is not delivery — ownership is
    still decided at fire time."""
    assert FailoverPolicy.should_register_locally(BackendState.AVAILABLE, _intent()) is True


def test_a_disabled_reminder_is_not_registered_locally():
    assert FailoverPolicy.should_register_locally(BackendState.OFFLINE, _intent(enabled=False)) is False


# --- Reconnect: the outage spanning a reminder -----------------------------


def test_a_delivery_made_offline_is_accepted_on_reconnect():
    """The outage case from the issue's verification. The shell fired it, the
    backend records the claim, and nobody fires it again."""
    accepted, superseded = FailoverPolicy.reconcile([_report()], {1: _intent()})

    assert len(accepted) == 1 and superseded == []


def test_reconnect_does_not_replay_an_acknowledged_firing():
    """The claim keys handed back are exactly what the backend must refuse to
    fire again."""
    keys = FailoverPolicy.duplicate_keys([_report(key="2026-08-02T09:00:00")])

    assert keys == {"reminder:1:2026-08-02T09:00:00"}


def test_two_reminders_sharing_an_occurrence_are_suppressed_separately():
    """Both fire daily at 09:00, so the occurrence key alone is ambiguous.
    Suppressing by occurrence would silence one of them."""
    keys = FailoverPolicy.duplicate_keys([_report(reminder_id=1), _report(reminder_id=2)])

    assert len(keys) == 2


# --- Convergence on the latest revision ------------------------------------


def test_a_delivery_from_a_superseded_revision_is_discarded():
    """The user moved the reminder to 18:00 on another device and this one
    fired the old 09:00 occurrence. Recording it would suppress a firing that
    should still happen — worse than the duplicate it was avoiding."""
    accepted, superseded = FailoverPolicy.reconcile(
        [_report(revision=1)], {1: _intent(revision=2)}
    )

    assert accepted == []
    assert len(superseded) == 1


def test_a_delivery_from_the_current_revision_is_accepted():
    accepted, _ = FailoverPolicy.reconcile([_report(revision=2)], {1: _intent(revision=2)})

    assert len(accepted) == 1


def test_a_delivery_from_a_newer_revision_than_the_server_knows_is_accepted():
    """The shell edited the reminder offline and fired the edited version. The
    edit will arrive through sync; discarding the delivery would lose a real
    notification the user already saw."""
    accepted, _ = FailoverPolicy.reconcile([_report(revision=5)], {1: _intent(revision=2)})

    assert len(accepted) == 1


def test_a_delivery_for_a_deleted_reminder_is_reported_not_claimed():
    """It happened and cannot be unhappened, but there is nothing left to
    claim it against."""
    accepted, superseded = FailoverPolicy.reconcile([_report()], {})

    assert accepted == []
    assert len(superseded) == 1


def test_reconcile_returns_both_lists_rather_than_raising():
    """A superseded report is expected during normal use, and the caller needs
    both — one set to claim, one to tell the user about."""
    accepted, superseded = FailoverPolicy.reconcile(
        [_report(reminder_id=1, revision=1), _report(reminder_id=2, revision=3)],
        {1: _intent(reminder_id=1, revision=9), 2: _intent(reminder_id=2, revision=3)},
    )

    assert [r.reminder_id for r in accepted] == [2]
    assert [r.reminder_id for r in superseded] == [1]


def test_an_empty_reconnect_is_harmless():
    assert FailoverPolicy.reconcile([], {}) == ([], [])


# --- The intent model ------------------------------------------------------


def test_a_higher_revision_supersedes_a_lower_one():
    assert _intent(revision=3).supersedes(_intent(revision=2)) is True
    assert _intent(revision=2).supersedes(_intent(revision=3)) is False


def test_an_equal_revision_does_not_supersede():
    """Otherwise two devices holding the same version would each think theirs
    was newer and overwrite the other in turn."""
    assert _intent(revision=2).supersedes(_intent(revision=2)) is False


def test_revisions_of_different_reminders_are_not_comparable():
    assert _intent(reminder_id=1, revision=9).supersedes(_intent(reminder_id=2, revision=1)) is False


def test_convergence_does_not_depend_on_clocks():
    """Two devices' clocks disagree. An edit made on a laptop whose clock is
    slow must not lose to an older edit made on a phone whose clock is fast,
    which is why this compares revisions and not timestamps."""
    slow_clock_but_newer = _intent(revision=5)
    fast_clock_but_older = _intent(revision=4)

    assert slow_clock_but_newer.supersedes(fast_clock_but_older) is True


def test_the_intent_carries_the_zone_the_schedule_is_evaluated_in():
    """Both executors have to agree on when 09:00 is, and 'the machine's local
    time' is not an agreement — the phone and the server are in different
    places."""
    assert _intent().time_zone == "Europe/Istanbul"


def test_a_reminder_edited_offline_and_on_the_server_converges_upward():
    """End to end: whichever revision is higher is the one both sides end up
    holding, regardless of which device made it."""
    offline_edit = _intent(revision=4)
    server_edit = _intent(revision=6)

    winner = server_edit if server_edit.supersedes(offline_edit) else offline_edit

    assert winner.revision == 6


def test_a_firing_computed_from_a_stale_revision_is_not_delivered_late():
    """The composed case: an offline delivery from revision 1 arriving after
    the server moved to revision 2 is discarded, and its claim key is
    therefore never registered — so the current schedule still fires."""
    accepted, superseded = FailoverPolicy.reconcile([_report(revision=1)], {1: _intent(revision=2)})

    assert FailoverPolicy.duplicate_keys(accepted) == set()
    assert len(superseded) == 1


def test_delivery_reports_carry_the_time_they_happened():
    """Reconciliation is about which occurrence fired, but a user asking why
    they got a notification at 3am needs the actual instant."""
    assert _report().delivered_at == NOW
    assert _report().delivered_at != NOW + timedelta(hours=1)


# --- The revision is the server's to assign --------------------------------


def test_updating_a_reminder_bumps_its_revision(db_session):
    """Bumped by the repository rather than taken from the caller: a client
    that could set the revision could claim to be newer than it is and win
    every convergence."""
    from app.domain.entities import Group, Reminder, User
    from app.domain.value_objects import Recurrence, SupportedLanguage, UserRole
    from app.infrastructure.repositories import (
        SqlAlchemyGroupRepository,
        SqlAlchemyReminderRepository,
        SqlAlchemyUserRepository,
    )

    user = SqlAlchemyUserRepository(db_session).add(
        User(id=None, username="a", email="a@b.c", hashed_password="x", role=UserRole.USER)
    )
    group = SqlAlchemyGroupRepository(db_session).add(
        Group(id=None, owner_id=user.id, name="G", target_language=SupportedLanguage.SPANISH)
    )
    repo = SqlAlchemyReminderRepository(db_session)
    stored = repo.add(
        Reminder(
            id=None, user_id=user.id, group_id=group.id,
            trigger_time="09:00", recurrence=Recurrence.DAILY,
        )
    )
    assert stored.revision == 1

    stored.trigger_time = "18:00"
    updated = repo.update(stored)

    assert updated.revision == 2


def test_a_client_supplied_revision_is_ignored(db_session):
    from app.domain.entities import Group, Reminder, User
    from app.domain.value_objects import Recurrence, SupportedLanguage, UserRole
    from app.infrastructure.repositories import (
        SqlAlchemyGroupRepository,
        SqlAlchemyReminderRepository,
        SqlAlchemyUserRepository,
    )

    user = SqlAlchemyUserRepository(db_session).add(
        User(id=None, username="a", email="a@b.c", hashed_password="x", role=UserRole.USER)
    )
    group = SqlAlchemyGroupRepository(db_session).add(
        Group(id=None, owner_id=user.id, name="G", target_language=SupportedLanguage.SPANISH)
    )
    repo = SqlAlchemyReminderRepository(db_session)
    stored = repo.add(
        Reminder(
            id=None, user_id=user.id, group_id=group.id,
            trigger_time="09:00", recurrence=Recurrence.DAILY,
        )
    )

    stored.revision = 9999
    updated = repo.update(stored)

    assert updated.revision == 2
