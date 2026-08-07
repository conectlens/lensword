---
title: MCP Server / Local CLI Changelog
description: User-facing changes to MCP Server / Local CLI, with verification evidence per entry.
---

# MCP Server / Local CLI changelog

Status — MCP Server: **unreleased**, Local CLI: **unreleased**.

Every entry states exactly what was verified — a passing automated test does not imply a platform was manually checked, and a manual check on one OS does not imply another. See [Verification levels](/reference/trust/verification-levels) for what each status means.

<a id="remove-cloudflare-backend-mcp-fix-psycopg"></a>

### Fixed: Removed the Cloudflare Containers deploy config for backend/MCP (Render is the actual deployment path now) and fixed a real bug where a standard postgresql:// connection string (what Supabase/Neon/Railway hand you by default) crashed the app on startup instead of connecting.

*2026-08-07* — verification: automated tests: passed; production observation: observed

Pasting a standard Postgres connection string (Supabase, Neon, Railway, etc.) as DATABASE_URL now works without any manual edit. No change for anyone already using the +psycopg form.

<details><summary>Technical detail</summary>

apps/backend/wrangler.toml, apps/backend/cf-worker/, apps/mcp/wrangler.toml, apps/mcp/cf-worker/, and the Node/TS deploy tooling (package.json/package-lock.json/tsconfig.json) for both were deleted entirely, along with .github/workflows/deploy-backend.yml and deploy-mcp.yml — not just disabled. Confirmed via a real deploy that Cloudflare Containers requires the Workers Paid plan; Render (see render-deployment.md) is the deployment path actually in use. apps/mcp/Dockerfile is kept — Render's render.yaml references it too.
app/config.py's Settings.database_url gained a validator (_require_psycopg_driver) that rewrites a bare postgresql:// or postgres:// URL to postgresql+psycopg://. Without it, a standard connection string (exactly what Supabase's dashboard gives you to copy-paste) makes SQLAlchemy default to the psycopg2 driver, which isn't installed — the failure is a ModuleNotFoundError deep inside Alembic's env.py on container startup, with nothing pointing at the actual cause. Hit this exact failure in a real deployment attempt, not found by inspection.

</details>

<a id="mcp-read-tool-request-id-fix"></a>

### Fixed: Read-only MCP tool calls (e.g. searching your vocabulary) no longer fail with an "unsupported payload field" error.

*2026-08-07* — verification: automated tests: passed

Every read-only MCP tool (search_words, get_due_reviews, get_learning_progress, and others) now works when called through a real MCP client or the stdio protocol directly, instead of failing validation before reaching your account's actual permissions.

<details><summary>Technical detail</summary>

apps/mcp's BackendClient.invoke() unconditionally attaches a request_id to every tool call payload, but contracts.py's payload validator only allowed request_id on write-class tool schemas, so every read-class call made through the stdio MCP server was rejected before it could reach the policy gate. Fixed validate_payload() to always allow request_id, matching the /api/v1/mcp/invoke route handler's own read/write-aware handling of it, which already assumed this was safe.

</details>

**Known limitations:**
- No real MCP client (Claude Desktop, Cursor, VS Code) was connected interactively to confirm this from a client's perspective — verified directly against the JSON-RPC protocol instead.

References: [#276](https://github.com/conectlens/lensword/issues/276), [PR #300](https://github.com/conectlens/lensword/pull/300)

<a id="mcp-oauth-discovery"></a>

### Fixed: The remote MCP server now advertises where to authenticate, so an OAuth client (like Claude.ai's connector UI) can find the backend's authorization server instead of failing to register with no useful error.

*2026-08-07* — verification: automated tests: passed; artifact build: passed; production observation: observed

An OAuth-capable MCP client can now discover LensWord's sign-in service automatically when connecting to the remote MCP server, instead of failing with no actionable error.

<details><summary>Technical detail</summary>

apps/mcp/lensword_mcp/http_transport.py's StreamableHTTPMCPServer gained an oauth_issuer parameter (wired to the existing LENSWORD_API_URL — no new setting to keep in sync). With it set: GET /.well-known/oauth-protected-resource returns RFC 9728 metadata naming the backend as authorization_servers (the backend already implements the full authorization server at apps/backend/app/api/routers/mcp_oauth.py — dynamic client registration, authorize, token, revoke — behind REMOTE_MCP_ENABLED; this MCP server never implemented any OAuth surface itself, by design, since RFC 9728 treats resource and authorization server as distinct roles). A 401 for a missing bearer token now also carries a WWW-Authenticate: Bearer resource_metadata="..." header, which is how a spec-compliant client finds the metadata endpoint without being told the URL out of band. Both are no-ops (old behavior exactly, bare 401/404) when oauth_issuer is unset, and server.py now always passes it (LENSWORD_API_URL is already a required setting for the http transport, so this is not a new requirement). Found by a real connection attempt from an OAuth-based MCP client against a deployed instance, not by inspection — the client's connector UI reported "Couldn't register with LensWord's sign-in service," which traced back to exactly this missing discovery metadata. Verified against a real running Docker container (curl against both the new endpoint and the 401 header), not just unit tests.

</details>

**Known limitations:**
- Still not verified against a real, successful end-to-end OAuth flow with a third-party client (authorize -> consent -> token exchange -> an actual tool call) — this fix addresses the discovery step specifically, which is as far as the real attempt that found the gap got.

<a id="mcp-http-keepalive-body-drain"></a>

### Fixed: A misdirected request to the remote MCP server (e.g. an OAuth client trying to register at the wrong URL) no longer corrupts the next request on the same connection with a garbled, confusing 501 error.

*2026-08-07* — verification: automated tests: passed; production observation: observed

A misbehaving or exploring client (an OAuth registration attempt, another server's health check, anything hitting a path other than /mcp) gets a clean 404 and the connection keeps working normally, instead of corrupting whatever request comes after it.

<details><summary>Technical detail</summary>

apps/mcp/lensword_mcp/http_transport.py's do_POST checked the request path, Origin, and bearer token — and returned an error for any of them — before ever reading the request body off the socket (self.rfile.read(length)). On this HTTP/1.1 keep-alive server (protocol_version = "HTTP/1.1"), an early-return response left the unread body bytes sitting in the socket buffer. The next request sent on that same connection had its request line corrupted by those leftover bytes, producing exactly the failure a real Claude.ai connection attempt hit in production: a POST carrying an RFC 7591 dynamic-client-registration payload to this server's root path (not /mcp, since this server is the OAuth *resource*, not the *authorization server* — see mcp-oauth-discovery.yml) got its intended 404, but the undrained body corrupted the client's follow-up request into `Error code: 501 / Message: Unsupported method ('{"redirect_uris":[...]} GET')` — the leftover JSON body text glued to the next request's "GET". Fixed by resolving Content-Length and reading the full body (or deliberately closing the connection) before any other check can early-return: a missing/invalid Content-Length or an oversized body (over MAX_HTTP_BODY_BYTES) now sets self.close_connection = True instead of leaving an unreadable-length or deliberately-undrained body on a connection marked for reuse. A regression test opens one real http.client.HTTPConnection, sends a POST to the wrong path, then sends a second request on the *same* connection and asserts it gets a clean response rather than a stdlib 501 from a corrupted request line.

</details>

**Known limitations:**
- This fixes the connection-corruption symptom, not the underlying reason an OAuth client ends up POSTing registration to this server's root path in the first place (most likely because the backend authorization server was unreachable at the time — see render-supabase-ipv4-pooler-fix.yml — so the client fell back to guessing an endpoint on the resource server's own origin). A reachable, correctly-discoverable authorization server remains the real fix for that flow to succeed at all.

<a id="lensword-documentation-site"></a>

### Documentation: LensWord has a real documentation site (docs/, built with VitePress), organized around Diátaxis (Setup tutorial, Install how-to guides, Learn explanation, Reference material) — replacing a flat, uncurated docs/ folder.

*2026-08-07* — verification: automated tests: passed; artifact build: passed; manual checks — windows: passed; production observation: not_applicable

Every surface (Web, Desktop, Browser Extension, MCP Server, Local CLI) now has a real, verified guide instead of scattered or missing documentation — including install steps, security/privacy behavior, and an honest account of what has and hasn't been tested for that surface.

<details><summary>Technical detail</summary>

docs/.vitepress/config.mts defines the site; every existing doc was moved (not deleted) into the new structure, apps/browser/README.md and apps/mcp/README.md are pulled in via VitePress's markdown @include feature so they can't drift from source, and a SurfaceChooser Vue component reads docs/internal/product-registry.json directly so the surface-comparison table can't drift from the audit that backs it.

</details>

**Known limitations:**
- GitHub Pages deployment for the site is wired up but not yet enabled (repository Settings -> Pages -> Source is still unset) — the site builds successfully in CI but has no public URL yet.

References: [#272](https://github.com/conectlens/lensword/issues/272), [PR #295](https://github.com/conectlens/lensword/pull/295)
