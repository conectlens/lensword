# Remote MCP: OAuth, Streamable HTTP, and what this app does not provide

Issue #196. Read this before pointing any MCP host that is not the local
stdio companion at a LensWord backend. It complements
[hosted-deployment.md](hosted-deployment.md) rather than repeating it — read
that one too if you are hosting for other people. For local stdio setup,
permissions/scopes, privacy/export/deletion/audit behavior, the verified-
fact-vs-AI-generated-advice distinction, and an honest compatibility matrix
across MCP hosts, see [mcp-companion-guide.md](mcp-companion-guide.md)
(issue #199) instead — this document stays scoped to the remote/OAuth
surface specifically.

## Read this first

**Remote MCP is off by default, in two independent places, and stays off
unless you deliberately turn it on.**

1. The backend's OAuth authorization/token endpoints and discovery metadata
   (`/api/v1/mcp/oauth/*`, `/.well-known/oauth-*`) all 404 unless
   `REMOTE_MCP_ENABLED=true` is set on the backend. `/api/v1/mcp/invoke`
   itself is unaffected either way — it still requires an authenticated
   caller — but with the flag off, no OAuth access token can ever exist to
   present to it.
2. `apps/mcp`'s Streamable HTTP transport does not start unless the
   companion process is launched with `LENSWORD_MCP_TRANSPORT=http` **and**
   `LENSWORD_MCP_REMOTE_ENABLED=1`. Every existing local stdio setup — the
   desktop app, a self-hosted single-user install, `lensword-mcp` run from a
   terminal — is completely unaffected: it still speaks stdio and still
   authenticates with the account's own login JWT exactly as it did before
   this issue.

Turning either flag on without doing the rest of this document (TLS, a
real `MCP_ISSUER_URL`, an origin allowlist) does not make remote access
safe. It makes the endpoints reachable, which is a precondition, not a
guarantee.

## This application does not terminate TLS, anywhere, for anything

Neither the FastAPI backend nor `apps/mcp`'s Streamable HTTP transport
speaks TLS. Both listen on plain HTTP. This was already true for the whole
backend before this issue (see hosted-deployment.md's "TLS and origins"
section) and remains true for the new remote MCP surface — nothing added
by issue #196 changes that boundary or claims otherwise.

**A remote MCP deployment absolutely requires TLS in front of both**:

- The backend's OAuth endpoints send bearer tokens and authorization codes
  over the wire — a code or token observed in transit over plain HTTP is a
  live credential to the account that authorized it.
- The Streamable HTTP transport carries the same kind of bearer token on
  every request (see below).

Put a real reverse proxy (nginx, Caddy, your platform's managed load
balancer — whatever already terminates TLS for the rest of your
deployment, per hosted-deployment.md) in front of both, and do not expose
either process's raw HTTP port to anything but that proxy.

## What "remote MCP" means concretely in this codebase

A remote MCP host (something that is not the local stdio companion talking
to a backend on the same machine) needs three things, all new in #196:

1. **OAuth authorization-code + PKCE**, against the backend
   (`app/api/routers/mcp_oauth.py`). It registers itself (or is
   pre-registered), sends the resource owner through `/authorize`, and
   exchanges the resulting code — with its PKCE `code_verifier` — for a
   short-lived access token and a rotating refresh token at `/token`. This
   access token is **never** the user's normal login JWT; see
   `app/api/mcp_auth.py`'s module docstring for why that separation exists
   and how it's enforced.
2. **Scoped grants.** The token is bound to (user, client, scope,
   workspace) and only unlocks the specific MCP tools the approved scopes
   list in `app/domain/services/mcp_scopes.py` — the same deny-by-default
   `MCPPolicyGate` the local path has always used, not a separate or looser
   check.
3. **A transport that isn't stdin/stdout.** `apps/mcp/lensword_mcp/http_transport.py`
   implements the request/response half of the MCP Streamable HTTP
   transport. It is a plain, unencrypted HTTP server by itself — the TLS
   requirement above is what makes it safe to expose.

## What is real, tested code today, and what is not

Honest accounting, because pretending this is production-hardened when it
has not been through interop testing or a red-team pass would be worse
than saying so plainly.

**Real and tested:**

- OAuth authorization-code + PKCE (S256 only — plain is rejected), short-lived
  access tokens, rotating refresh tokens with reuse-detection that revokes
  the whole token family.
- Scoped grants provisioned through the existing `MCPGrantModel`/
  `MCPPolicyGate` machinery, not a parallel authorization system.
- Token revocation (`/revoke`, and the connection-management "disconnect"
  endpoint) takes effect immediately — the very next `/invoke` call with
  that token is rejected.
- The Streamable HTTP transport's request/response mode: session lifecycle,
  origin allowlisting, bounded request bodies, a per-request timeout, and
  token-substitution detection (a session id replayed with a different
  bearer token than the one that opened it is rejected).
- Mandatory `request_id` (idempotency key) on every MCP write tool call,
  authorization-code single-use enforcement, and the adversarial test suite
  in `apps/backend/tests/test_mcp_security.py` and
  `apps/backend/tests/test_mcp_oauth.py` covering cross-user grant reuse,
  token substitution, and requester-identity spoofing attempts.
- (Issue #199) Cross-user resource enumeration specifically over the MCP
  tool surface (a real grant plus another account's real session/task id) —
  `apps/backend/tests/test_mcp_cross_user_enumeration.py` — and audit-chain
  tamper detection is now independently verifiable, not just tamper-shaped:
  `app.domain.services.mcp_policy.verify_chain` recomputes the hash chain
  and `apps/backend/tests/test_mcp_audit_chain_tamper.py` proves a directly
  mutated audit row is caught and localized.

**Explicitly not implemented — documented gaps, not silent ones:**

- **Server-initiated SSE streaming** (the other half of the Streamable HTTP
  spec, `GET` + `text/event-stream`). Every tool call and resource read
  this server exposes is plain request/response, so nothing here needs it
  today; a client that requires it gets a clean `405`, not a hang.
- **No live interop test against a third-party MCP host.** The transport's
  wire shapes are checked against this repository's own stdio
  `MCPServer.handle` (both transports share it) and against the published
  MCP spec text. That is not the same as having run a real client against
  it.
- **Shared/distributed rate limiting.** `rate_limit_mcp_oauth` is the same
  single-process, per-instance limiter the rest of this app already uses
  (see hosted-deployment.md's "Rate limiting" section for the identical
  caveat) — behind more than one backend instance, the effective ceiling is
  multiplied by instance count. There is no Redis or equivalent in this
  project to build a real distributed limiter on; adding one is out of
  scope for this issue.
- **Remote resource reads are narrower than local ones.** The local stdio
  transport's `BackendClient.resource()` reads arbitrary `lensword://` URIs
  through direct REST passthrough, trusted at the level of "this bearer
  token belongs to some user" — appropriate for a local companion at the
  same trust level as the browser. Wiring that same passthrough to a
  narrowly-scoped remote OAuth token would silently turn a `session-read`
  grant into unrestricted REST access. Instead, `GET /api/v1/mcp/resource`
  serves only the small set of resources listed in
  `app/domain/services/mcp_scopes.py`'s `SCOPE_RESOURCES`, each gated by
  the same per-tool grant check `/invoke` uses. A remote client that needs
  a resource outside that set does not have one today.
- **No custom app-link redirect URI scheme** (e.g. `myapp://callback`) —
  `app/domain/services/oauth_redirect.py` only accepts `https://` or a
  loopback `http://` redirect (RFC 8252 §7.3). A native host that relies on
  a custom scheme instead of a loopback port cannot register today.
- **Connection-management UI is minimal.** It lists connected companions,
  their scopes, last use, and a revoke action (see the frontend's companion
  connections page). It does not yet implement per-tool/per-resource
  granular consent toggles or a "capability change" diff view beyond what
  the `/authorize` preview endpoint reports as `new_scopes` — the frontend
  surfaces that list, but does not yet block re-approval on it with a
  dedicated warning dialog.

## Operator checklist

- [ ] TLS terminated in front of both the backend and the HTTP MCP
      transport, by a real reverse proxy — neither process does this itself.
- [ ] `REMOTE_MCP_ENABLED=true` and `MCP_ISSUER_URL` set to the actual
      public HTTPS origin the backend is reached on (this becomes the
      `issuer`/`resource` values in the published metadata documents — a
      wrong value here is a broken client, not merely a cosmetic issue).
- [ ] `LENSWORD_MCP_ALLOWED_ORIGINS` set on the HTTP transport if any
      browser-based MCP host will call it directly (empty, the default,
      rejects every browser-Origin request and only allows callers that
      send no `Origin` header at all).
- [ ] Egress/ingress rules reviewed the same way hosted-deployment.md
      describes for the rest of the application — nothing new here changes
      that guidance.
- [ ] Read the "explicitly not implemented" list above and confirm none of
      it is load-bearing for your use case before relying on this.
