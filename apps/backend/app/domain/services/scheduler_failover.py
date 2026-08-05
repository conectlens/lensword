"""One reminder intent, two possible executors, never two deliveries (#87).

A reminder can be fired by the backend scheduler or, when the backend is
unreachable, by a scheduler running inside the desktop shell. The hazard is
obvious and the fix is not: both know about the reminder, so both will fire it
unless something decides which one owns a given occurrence.

The rule here is *ownership follows reachability, and the loser defers*:

- **Backend available** — the backend owns every occurrence. The shell
  registers nothing, because a local copy would be a duplicate waiting for a
  network blip to become real.
- **Degraded** — reachable but refusing work. Still the backend's, because it
  will catch up; a shell that took over during a deploy would double-deliver
  the moment the deploy finished.
- **Offline** — the shell owns occurrences it can see, because nobody else
  will fire them.
- **Reconnect** — the interesting one. The shell reports what it delivered
  while offline, the backend records those occurrences as already claimed, and
  neither re-fires them.

That last step is why this reuses the claim key from #20 rather than inventing
a second identity: a locally-delivered occurrence and a backend-delivered one
have to be the *same* claim, or reconciliation cannot recognise them as the
same firing.

The revision is what makes an edit converge. A reminder edited offline and
also edited on the server has two versions; the higher revision wins, and a
firing computed from a superseded revision is discarded rather than delivered
at the old time.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class BackendState(str, Enum):
    """What the shell currently believes about the server.

    Reported rather than inferred, for the same reason as ConnectivityMode in
    sync_health: a server reachable from the data centre says nothing about a
    laptop on a train.
    """

    AVAILABLE = "available"
    # Reachable, but not accepting work — a deploy, a rate limit, an expired
    # token. Deliberately not "offline": the backend will catch up on its own,
    # and taking over would produce a duplicate when it does.
    DEGRADED = "degraded"
    OFFLINE = "offline"


class Executor(str, Enum):
    BACKEND = "backend"
    LOCAL = "local"
    # Nobody fires it. Not an error state — it is the correct answer for a
    # reminder that is disabled or whose revision has been superseded.
    NONE = "none"


@dataclass(frozen=True)
class ReminderIntent:
    """One reminder, in the form both executors agree on.

    `reminder_id` is the stable identity and `revision` is the authority. Two
    devices holding different revisions of the same intent are holding the
    same reminder, and the higher revision is the real one.
    """

    reminder_id: int
    revision: int
    trigger_time: str
    time_zone: str
    enabled: bool = True

    def supersedes(self, other: "ReminderIntent") -> bool:
        """Whether this is the newer version of the same reminder.

        Compares revisions rather than timestamps: two devices' clocks
        disagree, and an edit made on a laptop whose clock is slow must not
        lose to an older edit made on a phone whose clock is fast.
        """
        if self.reminder_id != other.reminder_id:
            return False
        return self.revision > other.revision


@dataclass(frozen=True)
class DeliveryReport:
    """A firing the shell carried out while the backend was unreachable.

    The occurrence key is the same one the backend claims with (#20), which is
    the whole reason reconciliation works: the two executors are naming the
    same firing rather than describing it in their own terms.
    """

    reminder_id: int
    occurrence_key: str
    delivered_at: datetime
    revision: int


class FailoverPolicy:
    """Stateless. Decides who owns an occurrence, and what to do on reconnect."""

    @staticmethod
    def executor_for(state: BackendState, intent: ReminderIntent) -> Executor:
        if not intent.enabled:
            return Executor.NONE
        if state is BackendState.OFFLINE:
            return Executor.LOCAL
        # AVAILABLE and DEGRADED both stay with the backend. Degraded is the
        # one worth stating: it looks like a good moment to take over, and
        # taking over is exactly what produces a duplicate once the deploy or
        # the rate limit ends.
        return Executor.BACKEND

    @staticmethod
    def should_register_locally(state: BackendState, intent: ReminderIntent) -> bool:
        """Whether the shell should hold a local job for this reminder.

        True whenever the shell *might* become the executor — which includes
        while the backend is available, because a job registered only at the
        moment connectivity drops would miss any occurrence during the gap.
        Registration is not delivery; ownership is still decided at fire time.
        """
        return intent.enabled

    @staticmethod
    def reconcile(
        reports: list[DeliveryReport], known_intents: dict[int, ReminderIntent]
    ) -> tuple[list[DeliveryReport], list[DeliveryReport]]:
        """Split reports into those to record as delivered and those to discard.

        A report is discarded when it was computed from a revision the server
        has since superseded: the user moved the reminder to 18:00 on another
        device, and this one fired the old 09:00 occurrence. Recording it would
        suppress a firing that should still happen, which is worse than the
        duplicate it was trying to prevent.

        Returns `(accepted, superseded)` rather than raising, because a
        superseded report is expected during normal use and the caller needs
        both lists — one to claim, one to tell the user about.
        """
        accepted: list[DeliveryReport] = []
        superseded: list[DeliveryReport] = []
        for report in reports:
            intent = known_intents.get(report.reminder_id)
            if intent is None:
                # The reminder was deleted while the shell was offline. The
                # delivery happened and cannot be unhappened, but there is
                # nothing left to claim it against.
                superseded.append(report)
                continue
            if report.revision < intent.revision:
                superseded.append(report)
                continue
            accepted.append(report)
        return accepted, superseded

    @staticmethod
    def duplicate_keys(reports: list[DeliveryReport]) -> set[str]:
        """Claim keys the backend must not fire again after reconnect.

        Scoped by reminder as well as occurrence, since two reminders can share
        an occurrence key — both fire daily at 09:00 — and suppressing by
        occurrence alone would silence one of them.
        """
        return {f"reminder:{r.reminder_id}:{r.occurrence_key}" for r in reports}
