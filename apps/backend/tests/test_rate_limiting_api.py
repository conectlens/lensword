"""Rate limiting wired onto real endpoints (issue #163).

The limiter itself (window sliding, isolation, eviction) is covered in
test_rate_limiter.py. This file is about the wiring: which endpoints enforce
which budget, that a 429 carries Retry-After, and that one caller running out
of budget does not affect another.

Defaults come from Settings (apps/backend/app/config.py) — auth: 10 attempts /
300s per IP; AI generation: 15 / 60s per account; import URL-fetch and
upload: 20 / 60s each per account. Tests exhaust the real default rather than
overriding it, so a change to the default is what it looks like to break one
of these.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app


@pytest.fixture()
def headers(auth_headers):
    return auth_headers()


# --- Auth login: keyed by IP, no account exists yet -------------------------


def test_repeated_failed_logins_are_eventually_rate_limited(client):
    limit = get_settings().rate_limit_auth_attempts
    client.post(
        "/api/v1/auth/register",
        json={"username": "alex", "email": "alex@example.com", "password": "supersecret1"},
    )
    payload = {"email": "alex@example.com", "password": "wrongpassword"}

    responses = [client.post("/api/v1/auth/login", json=payload) for _ in range(limit + 1)]

    assert [r.status_code for r in responses[:limit]] == [401] * limit
    assert responses[limit].status_code == 429
    assert "Retry-After" in responses[limit].headers


def test_a_correct_password_still_works_from_a_different_ip(client):
    """A limiter that locks the real user out is a denial of service built by
    the fix meant to prevent one."""
    limit = get_settings().rate_limit_auth_attempts
    client.post(
        "/api/v1/auth/register",
        json={"username": "alex", "email": "alex@example.com", "password": "supersecret1"},
    )
    bad = {"email": "alex@example.com", "password": "wrongpassword"}
    for _ in range(limit + 1):
        client.post("/api/v1/auth/login", json=bad)

    other_ip = TestClient(app, client=("203.0.113.5", 12345))
    good = {"email": "alex@example.com", "password": "supersecret1"}
    resp = other_ip.post("/api/v1/auth/login", json=good)

    assert resp.status_code == 200


# --- AI generation: keyed by account, shared across the four endpoints ------


def test_repeated_ai_calls_from_one_account_are_rate_limited(client, headers):
    limit = get_settings().rate_limit_ai_requests
    payload = {"term": "gato", "source_language": "Spanish", "target_language": "English"}

    responses = [client.post("/api/v1/ai/enrich", json=payload, headers=headers) for _ in range(limit + 1)]

    # No AI provider is configured in tests, so an allowed call 503s rather
    # than 200s — what matters here is that the limit'th-plus-one call is
    # rejected before it gets that far.
    assert all(r.status_code != 429 for r in responses[:limit])
    assert responses[limit].status_code == 429
    assert "Retry-After" in responses[limit].headers


def test_one_accounts_ai_budget_does_not_affect_another(client, auth_headers):
    """A global limiter would let one user deny the AI endpoints to everyone."""
    limit = get_settings().rate_limit_ai_requests
    alex = auth_headers(username="alex", email="alex@example.com")
    sam = auth_headers(username="sam", email="sam@example.com")
    payload = {"term": "gato", "source_language": "Spanish", "target_language": "English"}

    for _ in range(limit + 1):
        client.post("/api/v1/ai/enrich", json=payload, headers=alex)
    resp = client.post("/api/v1/ai/enrich", json=payload, headers=sam)

    assert resp.status_code != 429


def test_ai_budget_is_shared_across_the_four_ai_endpoints(client, headers):
    """enrich, converse, evaluate-scenario and generate-path all occupy the
    same local model, so they draw from one budget rather than each getting
    its own that a caller could add together."""
    limit = get_settings().rate_limit_ai_requests
    enrich_payload = {"term": "gato", "source_language": "Spanish", "target_language": "English"}

    for _ in range(limit):
        client.post("/api/v1/ai/enrich", json=enrich_payload, headers=headers)
    resp = client.post(
        "/api/v1/learning-paths/generate",
        json={"goal": "order food at a restaurant", "target_language": "Spanish"},
        headers=headers,
    )

    assert resp.status_code == 429


# --- Outbound URL fetch: keyed by account ------------------------------------


def test_repeated_url_imports_from_one_account_are_rate_limited(client, headers):
    limit = get_settings().rate_limit_fetch_requests
    page = b"<html><body><p>El gato duerme. La casa es grande.</p></body></html>"

    with patch("app.api.routers.imports.fetch_document", return_value=(page, "page.html")):
        responses = [
            client.post("/api/v1/imports/parse-url", json={"url": "https://example.com/a"}, headers=headers)
            for _ in range(limit + 1)
        ]

    assert all(r.status_code != 429 for r in responses[:limit])
    assert responses[limit].status_code == 429
    assert "Retry-After" in responses[limit].headers


# --- Upload: keyed by account, independent of the fetch budget --------------


def test_repeated_uploads_from_one_account_are_rate_limited(client, headers):
    limit = get_settings().rate_limit_upload_requests

    responses = [
        client.post(
            "/api/v1/imports/parse",
            files={"file": ("words.txt", "merhaba\n", "text/plain")},
            headers=headers,
        )
        for _ in range(limit + 1)
    ]

    assert all(r.status_code != 429 for r in responses[:limit])
    assert responses[limit].status_code == 429


def test_the_upload_and_fetch_budgets_are_independent(client, headers):
    fetch_limit = get_settings().rate_limit_fetch_requests
    page = b"<html><body><p>El gato duerme.</p></body></html>"

    with patch("app.api.routers.imports.fetch_document", return_value=(page, "page.html")):
        for _ in range(fetch_limit + 1):
            client.post("/api/v1/imports/parse-url", json={"url": "https://example.com/a"}, headers=headers)

    resp = client.post(
        "/api/v1/imports/parse",
        files={"file": ("words.txt", "merhaba\n", "text/plain")},
        headers=headers,
    )

    assert resp.status_code != 429
