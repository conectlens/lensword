"""SSRF guards on user-supplied import URLs (issue #145).

Fetching a URL the user typed means the server makes a request the user chose,
from inside a network that reaches things the internet cannot. Every test here
is a specific way that has been abused.
"""
from __future__ import annotations

import ipaddress

import pytest

from app.domain.services.url_safety import (
    UrlRejected,
    ensure_all_resolved_addresses_are_public,
    ensure_public_address,
    validate_url_shape,
)


# --- Schemes ---------------------------------------------------------------


def test_an_ordinary_https_url_is_accepted():
    assert validate_url_shape("https://example.com/article") == "example.com"


def test_plain_http_is_accepted():
    assert validate_url_shape("http://example.com/article") == "example.com"


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/x",
        "gopher://example.com/x",
        "data:text/plain,hello",
        "jar:http://example.com/x!/",
    ],
)
def test_only_http_schemes_are_fetched(url):
    """Everything else either reads the server's own disk or reaches protocols
    whose parsers are a far larger attack surface than the fetch."""
    with pytest.raises(UrlRejected):
        validate_url_shape(url)


# --- Credentials and ports -------------------------------------------------


def test_embedded_credentials_are_refused():
    """How a request gets aimed at something that would otherwise refuse it —
    and they would end up in logs besides."""
    with pytest.raises(UrlRejected):
        validate_url_shape("https://user:password@example.com/")


def test_a_non_standard_port_is_refused():
    """A URL naming 6379 is not fetching a document; it is talking to Redis
    through an HTTP client, and an unparseable response does not undo the
    request having been made."""
    with pytest.raises(UrlRejected):
        validate_url_shape("http://example.com:6379/")


def test_the_default_ports_are_allowed_explicitly():
    assert validate_url_shape("https://example.com:443/x") == "example.com"
    assert validate_url_shape("http://example.com:80/x") == "example.com"


# --- Shape -----------------------------------------------------------------


def test_an_empty_url_is_refused():
    with pytest.raises(UrlRejected):
        validate_url_shape("   ")


def test_a_url_with_no_host_is_refused():
    with pytest.raises(UrlRejected):
        validate_url_shape("http:///nowhere")


def test_an_absurdly_long_url_is_refused():
    with pytest.raises(UrlRejected):
        validate_url_shape("https://example.com/" + "a" * 4000)


# --- IP literals -----------------------------------------------------------


def test_a_loopback_literal_is_refused_without_needing_dns():
    """An IP literal skips resolution entirely, so it has to be caught by the
    shape check or not at all."""
    with pytest.raises(UrlRejected):
        validate_url_shape("http://127.0.0.1/")


def test_the_cloud_metadata_address_is_refused():
    """169.254.169.254 is the single most valuable target of an SSRF: it hands
    out instance credentials to anything that can reach it."""
    with pytest.raises(UrlRejected):
        validate_url_shape("http://169.254.169.254/latest/meta-data/")


@pytest.mark.parametrize(
    "address",
    ["10.0.0.1", "172.16.0.1", "192.168.1.1", "127.0.0.1", "0.0.0.0", "169.254.169.254"],
)
def test_private_ipv4_space_is_refused(address):
    with pytest.raises(UrlRejected):
        ensure_public_address(ipaddress.ip_address(address))


@pytest.mark.parametrize("address", ["::1", "fe80::1", "fc00::1", "::"])
def test_private_ipv6_space_is_refused(address):
    with pytest.raises(UrlRejected):
        ensure_public_address(ipaddress.ip_address(address))


def test_an_ipv4_mapped_ipv6_address_is_unwrapped_before_judging():
    """A way of writing 127.0.0.1 in v6 form. Unwrapped it must fail the same
    rules rather than sail through because the v6 checks do not recognise it."""
    with pytest.raises(UrlRejected):
        ensure_public_address(ipaddress.ip_address("::ffff:127.0.0.1"))


def test_a_6to4_address_wrapping_private_space_is_refused():
    # 2002::/16 embeds a v4 address; 2002:a00:1:: wraps 10.0.0.1.
    with pytest.raises(UrlRejected):
        ensure_public_address(ipaddress.ip_address("2002:a00:1::"))


def test_ordinary_public_addresses_pass():
    ensure_public_address(ipaddress.ip_address("93.184.216.34"))
    ensure_public_address(ipaddress.ip_address("2606:2800:220:1:248:1893:25c8:1946"))


def test_an_ipv6_literal_in_brackets_is_parsed():
    with pytest.raises(UrlRejected):
        validate_url_shape("http://[::1]/")


# --- Resolved addresses ----------------------------------------------------


def test_a_hostname_resolving_only_to_public_space_is_accepted():
    ensure_all_resolved_addresses_are_public(["93.184.216.34"])


def test_every_resolved_address_must_be_public_not_just_the_first():
    """A hostname returning one public and one private address is the standard
    way past a check that stops at the first answer — the client is free to
    connect to either."""
    with pytest.raises(UrlRejected):
        ensure_all_resolved_addresses_are_public(["93.184.216.34", "127.0.0.1"])


def test_a_host_that_resolves_to_nothing_is_refused():
    with pytest.raises(UrlRejected):
        ensure_all_resolved_addresses_are_public([])


def test_an_unparseable_resolution_is_refused_rather_than_ignored():
    with pytest.raises(UrlRejected):
        ensure_all_resolved_addresses_are_public(["not-an-address"])


def test_a_rejection_does_not_say_what_was_found():
    """The refusal must not become the scan it was meant to prevent: "that host
    is not reachable" would confirm which internal addresses exist."""
    with pytest.raises(UrlRejected) as caught:
        validate_url_shape("http://10.0.0.1/")

    message = str(caught.value).lower()
    assert "10.0.0.1" not in message
    assert "private" not in message and "internal" not in message
