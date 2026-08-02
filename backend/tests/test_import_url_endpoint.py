"""`POST /api/v1/imports/parse-url` (issue #145).

The endpoint's job is to turn a pasted page into import candidates. Its risk is
that the *server* makes a request the user chose, so most of what is checked
here is which URLs never reach the network.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.fixture()
def headers(auth_headers):
    return auth_headers()


def _post(client, headers, url: str):
    return client.post("/api/v1/imports/parse-url", json={"url": url}, headers=headers)


def test_a_fetched_page_becomes_import_candidates(client, headers):
    page = b"<html><body><p>El gato duerme. La casa es grande.</p></body></html>"

    with patch("app.api.routers.imports.fetch_document", return_value=(page, "page.html")):
        resp = _post(client, headers, "https://example.com/article")

    assert resp.status_code == 200, resp.text
    assert len(resp.json()["records"]) >= 1


def test_a_page_with_no_readable_text_is_reported(client, headers):
    with patch("app.api.routers.imports.fetch_document", return_value=(b"<html></html>", "p.html")):
        resp = _post(client, headers, "https://example.com/empty")

    assert resp.status_code == 422


def test_the_endpoint_requires_authentication(client):
    assert client.post("/api/v1/imports/parse-url", json={"url": "https://example.com"}).status_code == 401


# --- URLs that must never reach the network --------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/admin",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.1/",
        "http://[::1]/",
        "file:///etc/passwd",
        "ftp://example.com/x",
        "https://user:pass@example.com/",
        "http://example.com:6379/",
    ],
)
def test_a_dangerous_url_is_refused_without_being_fetched(client, headers, url):
    """The real fetch path runs — patching it out would remove the guard being
    tested. Every URL here is rejected on its shape alone, so DNS is never
    consulted either, which is what `resolve_addresses` asserts."""
    with patch("app.infrastructure.url_fetch.resolve_addresses") as resolve:
        resp = _post(client, headers, url)

    # 422 because the request itself is unacceptable — nothing upstream was
    # consulted, and nothing should have been.
    assert resp.status_code == 422, resp.text
    resolve.assert_not_called()


def test_the_refusal_does_not_name_the_address(client, headers):
    """A message that confirmed which internal host was unreachable would turn
    this endpoint into the scan the guard exists to prevent."""
    resp = _post(client, headers, "http://10.1.2.3/")

    assert "10.1.2.3" not in resp.text


def test_an_empty_url_is_rejected(client, headers):
    assert _post(client, headers, "   ").status_code == 422


# --- Upstream failure ------------------------------------------------------


def test_an_upstream_failure_is_a_502_not_a_500(client, headers):
    """The request was acceptable; the page was not. A 500 would say the fault
    was ours."""
    from app.infrastructure.url_fetch import UrlFetchFailed

    with patch(
        "app.api.routers.imports.fetch_document",
        side_effect=UrlFetchFailed("That page could not be fetched"),
    ):
        resp = _post(client, headers, "https://example.com/gone")

    assert resp.status_code == 502


def test_an_oversized_document_is_a_413(client, headers):
    from app.domain.services.documents import DocumentTooLargeError

    with patch("app.api.routers.imports.fetch_document", return_value=(b"x", "p.html")), patch(
        "app.api.routers.imports.parse_document",
        side_effect=DocumentTooLargeError("too large"),
    ):
        resp = _post(client, headers, "https://example.com/big")

    assert resp.status_code == 413
