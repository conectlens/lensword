---
title: MCP Server Changelog
description: User-facing changes to MCP Server, with verification evidence per entry.
---

# MCP Server changelog

Status — MCP Server: **unreleased**.

Every entry states exactly what was verified — a passing automated test does not imply a platform was manually checked, and a manual check on one OS does not imply another. See [Verification levels](/reference/trust/verification-levels) for what each status means.

<a id="mcp-transport-request-amplification"></a>

### Performance: MCP tool calls now reuse a single network connection instead of opening a new one per request, subscribed resources are no longer refetched after every message, and bulk vocabulary imports and edits are a single call.

*2026-08-09* — verification: automated tests: passed

Importing or editing vocabulary through an MCP client is substantially faster, especially against a hosted backend where every call previously paid a fresh TLS handshake. Long-lived remote MCP servers no longer grow in memory as clients reconnect. Argument completion in an MCP host responds without a network round trip per keystroke.

<details><summary>Technical detail</summary>

Five compounding defects made a 100-word import cost roughly 300 HTTP requests over 300 separate TCP+TLS connections. BackendClient._request was built on urllib.request.urlopen, which supports neither keep-alive nor pooling; it now uses a lazily created, lock-guarded persistent http.client.HTTP(S)Connection that transparently reconnects and replays once when a peer closes an idle socket, keeping lensword-cli's zero-runtime-dependency guarantee and the BackendError contract unchanged. poll_subscriptions ran its coalesce check after the fetch, so the window suppressed only the notification while the request had already been paid for; both that guard and a new, separate minimum poll interval now sit above the fetch, and lensword://me/today and lensword://me/due are fetched once per pass rather than twice despite resolving to an identical backend call. The Streamable HTTP transport's session_ttl_seconds was assigned and never read, and _Session carried no timestamp to compute it from, so every reconnect without an explicit DELETE leaked a session for the process lifetime; sessions now carry last_seen, are evicted opportunistically under the existing lock, and have their pooled connection closed on eviction. Completion candidate lookups are cached per session instead of hitting the network per keystroke. Two bulk tools were added, lensword_add_words and lensword_update_words, the latter finally exposing the PATCH /api/v1/words/bulk capability that had existed since #140 without ever appearing on the MCP surface; both the tool and the REST route now run one shared BulkEditWordsUseCase rather than two implementations.

</details>

**Known limitations:**
- The minimum poll interval means a subscribed resource's change can take up to that interval to be noticed. Delivery is unchanged — a material change still produces exactly one notification, and nothing is lost — but detection is no longer instantaneous on the very next processed message.
- Subscription fingerprints still request a full 100-row page where they only need a count. Shrinking that page cannot be done without either making the count wrong beyond the page size or having the backend return a total, so it is deliberately left alone rather than traded for a fingerprint that silently misses changes.
- Connection reuse is verified against a loopback HTTP server, which proves the connection count but not TLS-handshake savings against a real remote HTTPS backend.
- The new CI job is not yet in the repository's required-status-check set, so a red run there will not block a merge until branch protection is updated.

References: [#347](https://github.com/conectlens/lensword/issues/347)

<a id="mcp-batch-write-tools"></a>

### Performance: Three MCP tools gained batched siblings, so placing words in a memory-palace room, recording a passage's word encounters, or generating exercises for a set of words is one call instead of one call per word.

*2026-08-09* — verification: automated tests: passed

Populating a memory palace or recording vocabulary met while reading is noticeably faster over MCP, and a single bad word id no longer discards the valid work alongside it: unusable items come back listed with a reason while the rest still apply.

<details><summary>Technical detail</summary>

Adds lensword_place_words_in_room, lensword_record_context_occurrences and lensword_generate_exercises_for_words, each bounded at 100 items and returning the {applied, skipped} partial-success shape BulkWordEditResponse already established. PlaceWordsUseCase is the substantive one: the previous path loaded, mutated and saved the same Room aggregate once per placement, so N placements meant N ownership checks, N reads, N writes and N windows for a lost update. It now resolves and ownership-checks the room once, lists the room's group once to obtain the placeable words, applies every placement to that single aggregate and persists once — three repository calls regardless of batch size. Batched record_context_occurrences derives a per-item operation id from the call's request_id so a retried, partially-applied batch converges instead of deduping the whole batch against its first item. The contract validator was extended to check array items recursively; it previously understood only string items, so an array of integers or of objects passed through unvalidated. Single-item tools are retained — removing one would invalidate OAuth grants keyed on its name — and each batch is registered under the same scope as the tool it batches.

</details>

**Known limitations:**
- lensword_delete_word is deliberately not batched; bulk-destructive confirmation semantics need their own decision.
- record_answer, begin_learning_activity, submit_activity_response and request_hint remain single-item by design — each call depends on the previous call's result, so batching them would be semantically wrong.
- The batched exercise generator eliminates round trips only. Unlike room placement it has no shared aggregate, so it still performs one ownership check per word.

References: [#348](https://github.com/conectlens/lensword/issues/348)

<a id="language-profile-cache"></a>

### Performance: Repeated language-profile lookups no longer rescan the learner's entire vocabulary each time, so an assistant that checks the profile between actions stops paying a full collection scan per call.

*2026-08-09* — verification: automated tests: passed

No visible change in behaviour. Assistants and MCP clients that read the language profile repeatedly during a session get their answer without a repeated full scan of the learner's collection, which is most noticeable on larger vocabularies.

<details><summary>Technical detail</summary>

GetLanguageProfileUseCase.execute read every group and every word the learner owns to produce five counts and a language list, with no memoization, and is reachable through lensword_get_language_profile, which an agent may call before or after each word lookup or exercise. Adds PerUserTTLCache, a generic bounded LRU with a time-to-live in the shape ai_cache.py established (same 15-minute TTL and 500-entry bound; no provider/model in the key, since the value is derived from the database rather than sampled from a generator). The use case takes the cache as a constructor argument defaulting to a shared module-level instance, so execute's signature is unchanged and a caller needing live data can pass cache=None. The use cases that add or delete a word, or create or delete a group, invalidate the learner's entry themselves — the code performing a mutation is the only place that reliably knows one happened. A conftest fixture clears the shared instance between tests, following the existing isolate_coach_cache precedent, since ids restart from 1 in each test database.

</details>

**Known limitations:**
- Answering a review moves known_word_count and active_word_count as repetitions and strength cross the mastery threshold, and that is not invalidated — it happens on the hot path of every single review, the drift is at most a few words, and the issue's own acceptance criterion allows the profile to catch up within one TTL window. Structural changes (adding or removing words, creating or deleting groups) are invalidated immediately.
- Renaming a group is deliberately not invalidated, because no field of LanguageProfile depends on a group's name. If a group's language becomes editable, that change would need invalidating, since target_languages is derived from it.
- The cache is per process and in-memory, so a deployment running several backend workers caches independently in each. That is the same trade ai_cache.py documents and is bounded by the same TTL.

References: [#342](https://github.com/conectlens/lensword/issues/342)

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

<a id="mcp-tool-names-titles-and-annotations"></a>

### Fixed: Every LensWord tool was being rejected by Claude as an "unsupported name" and never loaded at all. Tools now load, carry readable names and real descriptions, and no longer ask for confirmation before read-only actions like searching vocabulary.

*2026-08-08* — verification: automated tests: passed; production observation: observed

**Breaking.** Automatic for existing users: migration 20260808_42_tool_underscores rewrites `mcp_grants.tool` to the new identifiers, preserving exactly the permissions already approved and granting nothing new. Any external caller that hardcoded the old dotted tool names (a script calling /api/v1/mcp/invoke directly) must update them; there is no aliasing of the old names.

LensWord's tools now actually appear and work in Claude instead of being silently dropped, show readable names like "Add Vocabulary Word" instead of "Lensword.add word", and only ask for confirmation before writes that genuinely change something — reading vocabulary or progress no longer interrupts with a prompt.

<details><summary>Technical detail</summary>

Three defects in the same surface, all found against a live connected client rather than by inspection. (1) Tool identifiers were `lensword.add_word` style. MCP's own spec permits dots (it lists `admin.tools.list` as a valid example), but the Anthropic API restricts tool names to `^[a-zA-Z0-9_-]{1,64}$`, so Claude refused to load any of them and reported "26 tools with unsupported names, which have been excluded from this chat" — the connector appeared to connect successfully while exposing nothing. Renamed to `lensword_add_word` throughout (338 references across backend, MCP server, CLI, tests and docs). `mcp_grants.tool` stores these identifiers verbatim and MCPPolicyGate matches them exactly, so migration 20260808_42_tool_underscores rewrites existing grant rows; without it every already-authorized connection would keep rows naming tools that no longer exist and fail `no_grant` on every call until the user re-ran consent. `mcp_audit_events.tool` is deliberately left alone — those rows are hash-chained, so rewriting history would make a tamper-evident log correctly report tampering. (2) Every tool's description was the placeholder `f"LensWord {name}"`, which told a model nothing about what a tool did or when to use it. Added TOOL_DOCS in app/application/mcp/contracts.py: a `name -> (title, description)` block giving each tool a human-readable MCP `Tool.title` and prose describing what it does, when to reach for it, and the constraint callers most often get wrong. (3) No tool sent MCP `Tool.annotations`, and that schema's defaults are deliberately worst-case (`readOnlyHint` false, `destructiveHint` true, `openWorldHint` true), so hosts treated every tool — including pure reads like search_words and get_due_reviews — as a potentially destructive open-world writer and prompted for confirmation before each one. Annotations are now derived from the existing AccessClass: READ tools declare readOnlyHint/closed-world, WRITE tools declare non-destructive, idempotent (honest — every write contract mandates a client-chosen request_id that IdempotencyStore dedupes on) and closed-world, with a deliberately small DESTRUCTIVE_TOOLS set of the two genuinely irreversible calls (cancel_companion_task, finish_companion_session). These are hints only; the real boundary remains MCPPolicyGate's per-tool grants and OAuth scopes, which trust nothing a client sends.

</details>

**Known limitations:**
- Annotations are advisory. A host is free to ignore readOnlyHint and keep prompting, and the spec explicitly tells clients to distrust annotations from untrusted servers, so this improves the default experience rather than guaranteeing it.
- The two locally-handled tools (companion_reply, companion_elicit) carry hand-written annotations in apps/mcp rather than deriving them from the backend contract registry, since the backend has no contract for them.

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
