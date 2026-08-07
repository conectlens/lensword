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
| Local CLI | unreleased | [Local CLI changelog](/reference/changelog/mcp) |

The shared backend (`apps/backend`) is not an independently released product — see [docs/internal/repo-audit.md](https://github.com/conectlens/lensword/blob/development/docs/internal/repo-audit.md). Its changes are folded into whichever product(s) they actually affect, listed below.

## Latest changes, all products

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
| 2026-08-07 | Backend (API), MCP Server | Corrects docs/internal/render-deployment.md's Supabase connection-string guidance, which was wrong in a way that broke a real deploy. No application code changed — the fix is which connection string an operator pastes into Render's dashboard, not anything this repo runs. | — |
| 2026-08-07 | Backend (API), MCP Server | Adds a free deployment path (Render.com) for backend/MCP as an alternative to Cloudflare Containers, which requires the Workers Paid plan (confirmed by a real "Unauthorized" failure against a Free-plan account). No application code changed — deploy tooling and docs only. The Cloudflare Containers workflows are disabled from auto-triggering (manual-only now) rather than removed. | — |
| 2026-08-07 | Web Application, Desktop Application, Browser Extension, MCP Server, Local CLI, Backend (API) | Adds CI enforcement (registry validation, fragment schema, product-impact detection, generation idempotency) for the changelog/release-transparency system #281 introduced. No product's runtime behavior changes — this is contributor-workflow and CI tooling only. | [#282](https://github.com/conectlens/lensword/issues/282) |
| 2026-08-07 | Web Application, Desktop Application, Browser Extension, MCP Server, Local CLI | Adds automated documentation QA (route/link integrity, code-block syntax, media size/secret scanning, accessibility smoke test) and fixes two broken-anchor bugs and one accessibility contrast issue the new tooling found. No product's runtime behavior changes. | [#283](https://github.com/conectlens/lensword/issues/283) |
| 2026-08-07 | Web Application, Backend (API), MCP Server | Adds Cloudflare deployment infrastructure (Dockerfile, wrangler.toml, GitHub Actions workflows) for web (Pages), backend (Containers), and the MCP server's remote transport (Containers). No application code changed — this is deploy tooling only, and nothing deploys automatically until the required Cloudflare secrets are configured (see docs/internal/cloudflare-deployment.md). | — |
