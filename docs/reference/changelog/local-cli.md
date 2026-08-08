---
title: Local CLI Changelog
description: User-facing changes to Local CLI, with verification evidence per entry.
---

# Local CLI changelog

Status — Local CLI: **unreleased**.

Every entry states exactly what was verified — a passing automated test does not imply a platform was manually checked, and a manual check on one OS does not imply another. See [Verification levels](/reference/trust/verification-levels) for what each status means.

<a id="split-local-cli-package"></a>

### Changed: The Local CLI is now published from its own apps/cli package (lensword-cli), independently versioned from the MCP server, with a PyPI publish workflow in place — not yet triggered.

*2026-08-08* — verification: automated tests: passed; artifact build: passed; manual checks — macos: passed

The MCP server is unaffected — installs and runs exactly as before (pip install -e apps/cli -e apps/mcp instead of pip install -e apps/mcp alone). The Local CLI's add/explain/diagnose/review subcommands now actually work against a live backend: they previously sent the wrong workspace value on every call and would error on the malformed timeout argument (see the bug fix above) — import-context, which never contacted the backend, was unaffected either way. Setup now needs three LENSWORD_* environment variables instead of four (LENSWORD_MCP_REQUESTER is gone; it never did anything). The Local CLI is now on its own release cycle (cli-v* tags, its own changelog page) separate from the MCP server's (mcp-v* tags). Nothing is installable from PyPI yet for either product.

<details><summary>Technical detail</summary>

Issue #311: apps/mcp used to ship both the MCP server (lensword-mcp entry point) and the Local CLI (lensword entry point, import-context/add/ explain/diagnose/review) as one Python package. The only code genuinely shared between the two was BackendClient/BackendError (the HTTP client to the backend's /api/v1/mcp/invoke boundary) — server.py itself had zero references to context_import.py, confirmed by grep before moving anything. Split into a new apps/cli package (lensword-cli, its own pyproject.toml, version 0.1.0): BackendClient/BackendError extracted to apps/cli/lensword_cli/backend_client.py, cli.py and context_import.py moved from apps/mcp/lensword_mcp/ with imports updated. apps/mcp now depends on lensword-cli==0.1.0 and imports BackendClient/BackendError from it rather than defining its own copy; its own lensword entry point was removed from pyproject.toml. Tests split the same way: apps/cli/tests/ gained test_cli.py and test_context_import.py (moved), plus a new test_backend_client.py holding the BackendClient.resource() URI-mapping tests that used to live in apps/mcp/tests/test_server.py (they test BackendClient itself, not anything MCP-protocol-specific) and two context_import-specific tests found the same way. apps/mcp/tests/ test_server.py and friends now import BackendError from lensword_cli.backend_client instead of relying on lensword_mcp.server's transitive re-export, so the real dependency is visible in the test imports rather than hidden. Since neither package is on PyPI yet, a fresh install needs both from source together (pip install -e apps/cli -e apps/mcp) — confirmed in a clean venv that pip resolves the local lensword-cli==0.1.0 requirement against the sibling editable install rather than reaching PyPI. The apps/mcp production Docker image (render.yaml's lensword-mcp service) needed a build-context change too: its Dockerfile can no longer install from apps/mcp alone now that it depends on the sibling apps/cli directory, so render.yaml's dockerContext moved from ./apps/mcp to the repo root (.), the Dockerfile now COPYs and installs both apps/cli and apps/mcp, and a root .dockerignore was added since Docker only reads a .dockerignore at the build context root. Confirmed with a real `docker build` against the updated Dockerfile/context. Added .github/workflows/publish-cli.yml: builds apps/cli with `python -m build`, checks the artifacts with `twine check`, and publishes via PyPI Trusted Publishing (pypa/gh-action-pypi-publish, OIDC, no API token secret), scoped to a `pypi` GitHub Environment so required-review protection can be added later. Triggers on `cli-v*` tags and workflow_dispatch (for exercising the build/check steps before the first tag or before the trusted publisher exists). A guard step fails the run if the pushed tag's version doesn't match apps/cli/pyproject.toml. This workflow has not actually run in GitHub Actions and no PyPI trusted publisher has been configured yet — see docs/internal/pypi-publishing.md for the setup the repo owner still needs to do. docs/internal/product-registry.json's local-cli entry updated: sourcePath -> apps/cli, versionSource -> apps/cli/pyproject.toml#version, versionTagPrefix -> cli-v (was mcp-v, shared with mcp-server), changelogRoute -> /reference/changelog/local-cli (was shared with mcp-server's /reference/changelog/mcp) — docs/.vitepress/config.mts's changelog nav and scripts/changelog/validate_registry.py's route/nav consistency check updated to match. status stays public-source-install-only (not changed to public — nothing is actually live on PyPI yet); statusNote now mentions the publish workflow's existence and untriggered state. Issue #311's TODO 4 (whether a published CLI build should default LENSWORD_API_URL to the hosted service) was deliberately left untouched — the existing fail-closed behavior (no default, missing env vars exit 2) is unchanged; that's a product/security decision for the repo owner, not made silently here. npm distribution (TODO 2) is also out of scope for this change. Also fixed, found while moving this code: apps/cli/lensword_cli/cli.py's _backend_from_env constructed BackendClient with 4 positional arguments (api_url, token, requester, workspace) against a constructor that only accepts 3 (api_url, token, workspace) plus timeout — LENSWORD_MCP_REQUESTER's value silently landed in the workspace field and the real workspace value landed in timeout. This predates the split (same bug existed in apps/mcp/lensword_mcp/cli.py before the move) and was never caught because the test suite's FakeBackendClient accepted the extra positional argument without complaint. LENSWORD_MCP_REQUESTER was already meaningless server-side (apps/mcp/README.md already documented that identity comes from LENSWORD_TOKEN alone, issue #196) — removed it from the CLI's required env vars entirely, fixed the constructor call to the real 3-argument shape, corrected FakeBackendClient's signature to match BackendClient's real one, and added a regression test asserting each env var lands in its correct field. docs/internal/product-registry.json's connect-mcp-client prerequisites list had the same stale LENSWORD_MCP_REQUESTER entry, corrected alongside it.

</details>

**Known limitations:**
- publish-cli.yml has not been run in GitHub Actions and no PyPI trusted publisher has been configured — pip install lensword-cli / pipx install lensword-cli do not work against the real index yet.

References: [#311](https://github.com/conectlens/lensword/issues/311)

<a id="mcp-crash-recovery-and-vocabulary-tools"></a>

### Fixed: Companion tools no longer drop the connection when the backend rejects a credential, every declared tool is now reachable through an OAuth scope, and eleven vocabulary-management tools (groups, word editing, memory-palace rooms, mnemonics, word map) were added to the MCP surface.

*2026-08-08* — verification: automated tests: passed

Composing a companion reply against an expired or wrong-environment credential now returns a message saying the connection needs re-authentication, instead of appearing to hang; a single failing tool call no longer takes down a local MCP server. Remote companions can be granted every tool the server advertises rather than only eight. An AI assistant can now create and list vocabulary groups (previously it had to guess numeric group IDs), edit or delete words, place words in memory-palace rooms, read and generate mnemonics, and read the word relationship map.

<details><summary>Technical detail</summary>

Three independent defects, found by auditing the live MCP surface against its own logs.
(1) Crash chain: MCPServer._ensure_loop caught a bare BackendError from get_loop and retried start_loop with the same credential, from outside any except block. On a 401 that exception escaped _reserve_or_error — whose docstring claimed it never raises — through tools/call and into the transport. http_transport.do_POST called MCPServer.handle unguarded, so socketserver logged a traceback and closed the socket with no response at all; StdioMCPServer.run caught only parse errors, so the same exception ended the serve loop and terminated the process. _ensure_loop now treats only 404 ("Companion loop has not been started") as "no budget yet" and propagates every other status; both transports answer with a JSON-RPC -32603 carrying an incident id, with the exception text logged rather than returned.
(2) Unreachable tools: mcp_scopes.SCOPE_TOOLS mapped 8 of 26 declared tools. Scopes are the only path by which an OAuth grant is provisioned, so the other 18 — the whole companion subsystem included — could never be consented to and answered no_grant indefinitely, indistinguishable from a revoked approval. All tools are now mapped, with a test asserting coverage in both directions.
(3) Opaque errors: add_word coerced target_language via SupportedLanguage(), whose ValueError is not a DomainError and so bypassed main.py's handler, producing an unhandled 500 that Starlette renders as plain text. The client found no JSON detail field and fell back to a fixed "LensWord request failed" string for every cause. BackendClient additionally called .get() on whatever json.loads returned, raising AttributeError instead of BackendError when an error body was a JSON list or string.
The eleven added tools bind to the same use cases that back the equivalent REST routes, so ownership is enforced by one code path rather than two.

</details>

**Known limitations:**
- Not exercised against a live third-party MCP client; verification is the repository's own test suites against the shared JSON-RPC handler, matching the standing gap recorded for this transport.
- lensword_search_words still has no group filter. Enumerating one group is served by the new lensword_list_group_words instead.
- lensword_delete_word is a hard delete with no archive tier, because the domain has none — DeleteWordUseCase removes the word and its review history. The tool requires an explicit confirmed=true and is annotated destructive.
- lensword_extract_vocabulary still requires an AI provider to be configured server-side; that is a deployment gap this change does not address.

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
