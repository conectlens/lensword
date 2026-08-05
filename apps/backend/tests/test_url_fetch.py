"""Fetching a user-supplied URL (issue #145).

Driven through an httpx mock transport, so every redirect and size case runs
without a network. The redirect tests matter most: a check applied only to the
URL the user typed is defeated by a 302.
"""
from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

from app.domain.services.url_safety import UrlRejected
from app.infrastructure.url_fetch import (
    MAX_FETCH_BYTES,
    UrlFetchFailed,
    fetch_document,
)

PUBLIC = ["93.184.216.34"]


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)


@pytest.fixture()
def public_dns():
    """Every hostname resolves to public space unless a test says otherwise."""
    with patch("app.infrastructure.url_fetch.resolve_addresses", return_value=PUBLIC) as mock:
        yield mock


# --- The happy path --------------------------------------------------------


def test_a_page_is_fetched_and_returned(public_dns):
    def handler(request):
        return httpx.Response(200, text="Hello world", headers={"content-type": "text/html"})

    body, filename = fetch_document("https://example.com/article", client=_client(handler))

    assert body == b"Hello world"
    assert filename.endswith(".html")


def test_a_url_ending_in_an_extension_keeps_it_as_the_filename_hint(public_dns):
    """The parser registry falls back on the filename, so a URL ending .pdf
    should reach the PDF parser the same way an upload would."""
    def handler(request):
        return httpx.Response(200, content=b"%PDF-1.4", headers={"content-type": "application/pdf"})

    _, filename = fetch_document("https://example.com/paper.pdf", client=_client(handler))

    assert filename == "paper.pdf"


def test_the_filename_is_never_taken_from_content_disposition(public_dns):
    """Attacker-controlled, and it would let a remote server choose which
    parser runs."""
    def handler(request):
        return httpx.Response(
            200,
            text="x",
            headers={
                "content-type": "text/html",
                "content-disposition": 'attachment; filename="evil.pdf"',
            },
        )

    _, filename = fetch_document("https://example.com/page", client=_client(handler))

    assert "evil" not in filename


# --- Redirects: the case a naive check misses ------------------------------


def test_a_redirect_to_a_private_address_is_refused(public_dns):
    """The oldest way past an SSRF check: validate the typed URL, then 302 the
    client to the metadata endpoint."""
    def handler(request):
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data/"})

    with pytest.raises(UrlRejected):
        fetch_document("https://example.com/start", client=_client(handler))


def test_a_redirect_to_another_scheme_is_refused(public_dns):
    def handler(request):
        return httpx.Response(302, headers={"location": "file:///etc/passwd"})

    with pytest.raises(UrlRejected):
        fetch_document("https://example.com/start", client=_client(handler))


def test_a_redirect_to_a_host_resolving_privately_is_refused():
    """The redirect target is resolved again rather than trusted for being a
    hostname rather than a literal."""
    def handler(request):
        if request.url.host == "example.com":
            return httpx.Response(302, headers={"location": "https://internal.example/"})
        return httpx.Response(200, text="secret")

    def resolve(hostname):
        return ["127.0.0.1"] if hostname == "internal.example" else PUBLIC

    with patch("app.infrastructure.url_fetch.resolve_addresses", side_effect=resolve):
        with pytest.raises(UrlRejected):
            fetch_document("https://example.com/start", client=_client(handler))


def test_an_ordinary_redirect_is_followed(public_dns):
    def handler(request):
        if request.url.path == "/start":
            return httpx.Response(301, headers={"location": "https://example.com/final"})
        return httpx.Response(200, text="arrived", headers={"content-type": "text/html"})

    body, _ = fetch_document("https://example.com/start", client=_client(handler))

    assert body == b"arrived"


def test_a_relative_redirect_is_resolved_against_the_current_url(public_dns):
    def handler(request):
        if request.url.path == "/start":
            return httpx.Response(302, headers={"location": "/final"})
        return httpx.Response(200, text="arrived", headers={"content-type": "text/html"})

    body, _ = fetch_document("https://example.com/start", client=_client(handler))

    assert body == b"arrived"


def test_a_redirect_loop_ends_rather_than_spinning(public_dns):
    def handler(request):
        return httpx.Response(302, headers={"location": "https://example.com/loop"})

    with pytest.raises(UrlFetchFailed):
        fetch_document("https://example.com/loop", client=_client(handler))


def test_a_redirect_with_no_location_is_a_failure_not_a_crash(public_dns):
    def handler(request):
        return httpx.Response(302)

    with pytest.raises(UrlFetchFailed):
        fetch_document("https://example.com/start", client=_client(handler))


# --- Size and failure ------------------------------------------------------


def test_an_oversized_body_is_refused_while_downloading(public_dns):
    """Counted while streaming rather than read from Content-Length, which is
    the remote server's claim about itself."""
    def handler(request):
        return httpx.Response(200, content=b"x" * (MAX_FETCH_BYTES + 1024))

    with pytest.raises(UrlFetchFailed):
        fetch_document("https://example.com/big", client=_client(handler))


def test_a_lying_content_length_does_not_get_a_pass(public_dns):
    """A server willing to exhaust our memory is willing to understate its
    size."""
    def handler(request):
        return httpx.Response(
            200,
            content=b"x" * (MAX_FETCH_BYTES + 1024),
            headers={"content-length": "10"},
        )

    with pytest.raises(UrlFetchFailed):
        fetch_document("https://example.com/liar", client=_client(handler))


def test_an_empty_body_is_reported_rather_than_returned(public_dns):
    def handler(request):
        return httpx.Response(200, content=b"")

    with pytest.raises(UrlFetchFailed):
        fetch_document("https://example.com/empty", client=_client(handler))


def test_an_error_status_is_a_failure(public_dns):
    def handler(request):
        return httpx.Response(404)

    with pytest.raises(UrlFetchFailed):
        fetch_document("https://example.com/missing", client=_client(handler))


def test_a_transport_error_does_not_describe_what_happened(public_dns):
    """Distinguishing refused from filtered from timed out is exactly what a
    port scan wants to learn."""
    def handler(request):
        raise httpx.ConnectError("Connection refused")

    with pytest.raises(UrlFetchFailed) as caught:
        fetch_document("https://example.com/x", client=_client(handler))

    message = str(caught.value).lower()
    assert "refused" not in message and "timeout" not in message


# --- The URL never reaches the network at all ------------------------------


def test_a_private_literal_is_refused_before_any_request(public_dns):
    called = False

    def handler(request):
        nonlocal called
        called = True
        return httpx.Response(200, text="x")

    with pytest.raises(UrlRejected):
        fetch_document("http://127.0.0.1/", client=_client(handler))

    assert called is False


def test_an_unresolvable_host_is_refused_before_any_request():
    called = False

    def handler(request):
        nonlocal called
        called = True
        return httpx.Response(200, text="x")

    with patch("app.infrastructure.url_fetch.resolve_addresses", return_value=[]):
        with pytest.raises(UrlRejected):
            fetch_document("https://nowhere.example/", client=_client(handler))

    assert called is False
