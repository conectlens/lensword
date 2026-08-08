---
title: MCP Server Changelog
description: User-facing changes to MCP Server, with verification evidence per entry.
---

# MCP Server changelog

Status — MCP Server: **unreleased**.

Every entry states exactly what was verified — a passing automated test does not imply a platform was manually checked, and a manual check on one OS does not imply another. See [Verification levels](/reference/trust/verification-levels) for what each status means.

<a id="cloud-ai-provider-adapters"></a>

### Added: AI_PROVIDER now accepts gemini, vertex, or openai alongside the existing none/ollama, so a hosted deployment that cannot run its own Ollama daemon can still enable real AI features (mnemonic suggestions, vocabulary extraction/enrichment, the conversation tutor, learning paths, and the companion coach).

*2026-08-08* — verification: automated tests: passed

Self-hosters and the LensWord Cloud deployment can enable AI features on a platform that cannot run Ollama (e.g. Render) by setting AI_PROVIDER=gemini/vertex/openai and the corresponding API key/project ID, instead of being limited to a local-only Ollama install or no AI at all. No change for an existing AI_PROVIDER=none or AI_PROVIDER=ollama deployment.

<details><summary>Technical detail</summary>

Refactored OllamaProvider onto a new _TextGeneratingProvider Template Method base (app/infrastructure/ai_providers/base.py) — request construction, JSON/candidate parsing, and the companion-coach evidence/forbidden-claim contract (validate_generated_content) moved up from OllamaProvider into the shared base, behind two abstract hooks (_generate_text/_generate_json) every concrete adapter implements. Added GeminiProvider and VertexAIProvider (google-genai SDK, sharing one _GoogleGenAIProvider base since both call client.aio.models.generate_content identically and differ only in how the client is constructed — API key vs. Application Default Credentials) and OpenAIProvider (openai SDK). Registered in both SUPPORTED_AI_PROVIDERS tuples and build_ai_provider, which fails fast at startup with a clear ValueError if a cloud provider is selected without its one required field (GEMINI_API_KEY / VERTEX_PROJECT_ID / OPENAI_API_KEY). Generalized the admin ai-settings API: AISettingsResponse now reports gemini_api_key_set/openai_api_key_set booleans rather than ever echoing a configured key back, and PUT treats a blank key as "leave the stored one alone." /probe stays a real reachability+model-list check for Ollama but does not fire a billed generation call for a cloud provider on every admin page load — it reports whether the required credential looks configured instead (live_check_performed on the response marks the difference explicitly).

</details>

**Known limitations:**
- Gemini, Vertex AI, and OpenAI adapter code is covered by unit tests against a mocked transport only. No live-model verification pass has been run against a real Gemini, Vertex AI, or OpenAI account — no credentials were available in the environment this was built in. See docs/install/cloud-ai-providers.md's "Verification status" section.
- Vertex AI's Application Default Credentials resolution has not been verified end-to-end in an actual Docker/Render deployment — only that the google-genai SDK's own credential-loading path is reached correctly in a mocked-transport test.

References: [#315](https://github.com/conectlens/lensword/issues/315)

<a id="byok-ai-credentials"></a>

### Added: Signed-in users can now supply their own Gemini, OpenAI, or Vertex AI key on the Settings page ("Bring Your Own Key") and have it used automatically for their own AI requests, instead of being limited to whatever the deployment itself is configured with (or nothing, if the deployment has AI switched off).

*2026-08-08* — verification: automated tests: passed

A signed-in user can add, update, or remove their own Gemini/OpenAI/ Vertex AI key from the Settings page. Once added, their own AI requests (mnemonic suggestions, vocabulary enrichment, the conversation tutor, learning paths, the companion coach) use that key automatically. No change for a user who does not configure one — AI features work exactly as before, off the deployment's own configuration.

<details><summary>Technical detail</summary>

New user-scoped API (GET/PUT/DELETE /api/v1/me/ai-credentials[/{provider}]) alongside the existing admin-only, deployment-wide /api/v1/ai-settings — no admin opt-in gate required per user. Provider-agnostic Strategy pattern for extensibility: CredentialSchema subclasses per provider (app/domain/services/ai_credentials.py, zero third-party imports, matching the domain layer's existing boundary) registered in PROVIDER_CREDENTIAL_SCHEMAS validate each provider's own payload shape (a bare api_key for Gemini/OpenAI; a GCP service-account JSON plus project_id/location for Vertex AI) and declare which fields are safe to echo back (Vertex's project_id/location) versus never (the secret). A new provider needs one schema class plus one builder function in app/infrastructure/ai_providers/credential_mapping.py — nothing else in the stack changes. Stored encrypted (UserAICredentialModel, migration 20260808_01_user_ai_credentials) with application-level authenticated encryption (cryptography.fernet.Fernet) under one master key, AI_CREDENTIAL_ENCRYPTION_KEY — deliberately not a cloud KMS/Vault, to avoid adding a second service to this project's self-hosted-first Docker/Render/SQLite posture. The first reversibly-encrypted secret this codebase has ever stored; every other credential (passwords, OAuth tokens) is one-way hashed. resolve_ai_provider_for_user (app/api/deps.py) is the shared precedence policy behind every AI-serving route (twelve REST endpoints via PerUserAIProvider, plus the MCP invocation boundary via app.api.mcp_auth.get_ai_provider_for_actor, which resolves caller identity differently — a remote MCP OAuth token is not a login JWT): no stored credential falls back to the deployment default unchanged; a user's single stored credential is used regardless of the deployment's own provider; with more than one, whichever matches the deployment's own AI_PROVIDER wins, otherwise it falls back rather than guessing. A credential that exists but is currently unusable (wrong encryption key, unusable key material) deliberately raises the same AIProviderUnavailableError every other provider failure does, rather than silently falling back and spending the deployment's own budget on a user's broken personal key. New Settings page section (ByokCredentialsCard) mirrors the existing MCP connection credential field's write-only pattern: every field is password/textarea input, nothing is ever pre-filled from a saved value.

</details>

**Known limitations:**
- Fully covered by unit tests against a mocked transport only — no real Gemini/OpenAI/Vertex AI credentials were available to verify a live round trip through a user's own stored key. See docs/install/cloud-ai-providers.md's "Bring Your Own Key" section.
- This is the first reversibly-encrypted secret this codebase has ever stored (every prior credential is one-way hashed) and handles real financial-risk credentials. A focused security review was performed before this reached development, which found and this fragment's change fixes one SSRF (a self-signed Vertex AI service_account_json's token_uri, trusted verbatim by google-auth's own token-refresh HTTP call, could be pointed at an internal address such as the cloud metadata endpoint — closed by allowlisting token_uri to Google's real OAuth endpoint, since a genuine key never has any other value). No other findings survived the review's false-positive filtering pass.
- A user who configures credentials for more than one provider, neither matching the deployment's own AI_PROVIDER, cannot currently choose explicitly which one is used — the system falls back to the deployment default in that specific case rather than guessing. No UI exists yet for an explicit "active provider" choice.
- There is no key-rotation or re-encryption tooling if AI_CREDENTIAL_ENCRYPTION_KEY itself needs to change after credentials have already been stored under the old one.

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
