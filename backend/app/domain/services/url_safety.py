"""Deciding whether a user-supplied URL is safe to fetch (issue #145).

Fetching a URL the user typed means the *server* makes a request the user
chose. From inside a deployment that reaches things the internet cannot:
`169.254.169.254` for cloud instance credentials, `localhost` for the admin
port, `10.x` for whatever else runs on the network. That is server-side request
forgery, and the reason this module exists rather than a bare `httpx.get`.

The design is deliberately a **denylist of address space, applied to resolved
addresses** rather than a pattern check on the string. A hostname is not an
address: `evil.example.com` can resolve to `127.0.0.1`, and any check that
looks at the text alone passes it. So the string is validated for shape, DNS
resolution happens, and then *every* address it resolved to is checked — one
public address does not excuse a second private one.

Pure and synchronous: it takes a URL and a list of resolved addresses and
returns a verdict. Nothing here opens a socket, which is what makes every rule
below testable without a network.
"""
from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from urllib.parse import urlsplit

# Only the two schemes a document can meaningfully arrive over. Everything else
# — `file://`, `ftp://`, `gopher://`, and the rest — either reads the server's
# own disk or reaches protocols whose parsers are a much larger attack surface
# than the fetch itself.
ALLOWED_SCHEMES = frozenset({"http", "https"})

# Ports are restricted to the defaults. A URL naming port 6379 or 11211 is not
# fetching a document; it is talking to Redis or memcached through an HTTP
# client, and the fact that the response is unparseable does not undo the
# request having been made.
ALLOWED_PORTS = frozenset({80, 443})

MAX_URL_LENGTH = 2048


@dataclass(frozen=True)
class UrlRejected(Exception):
    """Why a URL will not be fetched.

    Carries a reason meant to be shown to the user. Deliberately says *what*
    rule was broken and not what the server found — "that address is not
    reachable from here" would leak whether an internal host exists, turning
    the refusal itself into the scan it was meant to prevent.
    """

    reason: str

    def __str__(self) -> str:
        return self.reason


def validate_url_shape(raw: str) -> str:
    """Check everything decidable from the string alone. Returns the hostname.

    Runs before DNS so a malformed or obviously hostile URL costs no lookup.
    """
    if not raw or not raw.strip():
        raise UrlRejected("A URL is required")
    url = raw.strip()
    if len(url) > MAX_URL_LENGTH:
        raise UrlRejected("That URL is too long")

    parts = urlsplit(url)
    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        raise UrlRejected("Only http and https URLs can be imported")

    # Credentials in a URL are how a request gets aimed at something that would
    # otherwise refuse it, and they would end up in logs besides.
    if parts.username or parts.password:
        raise UrlRejected("URLs with embedded credentials are not accepted")

    hostname = parts.hostname
    if not hostname:
        raise UrlRejected("That URL has no host")

    port = parts.port or (443 if parts.scheme.lower() == "https" else 80)
    if port not in ALLOWED_PORTS:
        raise UrlRejected("Only the standard http and https ports can be imported")

    # An IP literal skips DNS entirely, so it is checked here rather than in
    # the resolved-address pass that would never see it.
    literal = _as_ip(hostname)
    if literal is not None:
        ensure_public_address(literal)

    return hostname


def ensure_public_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
    """Reject anything that is not ordinary public internet space.

    Written as "must be global" rather than "must not be one of these ranges".
    The denylist formulation always misses something — carrier-grade NAT,
    IPv4-mapped IPv6, the many reserved blocks — and the failure mode of a
    missed range is a request that should never have left the process.
    """
    # Covers 169.254.0.0/16, which is the cloud metadata endpoint and the
    # single most valuable target of an SSRF.
    if address.is_link_local:
        raise UrlRejected("That address is not allowed")
    if address.is_loopback or address.is_private or address.is_reserved:
        raise UrlRejected("That address is not allowed")
    if address.is_multicast or address.is_unspecified:
        raise UrlRejected("That address is not allowed")

    # An IPv4-mapped or 6to4 address is a way of writing a v4 address in v6
    # form; unwrapped, it must pass the same rules rather than sail through
    # because the v6 checks above do not recognise it.
    mapped = getattr(address, "ipv4_mapped", None)
    if mapped is not None:
        ensure_public_address(mapped)
    sixtofour = getattr(address, "sixtofour", None)
    if sixtofour is not None:
        ensure_public_address(sixtofour)

    if not address.is_global:
        raise UrlRejected("That address is not allowed")


def ensure_all_resolved_addresses_are_public(addresses: list[str]) -> None:
    """Every address a hostname resolved to must be acceptable.

    All of them, not the first. A hostname that returns one public address and
    one private address is the standard way to get past a check that stops at
    the first answer — the client is free to connect to either.
    """
    if not addresses:
        raise UrlRejected("That host could not be resolved")
    for raw in addresses:
        parsed = _as_ip(raw)
        if parsed is None:
            raise UrlRejected("That host could not be resolved")
        ensure_public_address(parsed)


def _as_ip(value: str):
    try:
        # Brackets survive from IPv6 URLs; strip them so the literal parses.
        return ipaddress.ip_address(value.strip("[]"))
    except ValueError:
        return None
