"""Per-tenant isolation audit (ROADMAP 4.1, issue #19).

The issue asks for a review of every repository method confirming queries are
scoped by user. This is that review, written as a test rather than a document,
because a document records that the code was correct once and this records that
it still is.

## How scoping actually works here

Most repositories deliberately do *not* filter by `user_id`. `get_by_id` on
words, rooms, sessions, mnemonics, reminders, exercises and reports all fetch by
primary key alone, and ownership is enforced one layer up, in the use case,
which raises PermissionDeniedError. That is a legitimate design — the domain
owns the rule and the repository stays a dumb mapper — but it means a
repository-level review cannot conclude anything on its own. A method that
looks unscoped may be fine, and a caller that forgets the check is invisible
from the repository.

So the audit is done from the outside: for every endpoint that accepts a
resource identifier, a second account is denied. That is the property tenant
isolation actually needs, and unlike a static review it fails if a *future*
endpoint reaches a repository without the ownership check.

## Coverage

Every path-parameter endpoint under `/api/v1` that a non-admin can call is
listed in `CROSS_TENANT_CASES` below. Admin routes are excluded deliberately:
they are privilege-scoped rather than tenant-scoped, guarded by
`get_current_admin`, and are covered in test_admin_api.py.
"""
from __future__ import annotations

import pytest

# Anything in the 4xx family that denies the request is acceptable. The
# distinction between 403 (exists, not yours) and 404 (hidden entirely) is a
# per-endpoint disclosure judgement this audit does not try to standardise —
# what it must never see is a 2xx.
DENIED = {403, 404}


@pytest.fixture()
def two_accounts(client, auth_headers):
    owner = auth_headers(username="alex", email="alex@example.com")
    intruder = auth_headers(username="sam", email="sam@example.com")
    return owner, intruder


@pytest.fixture()
def owned(client, two_accounts, db_session):
    """A full resource graph belonging to the first account."""
    owner, _ = two_accounts
    _db = db_session

    group = client.post(
        "/api/v1/groups", json={"name": "Alex Group", "target_language": "Spanish"}, headers=owner
    ).json()
    word = client.post(
        f"/api/v1/groups/{group['id']}/words",
        json={"term": "Correr", "target_language": "Spanish", "translations": ["to run"]},
        headers=owner,
    ).json()
    room = client.post(
        "/api/v1/rooms",
        json={"group_id": group["id"], "name": "Alex Room"},
        headers=owner,
    ).json()
    client.post(
        f"/api/v1/rooms/{room['id']}/placements",
        json={"word_id": word["id"], "x_percent": 10, "y_percent": 20},
        headers=owner,
    )
    mnemonic = client.post(
        f"/api/v1/words/{word['id']}/mnemonics", json={"text": "runner"}, headers=owner
    ).json()
    session = client.post(
        "/api/v1/review/sessions", json={"mode": "standard"}, headers=owner
    ).json()
    exercise = client.post(
        "/api/v1/practice/exercises",
        json={"word_id": word["id"], "kind": "translation"},
        headers=owner,
    ).json()
    report = client.post("/api/v1/reports/weekly", headers=owner).json()
    # Seeded directly: notifications are produced by the scheduler firing a
    # reminder, which no endpoint triggers on demand.
    from app.domain.entities import DesktopNotification
    from app.infrastructure.repositories import SqlAlchemyDesktopNotificationRepository

    owner_id = client.get("/api/v1/auth/me", headers=owner).json()["id"]
    notification = SqlAlchemyDesktopNotificationRepository(_db).add(
        DesktopNotification(id=None, user_id=owner_id, message="5 words are due")
    )
    # Reminders have no creation endpoint yet (#56), so this is seeded too.
    from app.domain.entities import Reminder
    from app.domain.value_objects import Recurrence
    from app.infrastructure.repositories import SqlAlchemyReminderRepository

    reminder = SqlAlchemyReminderRepository(_db).add(
        Reminder(
            id=None, user_id=owner_id, group_id=group["id"],
            trigger_time="09:00", recurrence=Recurrence.DAILY,
        )
    )
    # Enough engagement history for a window recommendation to exist. Without
    # it the accept endpoint correctly answers 404 for its own owner, and the
    # owner-reachability check could not tell that apart from a broken route.
    from datetime import timedelta

    from app.domain.value_objects import NotificationAction, utcnow

    notifications_repo = SqlAlchemyDesktopNotificationRepository(_db)
    midnight = utcnow().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=30)
    for day in range(10):
        for hour, action in ((9, None), (20, NotificationAction.START_SESSION.value)):
            at = midnight + timedelta(days=day, hours=hour)
            notifications_repo.add(
                DesktopNotification(
                    id=None, user_id=owner_id, message="due",
                    created_at=at, delivered_at=at, action=action,
                )
            )
    # Seeded directly: generating a path needs an AI provider, which this
    # audit deliberately does not stand up.
    from app.domain.services.learning_path import MilestonePlan
    from app.infrastructure.repositories import SqlAlchemyLearningPathRepository

    learning_path = SqlAlchemyLearningPathRepository(_db).add(
        user_id=owner_id,
        goal="Order food in Spain",
        target_language="Spanish",
        milestones=[
            MilestonePlan(title="Greetings", description="", topic="greetings", target_word_count=5),
            MilestonePlan(title="Ordering", description="", topic="restaurant", target_word_count=5),
        ],
    )
    _db.commit()

    return {
        "group": group["id"],
        "word": word["id"],
        "room": room["id"],
        "mnemonic": mnemonic["id"],
        # Starting a session returns `session_id`, not `id`, unlike every other
        # resource here.
        "session": session["session_id"],
        "exercise": exercise["id"],
        "report": report["id"],
        "notification": notification.id,
        "reminder": reminder.id,
        "path": learning_path.id,
    }


def _case(method, path, json_body=None):
    return pytest.param(method, path, json_body, id=f"{method} {path}")


# (method, path template, body). Path templates are formatted against `owned`.
CROSS_TENANT_CASES = [
    # Groups
    _case("GET", "/api/v1/groups/{group}/words"),
    _case("POST", "/api/v1/groups/{group}/words",
          {"term": "x", "target_language": "Spanish", "translations": ["y"]}),
    _case("PATCH", "/api/v1/groups/{group}", {"name": "stolen"}),
    _case("DELETE", "/api/v1/groups/{group}"),
    # Words
    _case("GET", "/api/v1/words/{word}"),
    _case("PUT", "/api/v1/words/{word}",
          {"term": "stolen", "target_language": "Spanish", "translations": ["y"]}),
    _case("PATCH", "/api/v1/words/{word}/associations", {"synonyms": ["stolen"]}),
    _case("DELETE", "/api/v1/words/{word}"),
    # Knowledge graph (#143). Read-only, but a graph that answered for
    # someone else's word would disclose both that it exists and what it
    # relates to.
    _case("GET", "/api/v1/words/{word}/prerequisites"),
    _case("GET", "/api/v1/words/{word}/related"),
    # AI provenance (#140). The history of someone else's card describes
    # their vocabulary, and verification is a claim about their data.
    _case("GET", "/api/v1/words/{word}/history"),
    _case("POST", "/api/v1/words/{word}/verify"),
    _case("DELETE", "/api/v1/words/{word}/verify"),
    # Learning paths (#137). A goal is a personal thing to leak the
    # existence of.
    _case("GET", "/api/v1/learning-paths/{path}"),
    _case("DELETE", "/api/v1/learning-paths/{path}"),
    # Rooms
    _case("GET", "/api/v1/rooms/{room}"),
    _case("GET", "/api/v1/rooms/{room}/words"),
    _case("POST", "/api/v1/rooms/{room}/placements",
          {"word_id": 1, "x_percent": 5, "y_percent": 5}),
    _case("DELETE", "/api/v1/rooms/{room}/placements/{word}"),
    _case("DELETE", "/api/v1/rooms/{room}"),
    # MnemoLab
    _case("GET", "/api/v1/words/{word}/mnemonics"),
    _case("POST", "/api/v1/words/{word}/mnemonics", {"text": "intruding"}),
    _case("POST", "/api/v1/words/{word}/mnemonics/{mnemonic}/vote", {"upvote": True}),
    _case("POST", "/api/v1/words/{word}/mnemonics/suggest"),
    # Review. Both bodies must be *valid*: a 422 is rejected by this audit
    # (see DENIED), because a request that fails schema validation never
    # reaches the ownership check and so proves nothing about isolation.
    _case("POST", "/api/v1/review/sessions/{session}/answers",
          {"word_id": 1, "outcome": "correct", "response_time_ms": 100}),
    _case("POST", "/api/v1/review/sessions/{session}/complete",
          {"new_words_learned_count": 0}),
    # Adaptive practice
    _case("POST", "/api/v1/practice/exercises/{exercise}/answer", {"response": "guess"}),
    _case("POST", "/api/v1/practice/exercises", {"word_id": 1, "kind": "translation"}),
    _case("POST", "/api/v1/practice/pronunciation-feedback", {"word_id": 1, "transcript": "correr"}),
    _case("POST", "/api/v1/practice/writing-correction", {"word_id": 1, "text": "yo correr"}),
    # Desktop notifications. Acting on one is as sensitive as reading it —
    # "skip today" on someone else's reminder would suppress their prompts.
    _case("POST", "/api/v1/desktop-notifications/{notification}/action",
          {"action": "start_session"}),
    # Reminder windows. Accepting one on someone else's reminder would move
    # when they are interrupted.
    _case("GET", "/api/v1/reminders/{reminder}/window-recommendation"),
    _case("POST", "/api/v1/reminders/{reminder}/window-recommendation/accept", {"hour": 20}),
    # Reports
    _case("GET", "/api/v1/reports/weekly/{report}"),
    _case("POST", "/api/v1/reports/weekly/{report}/narration"),
]


@pytest.mark.parametrize("method,path_template,json_body", CROSS_TENANT_CASES)
def test_a_second_account_is_denied(client, two_accounts, owned, method, path_template, json_body):
    _, intruder = two_accounts

    path = path_template.format(**owned)
    # Bodies that reference a resource by id carry a placeholder 1; substitute
    # the real owned id so the request is denied for ownership rather than
    # rejected for naming something that does not exist.
    body = dict(json_body) if json_body else None
    if body and "word_id" in body:
        body["word_id"] = owned["word"]

    response = client.request(method, path, json=body, headers=intruder)

    assert response.status_code in DENIED, (
        f"{method} {path} returned {response.status_code} to a second account; "
        f"body={response.text[:300]}"
    )


@pytest.mark.parametrize("method,path_template,json_body", CROSS_TENANT_CASES)
def test_the_same_endpoints_are_reachable_by_their_owner(
    client, two_accounts, owned, method, path_template, json_body
):
    """The denial test above would pass just as well against endpoints that are
    broken for everyone, which would make the audit meaningless. This asserts
    the same requests succeed for the account that owns the data, so a 403 in
    the test above is really about tenancy."""
    owner, _ = two_accounts

    path = path_template.format(**owned)
    body = dict(json_body) if json_body else None
    if body and "word_id" in body:
        body["word_id"] = owned["word"]

    response = client.request(method, path, json=body, headers=owner)

    assert response.status_code not in DENIED, (
        f"{method} {path} denied its own owner with {response.status_code}; "
        f"body={response.text[:300]}"
    )


# --- Listing endpoints -----------------------------------------------------
#
# These take no identifier, so they cannot be got wrong by passing someone
# else's id — they are wrong only if the query forgets its user filter, which
# returns another account's rows with no error at all.


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/groups",
        "/api/v1/rooms",
        "/api/v1/reports/weekly",
    ],
)
def test_collection_endpoints_return_nothing_belonging_to_another_account(
    client, two_accounts, owned, path
):
    _, intruder = two_accounts

    response = client.get(path, headers=intruder)

    assert response.status_code == 200, response.text
    assert response.json() == [], f"{path} leaked rows to a second account"


def test_due_words_are_scoped_to_the_requesting_account(client, two_accounts, owned):
    """`list_due_for_user` joins through groups to reach words, which is the
    kind of query where a missing join condition silently widens the result."""
    _, intruder = two_accounts

    started = client.post("/api/v1/review/sessions", json={"mode": "standard"}, headers=intruder)

    # 409 is the expected outcome and is itself the proof: the endpoint refuses
    # to start a session when the account has no due words, and this account
    # owns none — despite another account's word being due right now.
    assert started.status_code == 409, (
        f"a second account started a review session ({started.status_code}); "
        f"body={started.text[:300]}"
    )


def test_the_profile_overview_counts_only_the_requesting_account(client, two_accounts, owned):
    _, intruder = two_accounts

    overview = client.get("/api/v1/profile", headers=intruder).json()

    assert overview["user"]["total_words_learned"] == 0


# --- Keeping the audit honest ----------------------------------------------


# Routes excluded from the coverage check below, each for a stated reason.
# Anything not listed here and not covered by CROSS_TENANT_CASES fails the
# test, so adding an endpoint forces a decision rather than silently shrinking
# the audit.
_EXEMPT_PREFIXES = (
    # Privilege-scoped, not tenant-scoped: guarded by get_current_admin and
    # covered in test_admin_api.py.
    "/api/v1/admin",
    # Machine-to-machine surface with its own grant/scope model and its own
    # tests (test_mcp_security.py, test_mcp_policy.py).
    "/api/v1/mcp",
)


def test_every_identifier_taking_endpoint_is_covered_by_this_audit():
    """Fail when a new endpoint takes a resource id without being audited.

    Without this, the audit passes forever while covering less and less of the
    application — the failure mode of every checklist that is written once.
    """
    from app.main import app as fastapi_app

    # Read the routes from the OpenAPI schema rather than by walking
    # `app.routes`: this FastAPI version keeps included routers as wrapper
    # objects instead of flattening them, so the attribute walk silently finds
    # nothing — which would make this check pass while testing zero routes.
    paths = fastapi_app.openapi()["paths"]

    # CROSS_TENANT_CASES names its placeholders after the fixture ({group});
    # the routes name them after the parameter ({group_id}). Compare on the
    # shape of the path rather than on placeholder names.
    def _shape(path: str) -> str:
        out, depth = [], 0
        for char in path:
            if char == "{":
                depth += 1
                if depth == 1:
                    out.append("{}")
            elif char == "}":
                depth -= 1
            elif depth == 0:
                out.append(char)
        return "".join(out)

    audited_shapes = {_shape(case.values[1]) for case in CROSS_TENANT_CASES}

    uncovered = {
        f"{method.upper()} {path}"
        for path, operations in paths.items()
        for method in operations
        if "{" in path
        and path.startswith("/api/v1")
        and not path.startswith(_EXEMPT_PREFIXES)
        and _shape(path) not in audited_shapes
    }

    assert not uncovered, (
        "these endpoints accept a resource identifier but are not in "
        f"CROSS_TENANT_CASES: {sorted(uncovered)}. Add a case, or add the route "
        "to _EXEMPT_PREFIXES with the reason it is not tenant-scoped."
    )


def test_the_coverage_check_actually_finds_routes():
    """Guards the guard. `test_every_identifier_taking_endpoint_is_covered_by
    _this_audit` passes both when everything is covered and when it enumerates
    nothing at all, and those two outcomes look identical from the outside."""
    from app.main import app as fastapi_app

    identifier_routes = [
        path
        for path in fastapi_app.openapi()["paths"]
        if "{" in path and path.startswith("/api/v1") and not path.startswith(_EXEMPT_PREFIXES)
    ]

    assert len(identifier_routes) >= 15, identifier_routes
