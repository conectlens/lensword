---
title: Changelog
description: Product-aware changelog overview — every LensWord surface, with its own release identity and verification evidence.
---

# Changelog

LensWord isn't one product with one changelog — it's five independently distributable surfaces (plus a shared backend that isn't independently released), each with its own release status and verification evidence. Pick a product below for its full history, or read the combined list here.

| Product | Status | Changelog |
|---|---|---|
| Web Application | unreleased | [Web Application changelog](/reference/changelog/web) |
| Desktop Application | unreleased | [Desktop Application changelog](/reference/changelog/desktop) |
| Browser Extension | unreleased | [Browser Extension changelog](/reference/changelog/browser-extension) |
| MCP Server | unreleased | [MCP Server changelog](/reference/changelog/mcp) |
| Local CLI | unreleased | [Local CLI changelog](/reference/changelog/local-cli) |

The shared backend (`apps/backend`) is not an independently released product — see [docs/internal/repo-audit.md](https://github.com/conectlens/lensword/blob/development/docs/internal/repo-audit.md). Its changes are folded into whichever product(s) they actually affect, listed below.

## Latest changes, all products

**Web Application, Desktop Application**

<a id="weekly-report-action-feedback"></a>

### Fixed: The weekly report's "Generate AI interpretation" and "Refresh factual snapshot" buttons now show a spinner while working and a visible message when they fail, instead of appearing to do nothing.

*2026-08-09* — verification: automated tests: passed

Pressing either button on the weekly report now gives immediate visible feedback, and a failure — most likely when generating the AI interpretation — is reported on screen with the report still readable, rather than silently doing nothing.

<details><summary>Technical detail</summary>

Both buttons in WeeklyReportPage.tsx called reportsApi.<...>().then(setReport) directly from onClick, with no loading state, no disabled state and no .catch, so a request in flight was invisible and a failed one produced an unhandled promise rejection with nothing rendered. Both now use Button's existing loading prop, which already renders a spinner and disables the control, so no new UI primitive was needed. A single pending-action state disables both buttons while either runs, since each replaces the whole report and racing them would leave whichever finished last silently winning. Action failures render inline through a separate actionError state, kept apart from the page-level error state that replaces the whole view — that is the right response to the report failing to load and the wrong one to a button failing. Retrying clears a previous failure.

</details>

**Known limitations:**
- The interpretation is generated in one request rather than streamed, so the feedback is a spinner for the whole wait rather than progressive output.
- Verified by component tests against a mocked reports API; the buttons were not exercised against a live AI provider.

References: [#344](https://github.com/conectlens/lensword/issues/344)

**Web Application**

<a id="web-browser-notifications"></a>

### Added: The web app can now show browser notifications for due reviews, opted into from Settings. Permission is only ever requested when you click to turn it on, never on page load.

*2026-08-09* — verification: automated tests: passed

Users of the web app can opt in to browser notifications for due reviews from Settings, per browser. Nothing changes for anyone who does not opt in: no prompt appears on page load, and reminders continue to build up in the app as before. Browsers that block notifications, do not support them, or are served over plain HTTP now say so in Settings instead of presenting a switch that silently does nothing.

<details><summary>Technical detail</summary>

Adds lib/webNotifications.ts (support detection, permission, per-browser opt-in, show), lib/useWebNotifications.ts (a 30s outbox poll mirroring useDesktopNotifications) and a WebNotificationsCard settings section, which is the only caller of Notification.requestPermission() anywhere in the app. The collect/show/acknowledge loop was extracted from desktopNotifications.ts into lib/notificationOutbox.ts so both clients share one implementation; only show and ensurePermission were ever platform-specific, and desktopNotifications.ts re-exports the moved symbols so existing importers are unaffected. No backend change and no migration: the existing /api/v1/desktop-notifications outbox is client-agnostic despite its name, and recall_delivery.py's channel and quiet-hours policy still decides whether a notification is owed at all. The per-browser opt-in is stored in localStorage rather than on the account because notification permission is granted per browser profile — an account-level flag would claim notifications were on in Safari because they were granted in Chrome. The card renders nothing inside the Tauri shell, which raises OS notifications itself, so a reminder cannot be shown twice.

</details>

**Known limitations:**
- Notifications are delivered only while LensWord is open in a tab. There is no service worker or push subscription, so nothing arrives with the app closed. That is the same trade the desktop client documents — the backend durably records what is owed, so a missed poll costs latency and nothing else — and a push transport would add a reconnect story, a second auth path, and a server-side subscription registry.
- Clicking a notification focuses the tab but does not record a start_session action or navigate to the review, as the desktop shell's action buttons do. Routing from a notification is a separate change.
- The opt-in is per browser profile and does not follow the account to another browser or device, which is inherent to how browsers grant notification permission.
- Verified by unit and component tests against a stubbed Notification API; no notification was observed being raised by a real browser.

References: [#345](https://github.com/conectlens/lensword/issues/345)

**Web Application, Desktop Application**

<a id="themed-select-component"></a>

### Fixed: Dropdowns now open in the app's own dark styling instead of the browser's white system popup, and every dropdown in the app uses the same control.

*2026-08-09* — verification: automated tests: passed

Opening any dropdown in dark mode now shows a dark, app-styled list instead of a white system popup. Keyboard and screen-reader operation is preserved, and dropdowns look and behave identically everywhere in the app rather than varying by screen.

<details><summary>Technical detail</summary>

components/ui/Select.tsx wrapped a native `<select>` and styled its `<option>` elements, which browsers very largely ignore because the open dropdown is OS-level chrome rather than part of the page — so the popup kept rendering light against the app's dark surface no matter what CSS was applied. Rebuilt on @radix-ui/react-select, an unstyled accessible listbox primitive, so the open list is ordinary markup the app themes itself. Radix was chosen over a hand-rolled listbox because the parts that are easy to get wrong are the ones nobody notices until someone depends on them: roving focus, typeahead, aria-activedescendant, returning focus to the trigger on close. All 16 raw `<select>` elements across 11 files were migrated to the shared component, along with the 4 existing call sites, so the audit the issue asked for is complete rather than partial. The API is value/onValueChange rather than a native change event, and gained a size variant for the compact inline dropdowns several toolbars use. Radix reserves the empty string for "nothing selected", so filters offering "Any" or "Leave unchanged" use an exported ANY_OPTION sentinel that call sites map back themselves. Test setup gained the jsdom stubs the primitive needs (hasPointerCapture, ResizeObserver, DOMRect) and a shared selectOption helper that drives the control by keyboard.

</details>

**Known limitations:**
- Visual QA across light and dark themes was not performed. The change is verified by unit tests asserting the open list is rendered by the app rather than as native popup chrome, which is the structural cause of the bug, but no dropdown was observed in a real browser in either theme.
- Adds a runtime dependency (@radix-ui/react-select) to a frontend that previously had only React, the router and the icon library. The bundle grows accordingly. The issue names this trade explicitly, on the grounds that a hand-rolled listbox trades bundle size for accessibility risk.
- The desktop shell's Content-Security-Policy was read and does permit the inline styles the primitive uses for positioning (style-src 'self' 'unsafe-inline'), but this was not confirmed by running the packaged desktop build.

References: [#341](https://github.com/conectlens/lensword/issues/341)

**Backend (API), MCP Server, Local CLI**

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

**Backend (API), MCP Server**

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

**Backend (API), MCP Server**

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

**MCP Server, Local CLI**

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

**Backend (API), MCP Server**

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

**Backend (API), Web Application**

<a id="mcp-oauth-consent-page-and-remote-workspace"></a>

### Fixed: Connecting a remote MCP client (like Claude.ai) to a LensWord account now actually works end to end — it previously failed on every attempt with "Could not validate credentials."

*2026-08-08* — verification: automated tests: passed; production observation: observed

Connecting Claude.ai (or any other OAuth-based MCP client) to a LensWord account now completes successfully — login, consent, and the handoff back to the connector all work, instead of failing at the first step with no actionable error.

<details><summary>Technical detail</summary>

Two compounding bugs, both found by tracing a real Claude.ai connection attempt through to a live backend rather than by inspection. (1) The authorization-server metadata's `authorization_endpoint` advertised this backend's own GET/POST /api/v1/mcp/oauth/authorize — a Bearer-token JSON API — as the URL a connector should open in the user's browser. A browser navigation never attaches a custom Authorization header, so `current_user` could never resolve and every real attempt failed with "Could not validate credentials"; no frontend page existed anywhere to intercept that URL, log the user in, and call the API with their stored token on their behalf (the backend router's own docstring described that page's existence without it ever having been built). Fixed on both ends: apps/frontend/src/features/mcp/ OAuthAuthorizePage.tsx is that missing page (new route /oauth/authorize in App.tsx, not wrapped in ProtectedRoute since it must not carry the app's nav shell) — it redirects to /login with the current URL preserved as its next= param when logged out (LoginPage.tsx now honors `next`, validated against open-redirect via a same-origin-relative-path check), otherwise fetches the consent preview, renders the requesting client's name and scopes, and on approve/deny POSTs the decision and does a hard `window.location.href` navigation to the returned redirect_uri (an external callback URL, not a route this app owns). Settings.mcp_consent_url (app/config.py) is the new authorization_endpoint value; must be set to this deployment's real frontend origin + /oauth/authorize (render.yaml: MCP_CONSENT_URL). (2) Even reaching that endpoint, the request still failed: GET/POST /authorize required a `workspace` parameter that no external OAuth client sends (Claude.ai's redirect carries RFC 8707's `resource` instead, which this app never read), and workspace was validated by is_valid_workspace as an absolute POSIX filesystem path — a concept built for the desktop companion's local-directory sandboxing, meaningless for a remote, browser-only connector with no filesystem access. workspace is now optional on both endpoints, defaulting server-side to the new Settings.mcp_remote_workspace, and is_valid_workspace accepts that one configured value as a deliberate special case alongside its existing absolute-path rule (app/api/routers/ mcp.py). This value must equal the deployed remote MCP resource server's own LENSWORD_MCP_WORKSPACE exactly, the same way mcp_issuer_url must match that service's LENSWORD_API_URL — the resource server presents this string on every tool-invocation request, and a grant recorded under a different value would never match it (render.yaml: MCP_REMOTE_WORKSPACE, kept identical to lensword-mcp's existing LENSWORD_MCP_WORKSPACE).

</details>

**Known limitations:**
- The `resource` parameter Claude.ai's redirect includes (RFC 8707) is still not read or validated against — this fix addresses the concrete failure that blocked every connection attempt, not full RFC 8707 resource-indicator enforcement.

**MCP Server, Local CLI, Backend (API)**

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

**Web Application, Desktop Application, Browser Extension, MCP Server, Local CLI**

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

**Web Application, Desktop Application, Browser Extension, MCP Server, Local CLI**

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

**Backend (API)**

<a id="scheduler-persisted-job-callable-collapse"></a>

### Fixed: Four background jobs — reminder delivery, acquisition-ladder notifications, companion task progress, and scheduler-claim cleanup — no longer fail every time they fire in production.

*2026-08-07* — verification: automated tests: passed; production observation: observed

Reminders are delivered, acquisition-ladder nudges are sent, and companion task extraction actually makes progress again — all four were silently failing on every scheduled firing.

<details><summary>Technical detail</summary>

apps/backend/app/infrastructure/scheduler.py registered each job by passing a *constructed* dispatcher instance directly as the job's func, e.g. scheduler.add_job(CompanionTaskExecutor(session_factory), ...); apps/backend/app/infrastructure/reminders.py did the same with ReminderDispatcher via ApSchedulerReminderScheduler. The persistent SQLAlchemyJobStore does not pickle a job's callable — it stores a plain "module:qualname" string (apscheduler.util.obj_to_ref) and re-derives the callable from that string alone on every load. For a constructed instance, that collapses to a reference to its bare class: obj_to_ref has no way to name an instance, only a type, so the constructor's session_factory/channel arguments were silently dropped. Every dispatch after the first add_job() then called e.g. CompanionTaskExecutor() with no arguments and raised TypeError: CompanionTaskExecutor.__init__() missing 1 required positional argument: 'session_factory' — reproduced live in this deployment's logs for CompanionTaskExecutor (every 10s) and AcquisitionDispatcher (every 5m); ReminderDispatcher shared the identical bug but had not yet fired in production since no enabled reminder had come due. Confirmed empirically that the underlying session_factory (a live SQLAlchemy sessionmaker bound to a real Engine) is not picklable, which ruled out registering a bound method instead (APScheduler's own fallback for stateful job bodies, which pickles the instance into the job's stored args) as a fix. Fixed by keeping each dispatcher instance as a module-level global and registering a plain, zero/primitive-argument top-level function (e.g. _run_companion_task_executor) as the job's func instead — such a reference round-trips correctly, and the wrapper reads the live instance from module state at call time, which is safe because every job in this store only ever runs inside the process that registered it. Two new regression tests in apps/backend/tests/test_durable_scheduler.py register jobs on one scheduler, load them on a second, independent scheduler instance backed by the same on-disk SQLite store (simulating a real restart), and invoke the resulting job.func(*job.args, **job.kwargs) directly — exactly what apscheduler.executors.base.run_job does. Verified both tests fail with the exact production TypeError against the pre-fix code and pass against the fix; no prior test exercised this path since the rest of the suite runs with SCHEDULER_JOB_STORE=memory precisely to avoid sharing APScheduler's own table across tests.

</details>

**Backend (API), MCP Server, Web Application**

<a id="remove-cloudflare-backend-mcp-fix-psycopg"></a>

### Fixed: Removed the Cloudflare Containers deploy config for backend/MCP (Render is the actual deployment path now) and fixed a real bug where a standard postgresql:// connection string (what Supabase/Neon/Railway hand you by default) crashed the app on startup instead of connecting.

*2026-08-07* — verification: automated tests: passed; production observation: observed

Pasting a standard Postgres connection string (Supabase, Neon, Railway, etc.) as DATABASE_URL now works without any manual edit. No change for anyone already using the +psycopg form.

<details><summary>Technical detail</summary>

apps/backend/wrangler.toml, apps/backend/cf-worker/, apps/mcp/wrangler.toml, apps/mcp/cf-worker/, and the Node/TS deploy tooling (package.json/package-lock.json/tsconfig.json) for both were deleted entirely, along with .github/workflows/deploy-backend.yml and deploy-mcp.yml — not just disabled. Confirmed via a real deploy that Cloudflare Containers requires the Workers Paid plan; Render (see render-deployment.md) is the deployment path actually in use. apps/mcp/Dockerfile is kept — Render's render.yaml references it too.
app/config.py's Settings.database_url gained a validator (_require_psycopg_driver) that rewrites a bare postgresql:// or postgres:// URL to postgresql+psycopg://. Without it, a standard connection string (exactly what Supabase's dashboard gives you to copy-paste) makes SQLAlchemy default to the psycopg2 driver, which isn't installed — the failure is a ModuleNotFoundError deep inside Alembic's env.py on container startup, with nothing pointing at the actual cause. Hit this exact failure in a real deployment attempt, not found by inspection.

</details>

**MCP Server, Local CLI**

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

**MCP Server**

<a id="mcp-oauth-discovery"></a>

### Fixed: The remote MCP server now advertises where to authenticate, so an OAuth client (like Claude.ai's connector UI) can find the backend's authorization server instead of failing to register with no useful error.

*2026-08-07* — verification: automated tests: passed; artifact build: passed; production observation: observed

An OAuth-capable MCP client can now discover LensWord's sign-in service automatically when connecting to the remote MCP server, instead of failing with no actionable error.

<details><summary>Technical detail</summary>

apps/mcp/lensword_mcp/http_transport.py's StreamableHTTPMCPServer gained an oauth_issuer parameter (wired to the existing LENSWORD_API_URL — no new setting to keep in sync). With it set: GET /.well-known/oauth-protected-resource returns RFC 9728 metadata naming the backend as authorization_servers (the backend already implements the full authorization server at apps/backend/app/api/routers/mcp_oauth.py — dynamic client registration, authorize, token, revoke — behind REMOTE_MCP_ENABLED; this MCP server never implemented any OAuth surface itself, by design, since RFC 9728 treats resource and authorization server as distinct roles). A 401 for a missing bearer token now also carries a WWW-Authenticate: Bearer resource_metadata="..." header, which is how a spec-compliant client finds the metadata endpoint without being told the URL out of band. Both are no-ops (old behavior exactly, bare 401/404) when oauth_issuer is unset, and server.py now always passes it (LENSWORD_API_URL is already a required setting for the http transport, so this is not a new requirement). Found by a real connection attempt from an OAuth-based MCP client against a deployed instance, not by inspection — the client's connector UI reported "Couldn't register with LensWord's sign-in service," which traced back to exactly this missing discovery metadata. Verified against a real running Docker container (curl against both the new endpoint and the 401 header), not just unit tests.

</details>

**Known limitations:**
- Still not verified against a real, successful end-to-end OAuth flow with a third-party client (authorize -> consent -> token exchange -> an actual tool call) — this fix addresses the discovery step specifically, which is as far as the real attempt that found the gap got.

**MCP Server**

<a id="mcp-http-keepalive-body-drain"></a>

### Fixed: A misdirected request to the remote MCP server (e.g. an OAuth client trying to register at the wrong URL) no longer corrupts the next request on the same connection with a garbled, confusing 501 error.

*2026-08-07* — verification: automated tests: passed; production observation: observed

A misbehaving or exploring client (an OAuth registration attempt, another server's health check, anything hitting a path other than /mcp) gets a clean 404 and the connection keeps working normally, instead of corrupting whatever request comes after it.

<details><summary>Technical detail</summary>

apps/mcp/lensword_mcp/http_transport.py's do_POST checked the request path, Origin, and bearer token — and returned an error for any of them — before ever reading the request body off the socket (self.rfile.read(length)). On this HTTP/1.1 keep-alive server (protocol_version = "HTTP/1.1"), an early-return response left the unread body bytes sitting in the socket buffer. The next request sent on that same connection had its request line corrupted by those leftover bytes, producing exactly the failure a real Claude.ai connection attempt hit in production: a POST carrying an RFC 7591 dynamic-client-registration payload to this server's root path (not /mcp, since this server is the OAuth *resource*, not the *authorization server* — see mcp-oauth-discovery.yml) got its intended 404, but the undrained body corrupted the client's follow-up request into `Error code: 501 / Message: Unsupported method ('{"redirect_uris":[...]} GET')` — the leftover JSON body text glued to the next request's "GET". Fixed by resolving Content-Length and reading the full body (or deliberately closing the connection) before any other check can early-return: a missing/invalid Content-Length or an oversized body (over MAX_HTTP_BODY_BYTES) now sets self.close_connection = True instead of leaving an unreadable-length or deliberately-undrained body on a connection marked for reuse. A regression test opens one real http.client.HTTPConnection, sends a POST to the wrong path, then sends a second request on the *same* connection and asserts it gets a clean response rather than a stdlib 501 from a corrupted request line.

</details>

**Known limitations:**
- This fixes the connection-corruption symptom, not the underlying reason an OAuth client ends up POSTing registration to this server's root path in the first place (most likely because the backend authorization server was unreachable at the time — see render-supabase-ipv4-pooler-fix.yml — so the client fell back to guessing an endpoint on the resource server's own origin). A reachable, correctly-discoverable authorization server remains the real fix for that flow to succeed at all.

**Web Application, Desktop Application, Browser Extension, MCP Server, Local CLI**

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

**Web Application, Desktop Application, Browser Extension**

<a id="lensword-brand-identity"></a>

### Added: LensWord has a canonical logo and icon set for the first time — a favicon in the web app, real desktop app icons, and a real browser extension icon, replacing generic/unbranded placeholders.

*2026-08-07* — verification: automated tests: passed; artifact build: passed

The web app now has a real favicon and social-preview image, the desktop app has a real icon instead of Tauri's default, and the browser extension shows a real icon in the toolbar and extensions page instead of nothing.

<details><summary>Technical detail</summary>

Original SVG mark (lens + word-line) in brand/logo/svg/, with a reproducible generation script (scripts/generate-brand-assets.py) that derives every PNG/WebP/ICO/ICNS raster asset from the vector sources. Wired into apps/frontend's favicon/Open Graph tags, apps/desktop's Tauri icon set (replacing the default Tauri-generated placeholder), and apps/browser's manifest icons/action.default_icon (previously unset — the extension had no working icon at all, since MV3 doesn't accept SVG for that field).

</details>

**Known limitations:**
- Desktop icon change was not visually re-verified on a packaged installer (none has ever been built) — confirmed only that the icon files exist at the correct paths/sizes referenced by tauri.conf.json.

References: [#270](https://github.com/conectlens/lensword/issues/270), [PR #291](https://github.com/conectlens/lensword/pull/291)

**Web Application**

<a id="fix-frontend-api-url-validation"></a>

### Fixed: Fixed a bug where a scheme-less VITE_API_URL silently sent every API request to the wrong place instead of failing clearly.

*2026-08-07* — verification: automated tests: passed; production observation: observed

A misconfigured API URL now fails immediately with a clear error instead of silently sending every request to the wrong place with a confusing 405/404.

<details><summary>Technical detail</summary>

apps/frontend/src/lib/runtimeConfig.ts's browser-path fallback used VITE_API_URL as-is with no validation. A value missing its http(s):// scheme (e.g. "lensword-api.conectlens.com" instead of "https://lensword-api.conectlens.com") doesn't fail the build — every fetch() call silently treats it as a relative path and resolves it against the page's own origin. Caught this exact way in production: real requests going to https://lensword.conectlens.com/lensword-api.conectlens.com/api/v1/... and failing with a confusing 405, with nothing pointing at the actual misconfigured environment variable. Added an explicit check (assertAbsoluteHttpUrl) that throws a specific, actionable error at first use instead.

</details>

**Desktop Application, Web Application, Backend (API)**

<a id="fix-desktop-build-and-selfhost-env-gaps"></a>

### Fixed: Fixed a desktop-installer build failure (never previously exercised by a real CI run) and a docker-compose self-hosting gap where Ollama/AI and remote-MCP settings couldn't be configured via .env.

*2026-08-07* — verification: automated tests: passed

A CI-built desktop installer (either release channel) now actually builds instead of failing during the frontend-embedding step. Cloudflare deploy workflows no longer fail on an npm peer-dependency conflict before ever reaching the actual deploy step. docker-compose-based self-hosters can now turn on local AI/Ollama suggestions or the remote MCP transport by setting a value in .env, without editing docker-compose.yml directly.

<details><summary>Technical detail</summary>

apps/desktop/src-tauri/tauri.conf.json's beforeBuildCommand used ../../frontend, which is only correct if Tauri executes it relative to the config file's own directory (src-tauri/). It does not — it executes relative to wherever `tauri build` was invoked from (apps/desktop, per CONTRIBUTING.md's documented flow and this project's own tauri-action projectPath), where the correct relative path is one level up (../frontend), not two. Confirmed both the bug and the fix by actually running `npx @tauri-apps/cli@2 build` locally: before the fix, the documented beforeBuildCommand path resolved to a nonexistent sibling directory outside the repo (`<repo-root>/frontend` instead of `<repo-root>/apps/frontend`) and failed with a misleading "no package-lock.json" error from npm; after the fix, the frontend build step inside `tauri build` completes and the Rust build proceeds. This had never been caught because no tag was ever pushed to trigger release.yml, and the desktop CI job (ci.yml) only runs `cargo check`, which doesn't exercise beforeBuildCommand at all.
Separately, docker-compose.yml's backend service environment: block passed through DATABASE_URL/SECRET_KEY/CORS_ORIGINS/FIRST_ADMIN_* but not AI_PROVIDER/OLLAMA_MODEL/OLLAMA_BASE_URL or REMOTE_MCP_ENABLED/MCP_ISSUER_URL, even though the root .env.example's own header comment claimed "anything set there can also be passed through" — for those specific settings, that claim was false. Added the missing passthroughs (with the same working defaults as apps/backend/.env.example) to docker-compose.yml, and documented them in the root .env.example with a pointer to docs/install/local-ai-ollama.md's Docker-specific OLLAMA_BASE_URL guidance (`localhost` inside the container is not the host machine). Also pinned cloudflare/wrangler-action's wranglerVersion to 4.120.0 in the three deploy-*.yml workflows added in #310 — the action's own default (observed via a real failed CI run: 4.86.0) has a @cloudflare/workers-types peer-dependency conflict with the version this project's package.json already installs (^5.x).

</details>

**Known limitations:**
- The desktop build fix was verified up through the frontend-embedding step (beforeBuildCommand completing successfully); the full native Rust/Tauri compilation and installer packaging was not run to completion in this environment (no signing certificates, and a full release build takes longer than was practical to wait out here) — CI is the real gate for that, and this fix directly addresses the exact failure a real CI run on main just produced.
- docker-compose.yml still doesn't pass through the RATE_LIMIT_* or DB_POOL_SIZE/DB_MAX_OVERFLOW/LOG_LEVEL/DB_ECHO/SCHEDULER_JOB_STORE settings — deliberately scoped to the ones a self-hoster is actually likely to want to change (AI/Ollama, remote MCP), not a full mirror of every backend setting; the root .env.example says so explicitly and points at apps/backend/.env.example for the rest.

**Desktop Application**

<a id="desktop-production-default-and-continuous-release"></a>

### Added: A desktop installer built by CI (either release channel) now defaults to the hosted production API instead of a local loopback address, and a new automatic "continuous build" channel publishes an always-current desktop build on every push to main.

*2026-08-07* — verification: automated tests: passed

A LensWord Desktop installer downloaded from GitHub now works against the real hosted service out of the box, with no configuration step, instead of only working once a local backend is also running. A new "Continuous Build" release (tag desktop-continuous, marked prerelease) reflects the current tip of main and updates automatically; the existing desktop-v* tagged-release channel is unchanged in behavior beyond also getting this same production default.

<details><summary>Technical detail</summary>

apps/desktop/api-config/src/lib.rs's DEFAULT_API_BASE is now resolved via option_env!("LENSWORD_RELEASE_API_BASE") at compile time, falling back to the existing http://127.0.0.1:8000 literal when unset. Only CI release builds set that variable (.github/workflows/build-desktop-installers.yml, a new reusable workflow extracted from release.yml's original single-file form so release.yml and the new release-continuous.yml share identical packaging/signing logic rather than risking drift between two copies). cargo build/cargo tauri dev never set it, so local development is unaffected — verified by running the existing 25-test suite unchanged, then re-running with LENSWORD_RELEASE_API_BASE set and confirming the one test that hardcodes the loopback literal fails for exactly the expected reason (the compiled constant genuinely changed). The runtime LENSWORD_API_URL env var and api-endpoint config file both still outrank the compiled-in default either way, so a downloaded installer remains fully self-hostable. release-continuous.yml triggers on push to main (path-filtered to apps/desktop and apps/frontend), deletes and recreates a rolling `desktop-continuous` GitHub prerelease each time via `gh release delete` before invoking the shared reusable workflow — chosen specifically to avoid depending on unverified behavior of tauri-action's own handling of re-publishing to an already-existing tag.

</details>

**Known limitations:**
- Not verified end to end against a real deploy — the production API (lensword-api.conectlens.com) this defaults to did not exist as a live service when this was written (see the Cloudflare deployment PR); a downloaded installer using the new default won't actually reach a server until that's deployed.
- release-continuous.yml itself has not run for real (no push to main happened from this session) — the reusable workflow it calls is verified only by inspection and by the fact that release.yml's unchanged packaging/signing steps already work; the new delete-then-recreate rolling-release step is untested against a live GitHub Releases API.

**Desktop Application**

<a id="desktop-linux-appindicator-build-dep"></a>

### Fixed: The Linux desktop installer (AppImage/.deb/.rpm) build no longer fails — it was missing a required system tray dependency.

*2026-08-07* — verification: production observation: observed

Linux users get an actual AppImage/.deb/.rpm from the release/continuous build pipeline again, instead of the build job failing after a full ~5-minute compile with no artifacts produced.

<details><summary>Technical detail</summary>

A real run of the desktop-installer build workflow (build-desktop-installers.yml, ubuntu-latest) panicked during bundling: `Can't detect any appindicator library`. The Rust build itself succeeded (this app uses a system tray — see apps/frontend/src/lib/tray.ts/useTraySync); the panic is inside tauri-cli's bundler, which does its own pkg-config-based lookup for a tray/appindicator library at bundle time, separate from plain compilation — which is why ci.yml's "Desktop shell (Rust, ubuntu-latest)" job (cargo check/test/clippy only, no `tauri build` bundle step) never hit this. Added libayatana-appindicator3-dev to this workflow's apt-get install list, matching Tauri's own documented Linux prerequisites for tray-icon support.

</details>

**Known limitations:**
- Not verified against a real completed CI run of this workflow yet (the fix is a one-line apt-get addition matching Tauri's documented Linux dependency list, not something reproducible in this sandbox, which has no Tauri/GTK toolchain) — verify on the next release-continuous run.

**Web Application, Desktop Application**

<a id="desktop-fonts-blocked-by-csp"></a>

### Fixed: The desktop app's icons and headings now render correctly. They were invisible/wrong before: the Material Symbols icon font failed to load, so icon ligatures (e.g. "translate") showed as literal words instead of glyphs.

*2026-08-07* — verification: automated tests: passed; artifact build: passed; production observation: observed

Desktop app users see real icons and the intended headings/body font instead of literal icon-name text and a system font fallback. No change for web app users (Cloudflare Pages), who never hit this.

<details><summary>Technical detail</summary>

apps/frontend loaded Montserrat, Poppins, and Material Symbols Outlined from fonts.googleapis.com/fonts.gstatic.com via a <link> in index.html. The web build has no CSP and never showed a problem. The Tauri desktop shell's CSP (apps/desktop/src-tauri/tauri.conf.json: style-src 'self' 'unsafe-inline'; font-src 'self' data:) blocks both origins outright, so in the desktop build the stylesheet link and the font files behind it silently failed to load. Text fell back to a system sans-serif (headings/ body, easy to miss) and Material Symbols' ligature spans fell back to rendering their literal name text (e.g. "translate" — visually obvious, reported by a real screenshot of the register page). Fixed by self-hosting instead of loosening the CSP: apps/frontend/public/fonts now carries Montserrat (single variable-weight file, Latin unicode-range), Poppins (four static weights, Latin), and a glyph-subsetted Material Symbols Outlined file containing only the icon names src/ actually references (see components/ui/Icon.tsx callers) — 257KB static, vs 3.85MB for the full variable-axis font, since the app never toggles Icon's `filled` prop to true anywhere today. @font-face rules added to src/index.css; the Google Fonts <link>/preconnect tags removed from index.html. font-src/style-src 'self' already covers same-origin files, so no CSP change was needed or made — self-hosting fixes both build targets from one source without loosening either one's security policy.

</details>

**Known limitations:**
- Montserrat/Poppins are self-hosted Latin-only (matching the weights already in use); non-Latin UI text (there isn't any in this app's chrome today) would fall back to the `sans-serif` stack rather than these fonts specifically.
- The Material Symbols subset only contains the icon names in use as of this fix. Adding a new `<Icon name="...">` value requires regenerating apps/frontend/public/fonts/material-symbols-outlined.woff2 the same way (fonts.googleapis.com/css2?family=Material+Symbols+Outlined&text=...) or it will silently render as literal text again, same failure mode.

**Browser Extension**

<a id="browser-notification-icon-fix"></a>

### Fixed: Capture notifications ("Saved to LensWord", error notifications) now show the LensWord icon instead of a broken image.

*2026-08-07* — verification: not verified

Every capture notification (success or failure) now renders with a real icon instead of a missing-image placeholder.

<details><summary>Technical detail</summary>

service-worker.js's three chrome.notifications.create() calls referenced iconUrl: 'icon.svg'. Chrome's notifications API does not support SVG icons (confirmed against Chrome's own extension documentation and a matching real-world "Unable to download all specified images" bug report). Fixed to reference icons/icon48.png, the PNG icon set added by the brand-assets work.

</details>

**Known limitations:**
- Not confirmed by loading the extension into a real Chrome instance and observing a live notification — chrome:// pages could not be driven by this documentation session's browser automation. Fix is based on Chrome's documented SVG limitation plus a matching reported failure, not a directly observed broken/fixed notification.

References: [#275](https://github.com/conectlens/lensword/issues/275), [PR #299](https://github.com/conectlens/lensword/pull/299)

Also see [Main Branch Activity](/reference/changelog/main-branch-activity) — what's merged but not yet part of any release, and [Releases](/reference/releases/) — published, immutable release records (none exist yet).

## No changelog entry

Changes reviewed and confirmed to have no user-observable effect (internal-only, CI-only, docs-only) — see [CONTRIBUTING.md](https://github.com/conectlens/lensword/blob/development/CONTRIBUTING.md) for the fragment policy. Listed here for reviewer visibility, not rendered on any product's changelog page.

| Date | Products | Reason | References |
|---|---|---|---|
| 2026-08-08 | Backend (API) | Adds server-side logging only (which specific check inside token exchange rejected a request) — no change to any response, status code, or behavior a client observes. Needed because Render's access logs show only method/path/status, not enough to diagnose a real Claude.ai connection's POST /token 400 with the generic invalid_grant detail shared across several distinct causes. | — |
| 2026-08-07 | Backend (API), MCP Server | Corrects docs/internal/render-deployment.md's Supabase connection-string guidance, which was wrong in a way that broke a real deploy. No application code changed — the fix is which connection string an operator pastes into Render's dashboard, not anything this repo runs. | — |
| 2026-08-07 | Backend (API), MCP Server | Adds a free deployment path (Render.com) for backend/MCP as an alternative to Cloudflare Containers, which requires the Workers Paid plan (confirmed by a real "Unauthorized" failure against a Free-plan account). No application code changed — deploy tooling and docs only. The Cloudflare Containers workflows are disabled from auto-triggering (manual-only now) rather than removed. | — |
| 2026-08-07 | Web Application, Desktop Application, Browser Extension, MCP Server, Local CLI, Backend (API) | Adds CI enforcement (registry validation, fragment schema, product-impact detection, generation idempotency) for the changelog/release-transparency system #281 introduced. No product's runtime behavior changes — this is contributor-workflow and CI tooling only. | [#282](https://github.com/conectlens/lensword/issues/282) |
| 2026-08-07 | Web Application, Desktop Application, Browser Extension, MCP Server, Local CLI | Adds automated documentation QA (route/link integrity, code-block syntax, media size/secret scanning, accessibility smoke test) and fixes two broken-anchor bugs and one accessibility contrast issue the new tooling found. No product's runtime behavior changes. | [#283](https://github.com/conectlens/lensword/issues/283) |
| 2026-08-07 | Web Application, Backend (API), MCP Server | Adds Cloudflare deployment infrastructure (Dockerfile, wrangler.toml, GitHub Actions workflows) for web (Pages), backend (Containers), and the MCP server's remote transport (Containers). No application code changed — this is deploy tooling only, and nothing deploys automatically until the required Cloudflare secrets are configured (see docs/internal/cloudflare-deployment.md). | — |
