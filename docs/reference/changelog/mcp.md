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
