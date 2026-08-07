---
title: Web Application Changelog
description: User-facing changes to Web Application, with verification evidence per entry.
---

# Web Application changelog

Status — Web Application: **unreleased**.

Every entry states exactly what was verified — a passing automated test does not imply a platform was manually checked, and a manual check on one OS does not imply another. See [Verification levels](/reference/trust/verification-levels) for what each status means.

<a id="mcp-oauth-consent-page-and-remote-workspace"></a>

### Fixed: Connecting a remote MCP client (like Claude.ai) to a LensWord account now actually works end to end — it previously failed on every attempt with "Could not validate credentials."

*2026-08-08* — verification: automated tests: passed; production observation: observed

Connecting Claude.ai (or any other OAuth-based MCP client) to a LensWord account now completes successfully — login, consent, and the handoff back to the connector all work, instead of failing at the first step with no actionable error.

<details><summary>Technical detail</summary>

Two compounding bugs, both found by tracing a real Claude.ai connection attempt through to a live backend rather than by inspection. (1) The authorization-server metadata's `authorization_endpoint` advertised this backend's own GET/POST /api/v1/mcp/oauth/authorize — a Bearer-token JSON API — as the URL a connector should open in the user's browser. A browser navigation never attaches a custom Authorization header, so `current_user` could never resolve and every real attempt failed with "Could not validate credentials"; no frontend page existed anywhere to intercept that URL, log the user in, and call the API with their stored token on their behalf (the backend router's own docstring described that page's existence without it ever having been built). Fixed on both ends: apps/frontend/src/features/mcp/ OAuthAuthorizePage.tsx is that missing page (new route /oauth/authorize in App.tsx, not wrapped in ProtectedRoute since it must not carry the app's nav shell) — it redirects to /login?next=<this URL> when logged out (LoginPage.tsx now honors `next`, validated against open-redirect via a same-origin-relative-path check), otherwise fetches the consent preview, renders the requesting client's name and scopes, and on approve/deny POSTs the decision and does a hard `window.location.href` navigation to the returned redirect_uri (an external callback URL, not a route this app owns). Settings.mcp_consent_url (app/config.py) is the new authorization_endpoint value; must be set to this deployment's real frontend origin + /oauth/authorize (render.yaml: MCP_CONSENT_URL). (2) Even reaching that endpoint, the request still failed: GET/POST /authorize required a `workspace` parameter that no external OAuth client sends (Claude.ai's redirect carries RFC 8707's `resource` instead, which this app never read), and workspace was validated by is_valid_workspace as an absolute POSIX filesystem path — a concept built for the desktop companion's local-directory sandboxing, meaningless for a remote, browser-only connector with no filesystem access. workspace is now optional on both endpoints, defaulting server-side to the new Settings.mcp_remote_workspace, and is_valid_workspace accepts that one configured value as a deliberate special case alongside its existing absolute-path rule (app/api/routers/ mcp.py). This value must equal the deployed remote MCP resource server's own LENSWORD_MCP_WORKSPACE exactly, the same way mcp_issuer_url must match that service's LENSWORD_API_URL — the resource server presents this string on every tool-invocation request, and a grant recorded under a different value would never match it (render.yaml: MCP_REMOTE_WORKSPACE, kept identical to lensword-mcp's existing LENSWORD_MCP_WORKSPACE).

</details>

**Known limitations:**
- The `resource` parameter Claude.ai's redirect includes (RFC 8707) is still not read or validated against — this fix addresses the concrete failure that blocked every connection attempt, not full RFC 8707 resource-indicator enforcement.

<a id="remove-cloudflare-backend-mcp-fix-psycopg"></a>

### Fixed: Removed the Cloudflare Containers deploy config for backend/MCP (Render is the actual deployment path now) and fixed a real bug where a standard postgresql:// connection string (what Supabase/Neon/Railway hand you by default) crashed the app on startup instead of connecting.

*2026-08-07* — verification: automated tests: passed; production observation: observed

Pasting a standard Postgres connection string (Supabase, Neon, Railway, etc.) as DATABASE_URL now works without any manual edit. No change for anyone already using the +psycopg form.

<details><summary>Technical detail</summary>

apps/backend/wrangler.toml, apps/backend/cf-worker/, apps/mcp/wrangler.toml, apps/mcp/cf-worker/, and the Node/TS deploy tooling (package.json/package-lock.json/tsconfig.json) for both were deleted entirely, along with .github/workflows/deploy-backend.yml and deploy-mcp.yml — not just disabled. Confirmed via a real deploy that Cloudflare Containers requires the Workers Paid plan; Render (see render-deployment.md) is the deployment path actually in use. apps/mcp/Dockerfile is kept — Render's render.yaml references it too.
app/config.py's Settings.database_url gained a validator (_require_psycopg_driver) that rewrites a bare postgresql:// or postgres:// URL to postgresql+psycopg://. Without it, a standard connection string (exactly what Supabase's dashboard gives you to copy-paste) makes SQLAlchemy default to the psycopg2 driver, which isn't installed — the failure is a ModuleNotFoundError deep inside Alembic's env.py on container startup, with nothing pointing at the actual cause. Hit this exact failure in a real deployment attempt, not found by inspection.

</details>

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

<a id="fix-frontend-api-url-validation"></a>

### Fixed: Fixed a bug where a scheme-less VITE_API_URL silently sent every API request to the wrong place instead of failing clearly.

*2026-08-07* — verification: automated tests: passed; production observation: observed

A misconfigured API URL now fails immediately with a clear error instead of silently sending every request to the wrong place with a confusing 405/404.

<details><summary>Technical detail</summary>

apps/frontend/src/lib/runtimeConfig.ts's browser-path fallback used VITE_API_URL as-is with no validation. A value missing its http(s):// scheme (e.g. "lensword-api.conectlens.com" instead of "https://lensword-api.conectlens.com") doesn't fail the build — every fetch() call silently treats it as a relative path and resolves it against the page's own origin. Caught this exact way in production: real requests going to https://lensword.conectlens.com/lensword-api.conectlens.com/api/v1/... and failing with a confusing 405, with nothing pointing at the actual misconfigured environment variable. Added an explicit check (assertAbsoluteHttpUrl) that throws a specific, actionable error at first use instead.

</details>

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
