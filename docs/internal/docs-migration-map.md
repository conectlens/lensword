# Documentation Migration Map

> Maps every existing user-relevant document to a disposition (keep,
> rewrite, merge, archive, redirect) and, where applicable, its new
> canonical VitePress route. Built from the audit in
> [`repo-audit.md`](./repo-audit.md) for issue #269. Later issues (#271,
> #272) should execute this map rather than re-deriving it.

| Current path | Disposition | New route / destination | Notes |
|---|---|---|---|
| `README.md` | **Rewrite** | stays at repo root | Becomes a concise use-case-first hub (#271); deep content below moves into VitePress |
| `README.md` § "Design decisions worth flagging" | **Merge** | `/reference/adr/` (or a new "Design notes" reference page) | Not a getting-started concern |
| `README.md` § "Verification actually run" / "Known gaps" | **Merge** | `/trust/` | Pairs with `docs/ai-model-verification.md` |
| `README.md` § Desktop | **Merge** | `/use-cases/desktop` | Combine with `docs/releasing.md` |
| `README.md` § Ollama/AI setup | **Merge** | `/use-cases/ollama-mnemonics` | |
| `README.md` broken link to `docs/memory-loop-verification.md` | **Fix** | n/a | File does not exist anywhere in the repo; either restore the content under its real name or remove/repoint the link. Same broken link exists in `ROADMAP.md`. |
| `CHANGELOG.md` | **Keep** (until #281 lands) | `/changelog/` | Feeds the product-aware changelog system; do not restructure ahead of #281 |
| `ROADMAP.md` | **Keep** | `/roadmap/` or stays at root, linked from VitePress nav | Fix the same broken `memory-loop-verification.md` link when touched |
| `CONTRIBUTING.md` | **Keep, needs a correction** | `/contributing/` | "Project layout" section omits `apps/desktop`, `apps/browser`, `apps/mcp` — flagged as stale in the audit; correct when this file is next touched (not required for #269 itself) |
| `SECURITY.md` | **Keep** | `/trust/security` or stays at root | Cross-check "known limitations" against later rate-limiting work in CHANGELOG |
| `CODE_OF_CONDUCT.md`, `LICENSE` | **Keep as-is** | stays at root | Standard OSS scaffolding, no docs-architecture action needed |
| `docs/releasing.md` | **Keep, relocate** | `/use-cases/desktop` (release/verification subsection) | Canonical source for desktop release process |
| `docs/hosted-deployment.md` | **Keep, relocate** | `/use-cases/self-hosting` | Canonical source; #273 must link here, not duplicate |
| `docs/mcp-remote-transport.md` | **Keep, relocate** | `/use-cases/mcp-server` | Canonical source for #276 |
| `docs/ai-model-verification.md` | **Archive as historical evidence record** | `/trust/ai-verification` | Preserve in full — this is a dated verification log, not prose to rewrite |
| `docs/adr/0001`–`0009` | **Keep, relocate as a set** | `/reference/adr/*` with an index page | All still govern real decisions; do not edit content, only add an index and cross-links from the use-case guides that depend on each one |
| `apps/browser/README.md` | **Keep** | stays in-repo; link from `/use-cases/browser-extension` | Developer quick-reference, not a replacement for the user-facing guide |
| `apps/mcp/README.md` | **Keep** | stays in-repo; link from `/use-cases/mcp-server` and `/use-cases/local-cli` | Same rationale |
| `.github/pull_request_template.md` | **Keep, needs a correction** | n/a (not a docs route) | Only references backend/frontend gates, consistent with CONTRIBUTING's staleness; out of scope for #269 |

## README links that must point to docs routes

Once VitePress (#272) exists, the following README sections should become
short summaries + a link rather than full inline content: Desktop
installation/setup, Ollama/AI configuration, self-hosting/production
deployment, and the design-decisions/verification-gaps material. This list
is the direct input for #271's rewrite scope.

## Explicitly not migrated

No file listed in the audit is deleted. Every ADR, the AI verification log,
`ROADMAP.md`, and `CHANGELOG.md` are preserved per issue #269's acceptance
criteria ("no existing ADR, historical changelog, verification report, or
deployment warning is silently deleted").
