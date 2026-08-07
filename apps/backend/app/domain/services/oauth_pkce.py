"""PKCE (RFC 7636) verification for the remote MCP OAuth flow (issue #196).

Deliberately the one piece of this feature that reaches for a vetted crypto
library instead of hand-rolling: `authlib.oauth2.rfc7636.create_s256_code_challenge`
implements the S256 transform (`BASE64URL(SHA256(code_verifier))`) exactly as
RFC 7636 section 4.2 defines it. This module only adds the constant-time
comparison and the "reject anything but S256" policy on top — it does not
reimplement the digest/encoding itself.

Zero I/O, deterministic given its inputs, so it lives beside the other pure
domain services rather than in infrastructure.
"""
from __future__ import annotations

import hmac

from authlib.oauth2.rfc7636 import create_s256_code_challenge

# The MCP/OAuth 2.1 guidance drops the "plain" PKCE method entirely — it exists
# in RFC 7636 only for clients that cannot compute SHA-256, which does not
# describe any MCP host. Accepting it here would let a network attacker who
# intercepts the authorization request (the thing PKCE exists to defend
# against) simply resend the same value as both challenge and verifier.
SUPPORTED_CODE_CHALLENGE_METHOD = "S256"


def verify_pkce(code_verifier: str, code_challenge: str, code_challenge_method: str) -> bool:
    """Return True iff `code_verifier` transforms into `code_challenge`.

    Fails closed: an unsupported method, an empty verifier, or a verifier
    outside RFC 7636's 43-128 character bound is never valid, regardless of
    whether it happens to hash to the stored challenge.
    """
    if code_challenge_method != SUPPORTED_CODE_CHALLENGE_METHOD:
        return False
    if not (43 <= len(code_verifier) <= 128):
        return False
    if not code_challenge:
        return False
    computed = create_s256_code_challenge(code_verifier)
    return hmac.compare_digest(computed, code_challenge)
