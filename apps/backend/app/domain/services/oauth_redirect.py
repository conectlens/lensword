"""Redirect URI validation for the remote MCP OAuth flow (issue #196).

A native/desktop MCP host is a "public" client per RFC 8252 — it cannot keep
a client secret, so its registered redirect URI is one of the only things
this server can pin down at registration and re-check at both
`/authorize` and `/token`. Pure string validation, zero I/O, so it lives
beside the other pure domain services.
"""
from __future__ import annotations

from urllib.parse import urlparse

# RFC 8252 section 7.3: a native app may redirect to a loopback interface it
# binds an ephemeral port on. `localhost` is included for the same case on
# platforms/frameworks that resolve it locally rather than over DNS, with
# the caveat OAuth 2.1 itself notes (some resolvers can be tricked) — https
# or a literal loopback IP is the safer choice a well-behaved client uses.
_LOOPBACK_HOSTS = ("127.0.0.1", "::1", "localhost")
_MAX_URI_LENGTH = 2048


def is_acceptable_redirect_uri(uri: str) -> bool:
    """True for https (any host) or http restricted to a loopback host.

    Never true for plain http to a non-loopback host, a fragment-bearing
    URI (RFC 6749 section 3.1.2 forbids a fragment component outright,
    since anything after `#` is never sent to the server and so cannot be
    verified here), or a custom app-link scheme — the last of those is a
    real, documented gap: see the PR description.
    """
    if not uri or len(uri) > _MAX_URI_LENGTH or "#" in uri:
        return False
    parsed = urlparse(uri)
    if parsed.scheme == "https":
        return bool(parsed.netloc)
    if parsed.scheme == "http":
        return parsed.hostname in _LOOPBACK_HOSTS
    return False


def redirect_uri_matches(requested: str, registered: list[str]) -> bool:
    """Exact match only.

    OAuth 2.1 supersedes RFC 6749's looser prefix-matching allowance
    specifically because prefix matching is a known open-redirect vector —
    a registered `https://host/callback` must not also authorize
    `https://host/callback/../steal-tokens`.
    """
    return requested in registered
