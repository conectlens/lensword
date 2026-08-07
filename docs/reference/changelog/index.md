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
| 2026-08-07 | Web Application, Desktop Application, Browser Extension, MCP Server, Local CLI, Backend (API) | Adds CI enforcement (registry validation, fragment schema, product-impact detection, generation idempotency) for the changelog/release-transparency system #281 introduced. No product's runtime behavior changes — this is contributor-workflow and CI tooling only. | [#282](https://github.com/conectlens/lensword/issues/282) |
| 2026-08-07 | Web Application, Desktop Application, Browser Extension, MCP Server, Local CLI | Adds automated documentation QA (route/link integrity, code-block syntax, media size/secret scanning, accessibility smoke test) and fixes two broken-anchor bugs and one accessibility contrast issue the new tooling found. No product's runtime behavior changes. | [#283](https://github.com/conectlens/lensword/issues/283) |
