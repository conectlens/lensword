# LensWord Repository Audit — Documentation Architecture Foundation

> Internal, non-user-facing evidence record. Written for issue #269, the
> foundation of the documentation rewrite epic (#268). Every claim below is
> backed by a file path, command output, or GitHub API result gathered
> against branch `issue-269-doc-architecture-audit` on 2026-08-07. Where
> evidence was unavailable, that is stated explicitly rather than assumed.

## 1. Repository structure & products

The repository is not an npm/monorepo workspace — there is no root
`package.json`. Each product lives under `apps/*` and manages its own
dependencies and versioning independently.

### Product boundaries

| Surface | Path | Public product? | Source of truth for version | CI coverage | Release channel |
|---|---|---|---|---|---|
| Backend (API) | `apps/backend` | **No — shared implementation dependency**, not an independently distributed product. Every other surface depends on it; it has no CLI/GUI of its own and no standalone release channel. | Not versioned (no `version=` on the FastAPI app, no `VERSION` file, no `pyproject.toml`) | `backend`, `backend-postgres`, `docker-build` jobs in `.github/workflows/ci.yml` | Docker image built in CI, never pushed to a registry (`push: false`) |
| Web Application | `apps/frontend` | **Yes** — the real, working, publicly usable surface | `apps/frontend/package.json` (`"version": "0.1.0"`) | `frontend` job (lint/build/test) + `docker-build` | Docker image only, not pushed to a registry |
| Desktop Application | `apps/desktop` | Built and CI-tested, but **unreleased** — README states plainly "No release has been published yet"; confirmed independently (`git tag -l` and `gh release list` both empty) | `apps/desktop/Cargo.toml` / `src-tauri/tauri.conf.json` (`"0.1.0"`) | `desktop` job — **macOS + Linux only, no Windows leg** in CI (Windows is only built in `release.yml`, which has never run against a real tag) | `release.yml` on `v*` tags → draft GitHub Release, unsigned by default; no tag has ever been pushed |
| Browser Extension | `apps/browser` | Real and functional, but **dev-tool maturity** — install is "Load unpacked" only | `apps/browser/manifest.json` (`"version": "0.1.0"`) | **None** — no workflow references `apps/browser` | None — not published to the Chrome Web Store |
| MCP Server + local CLI | `apps/mcp` | Functionally the most complete "extra" surface (real OAuth+PKCE, tenant isolation), but **not distributed** | `apps/mcp/pyproject.toml` (`"0.1.0"`) | **None** — no workflow references `apps/mcp`, despite it having its own `tests/` suite | None — not published to PyPI, source install only |

**Decision for the documentation architecture**: the backend is documented as
the shared server underneath Web/Desktop/Browser/MCP, not as a sixth
"product" with its own top-level use-case guide. Five canonical
user-facing/installable surfaces exist: **Web, Desktop, Browser Extension,
MCP Server, Local CLI** (the CLI is a distinct entry point of the `apps/mcp`
package — `lensword` vs. `lensword-mcp` — and deserves its own doc section
since its risk profile is different: `import-context` is offline/read-only
by design).

### Independent version strings

Every versioned artifact currently reads `0.1.0`, set independently per
package (frontend, desktop, browser, MCP). There is no shared/coordinated
versioning scheme today. No git tags and no GitHub Releases exist. This is
the reason the release-transparency system (#281) cannot assume a single
project-wide version — it must be product-aware from day one.

## 2. Existing docs inventory

| File | Verdict | Disposition |
|---|---|---|
| `README.md` | Current, unusually rigorous (explicitly separates verified vs. unverified claims). Too long and mixes onboarding with internal design notes. | Split: concise use-case-first hub (→ #271) + deep content moves into VitePress docs (→ #272). |
| `CHANGELOG.md` | Current, Keep-a-Changelog format, one large `[Unreleased]` section, no real tagged releases yet. | Feeds the product-aware changelog system (#281). Keep as-is until #281 lands. |
| `ROADMAP.md` | Current and cross-referenced against ADRs/code. Contains a broken link to `docs/memory-loop-verification.md` (does not exist). | Keep. Fix the broken link as part of this issue's migration map (see below) or #271, whichever touches it first. |
| `CONTRIBUTING.md` | **Stale** — "Project layout" section only documents `apps/backend`/`apps/frontend`; omits `apps/desktop`, `apps/browser`, `apps/mcp` even though a desktop dev-setup subsection exists later in the same file. | Correct in a follow-up; out of scope for #269 itself (flagged here as an evidence gap for whoever owns CONTRIBUTING next). |
| `CODE_OF_CONDUCT.md`, `SECURITY.md`, `LICENSE` | Current, standard OSS scaffolding. `SECURITY.md`'s "known limitations" section may be slightly stale versus later rate-limiting work in CHANGELOG — worth a cross-check pass by whoever next edits it. | Keep. |
| `docs/releasing.md` | Current, honest — states plainly no installer has ever been run on any OS. | Keep as the canonical desktop release/verification reference (→ #274). |
| `docs/hosted-deployment.md` | Current, rigorous self-hosting guide with a real migration-verification writeup. | Canonical source for the self-hosting guide (→ #273); do not duplicate its content, link to it. |
| `docs/mcp-remote-transport.md` | Current, detailed remote MCP OAuth/transport reference. | Canonical source for MCP remote-transport docs (→ #276). |
| `docs/ai-model-verification.md` | Current, valuable **evidence record** (dated real-model verification runs). Internal/QA in nature, not onboarding material. | Preserve as historical/architectural record — do not fold into user-facing guides; link from a "verification" or "trust" page instead. |
| `docs/adr/0001`–`0009` | All current and still govern real architectural decisions (Tauri choice, desktop remote-only mode, AI provider audit, memory scheduling, semantic relatedness scope, AI Learning Diagnosis architecture, AI Companion architecture, domain-neutral kernel). | Preserve all. Link the relevant ADR from each use-case guide that depends on its decision (e.g., ADR 0002 from the desktop guide, ADR 0008 from the MCP guide). |
| `apps/browser/README.md`, `apps/mcp/README.md` | Current, accurate, minimal. | Keep as developer-facing quick references; the use-case guides (#275, #276) are the user-facing counterparts, not replacements. |

**Broken link found**: `docs/memory-loop-verification.md` is referenced by
both `README.md` and `ROADMAP.md` but does not exist anywhere in the
repository. This must be either restored (if the content exists elsewhere
under a different name) or repointed/removed during the README rewrite
(#271).

**No `docs/internal/` directory existed before this issue** — this audit is
its first occupant, per the issue's own instruction.

## 3. Use-case map

| Use case | Supported today? | Owning surface | Prerequisites | Known limitations |
|---|---|---|---|---|
| Learn/review vocabulary in a browser | Yes | Web Application (`apps/frontend`) | Backend reachable (bundled via Docker Compose) | None significant — most complete, CI-tested surface |
| Self-host LensWord for yourself or a team | Yes, with caveats | Web Application + Backend, via `docker-compose.yml` or `docs/hosted-deployment.md` | Postgres, a real `SECRET_KEY` | Notifications are log-only (no real email/push provider); rate limiting is per-instance, not shared across a multi-instance deployment |
| Use LensWord as a desktop application | Buildable from source only | Desktop (`apps/desktop`) | Rust toolchain, a **running remote server** (remote-only per ADR 0002 — no bundled backend) | No installer has ever been published; CI builds macOS+Linux only; native notifications are unit-tested but never observed on a real OS (blocked on open issue #65) |
| Capture selected words from a webpage | Yes, developer-mode only | Browser Extension (`apps/browser`) | Manual "Load unpacked"; API URL, bearer token, group ID entered by hand | Not published to the Chrome Web Store; zero CI coverage; v1 scope is hardcoded to Spanish, no translations |
| Connect Claude, Codex, Cursor, or another MCP client | Yes for local stdio; remote exists but is off by default | MCP Server (`apps/mcp`, `lensword-mcp` entry point) | `LENSWORD_API_URL`, `LENSWORD_TOKEN`, `LENSWORD_MCP_REQUESTER`, `LENSWORD_MCP_WORKSPACE`; remote additionally needs `REMOTE_MCP_ENABLED=true` on the backend plus two more env vars on the MCP process | Not on PyPI (source install only); no CI coverage; remote transport has no live interop test against a real third-party MCP host |
| Preview/import developer context via local CLI | Yes, and safe by design | Local CLI (`apps/mcp`, `lensword` entry point, `import-context` subcommand) | Local Python install of `apps/mcp` | `import-context` is read-only/offline (never writes, never contacts the backend, redacts secrets, capped at 50,000 chars); the other CLI subcommands (`add`/`explain`/`diagnose`/`review`) do contact the backend and need the same env vars as the MCP server |
| Configure local Ollama-powered mnemonic suggestions | Yes, verified against a live model | Backend + MnemoLab UI in the Web Application | Running `ollama serve`, a pulled model, 3 backend env vars | Off by default (`ai_provider = "none"`); Docker-to-host networking needs OS-specific config; `docs/ai-model-verification.md` documents real, dated pass/fail results including some reproducible defects |
| Verify releases, compatibility, and platform evidence | Documentation exists; nothing to verify yet | `docs/releasing.md`, `docs/hosted-deployment.md`, `docs/ai-model-verification.md`, ROADMAP, ADRs 0001/0002 | N/A | Since no release/tag/installer has ever been produced, "verifying a release" today means reading the documented methodology, not checking a real artifact |

## 4. Proposed documentation information architecture

### Root README (→ #271)

A short, use-case-first hub: what LensWord is in 2-3 sentences, a table
mapping each use case above to its guide, a minimal "fastest path to
running it" (Docker Compose), and links out — no embedded deep-dive content.
Design decisions, verification logs, and internal architecture notes move to
VitePress/`docs/internal/`.

### VitePress navigation (→ #272)

Organized by user journey, not by source directory:

- **Get Started** — what LensWord is, the use-case table, fastest path
- **Use Cases** — one guide per row of the table in §3
- **Product Guides** — Web Application, Desktop Application, Browser
  Extension, MCP Server, Local CLI (deeper reference beneath each use case)
- **Self-Hosting** — Docker Compose, hosted/production deployment
- **Reference** — environment variables, API boundaries, ADR index
- **Troubleshooting**
- **Contributing**
- **Changelog & Releases** — product-aware changelog, release evidence,
  compatibility matrix (feeds #281/#282)
- **Trust** — verification reports (`ai-model-verification.md` lives here),
  security posture, known gaps

### Stable routes

| Route | Source |
|---|---|
| `/get-started/` | New, built from README + this audit's use-case table |
| `/use-cases/web-app` | New, built from README's running instructions |
| `/use-cases/self-hosting` | `docs/hosted-deployment.md` (moved, not duplicated) |
| `/use-cases/desktop` | `docs/releasing.md` + README's Desktop section + ADR 0001/0002 |
| `/use-cases/browser-extension` | `apps/browser/README.md` (expanded) |
| `/use-cases/mcp-server` | `docs/mcp-remote-transport.md` + `apps/mcp/README.md` |
| `/use-cases/local-cli` | `apps/mcp/README.md` (CLI section, expanded) |
| `/use-cases/ollama-mnemonics` | README's AI/Ollama section |
| `/reference/adr/*` | `docs/adr/*` (moved as-is, index page added) |
| `/trust/ai-verification` | `docs/ai-model-verification.md` (moved, preserved in full) |
| `/trust/release-evidence` | New, feeds #281 |
| `/contributing/` | `CONTRIBUTING.md` (corrected, then moved/mirrored) |

Full source-to-route mapping with keep/rewrite/merge/archive/redirect
decisions is in
[`docs-migration-map.md`](./docs-migration-map.md).

## 5. Evidence gaps

See [`evidence-gaps.md`](./evidence-gaps.md) for the full list of items that
require manual or platform-specific verification rather than static repo
analysis.

## Sources

This report was compiled by directly inspecting: the full repository tree;
`apps/backend`, `apps/frontend`, `apps/desktop`, `apps/browser`, `apps/mcp`
(package manifests, Dockerfiles, CI workflows); `.github/workflows/*.yml`;
`README.md`, `CHANGELOG.md`, `ROADMAP.md`, `CONTRIBUTING.md`, `SECURITY.md`;
every file under `docs/` including `docs/adr/`; `git tag -l`; and, via the
`gh` CLI, `gh issue list --state all`, `gh release list`, and
`gh pr list --state merged`.
