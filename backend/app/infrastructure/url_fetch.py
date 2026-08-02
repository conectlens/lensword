"""Fetching a user-supplied URL, as safely as this can be done (issue #145).

The rules live in `app.domain.services.url_safety`; this is the adapter that
resolves DNS, applies them, and pulls bytes.

Three things it does that a plain `httpx.get` does not:

**Redirects are followed by hand.** Automatic redirect following would validate
the first URL and then let the server send the client anywhere — a 302 to
`http://169.254.169.254/` is the oldest way past an SSRF check. Every hop is
re-validated as if it had been typed.

**The body is bounded while it downloads**, not after. Checking a Content-Length
header trusts the remote server about its own size; streaming with a running
total does not.

**Failures do not describe what was found.** A refusal that distinguished
"connection refused" from "timed out" would turn this endpoint into a port
scanner for the network the server sits in.

A residual risk stays, and is documented rather than papered over: between
resolving a hostname and connecting to it, the answer can change (DNS
rebinding). Closing that fully means pinning the connection to a validated
address, which breaks TLS certificate validation for the hostname. The mitigation
is network egress restrictions, which `docs/hosted-deployment.md` recommends.
"""
from __future__ import annotations

import ipaddress
import logging
import socket

import httpx

from app.domain.services.url_safety import (
    UrlRejected,
    ensure_all_resolved_addresses_are_public,
    validate_url_shape,
)

logger = logging.getLogger(__name__)

# Generous enough for an article, small enough that a hostile server cannot use
# this endpoint to fill the disk. The parser layer bounds it again.
MAX_FETCH_BYTES = 5 * 1024 * 1024

# A slow remote must not hold a worker open indefinitely.
FETCH_TIMEOUT_SECONDS = 10.0

# Enough for the http→https and www→apex hops a real site uses; short enough
# that a redirect loop ends quickly.
MAX_REDIRECTS = 5


class UrlFetchFailed(Exception):
    """The fetch did not produce a document.

    Deliberately one class with a generic message rather than a taxonomy of
    network errors: the difference between refused, filtered and timed out is
    exactly what a port scan wants to learn.
    """


def resolve_addresses(hostname: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UrlRejected("That host could not be resolved") from exc
    return [info[4][0] for info in infos]


def fetch_document(url: str, *, client: httpx.Client | None = None) -> tuple[bytes, str]:
    """Fetch a URL and return its bytes and a filename hint.

    The filename hint exists because the parser registry keys off media type
    with the filename as a fallback signal — a URL ending `.pdf` should reach
    the PDF parser the same way an uploaded file would.
    """
    current = validate_and_resolve(url)

    owns_client = client is None
    client = client or httpx.Client(
        timeout=FETCH_TIMEOUT_SECONDS,
        follow_redirects=False,
        # A server that gets no user agent often refuses; one that gets a
        # browser's is being lied to. This says what it is.
        headers={"User-Agent": "LensWord/1.0 (vocabulary import)"},
    )
    try:
        for _ in range(MAX_REDIRECTS + 1):
            response = _get(client, current)
            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    raise UrlFetchFailed("That page could not be fetched")
                # Resolved against the current URL so a relative Location works,
                # then validated from scratch — the redirect target gets no
                # more trust than the original URL did.
                current = str(httpx.URL(current).join(location))
                validate_and_resolve(current)
                continue
            if response.status_code >= 400:
                raise UrlFetchFailed("That page could not be fetched")
            return _read_bounded(response), _filename_hint(current, response)
        raise UrlFetchFailed("That page redirected too many times")
    finally:
        if owns_client:
            client.close()


def validate_and_resolve(url: str) -> str:
    """Apply every rule to a URL, including resolving it. Returns the URL."""
    hostname = validate_url_shape(url)
    if _is_ip_literal(hostname):
        # Already checked by the shape pass; resolving it would only ask the
        # system to confirm an address we can read directly.
        return url
    ensure_all_resolved_addresses_are_public(resolve_addresses(hostname))
    return url


def _get(client: httpx.Client, url: str) -> httpx.Response:
    try:
        return client.send(client.build_request("GET", url), stream=True)
    except httpx.HTTPError as exc:
        # Logged with detail for the operator, reported without it to the user.
        logger.info("URL import fetch failed: %s", exc)
        raise UrlFetchFailed("That page could not be fetched") from exc


def _read_bounded(response: httpx.Response) -> bytes:
    """Read the body, stopping if it exceeds the cap.

    Counted while streaming rather than checked afterwards: a Content-Length
    header is the remote server's claim about itself, and a server willing to
    exhaust our memory is willing to lie about it.
    """
    chunks: list[bytes] = []
    total = 0
    try:
        for chunk in response.iter_bytes():
            total += len(chunk)
            if total > MAX_FETCH_BYTES:
                raise UrlFetchFailed("That page is too large to import")
            chunks.append(chunk)
    except httpx.HTTPError as exc:
        raise UrlFetchFailed("That page could not be fetched") from exc
    finally:
        response.close()
    if not chunks:
        raise UrlFetchFailed("That page was empty")
    return b"".join(chunks)


def _filename_hint(url: str, response: httpx.Response) -> str:
    """A filename for the parser registry to fall back on.

    Taken from the URL path when it carries a recognisable extension, and
    otherwise synthesised from the content type. Never taken from
    Content-Disposition, which is attacker-controlled and would let a remote
    server choose which parser runs.
    """
    path = httpx.URL(url).path
    tail = path.rsplit("/", 1)[-1]
    if "." in tail and len(tail) <= 128:
        return tail

    content_type = (response.headers.get("content-type") or "").split(";")[0].strip().lower()
    suffix = {
        "text/html": "html",
        "application/xhtml+xml": "html",
        "application/pdf": "pdf",
        "text/plain": "txt",
        "text/markdown": "md",
    }.get(content_type, "html")
    return f"imported.{suffix}"


def _is_ip_literal(hostname: str) -> bool:
    try:
        ipaddress.ip_address(hostname.strip("[]"))
        return True
    except ValueError:
        return False
