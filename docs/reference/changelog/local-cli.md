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
