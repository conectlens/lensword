# Documentation epic (#268) — final QA and implementation report

Written for #283, the closing verification issue of the documentation epic
(#269–#283). Excluded from the built site (`srcExclude: ['internal/**']` in
`config.mts`) — this is a maintainer-facing record, not a page for
visitors. Every command below was actually run against this branch; none
of the results are inferred or assumed.

## 1. Repository state discovered before implementation

Before #269's audit, LensWord had no canonical account of its own product
surfaces: no registry of what shipped, what didn't, or what each surface's
real status was. `docs/internal/repo-audit.md` (#269) is the source
record; in summary:

- Five independently distributable products existed in the codebase (Web,
  Desktop, Browser Extension, MCP Server, Local CLI) plus a shared,
  non-independently-released backend, but nothing enumerated them together.
- No logo/brand asset system existed — placeholder icons throughout.
- README was not use-case-first and didn't reflect the desktop/extension/MCP
  surfaces that existed in the tree.
- No docs site existed; scattered Markdown files under `docs/` with no
  navigation or build.
- No changelog beyond a single flat `CHANGELOG.md`; no per-product release
  identity, no versioning scheme, no verification-evidence convention.
- No CI enforcement tying any of the above together — a contributor could
  add a feature to any product with no docs, no changelog entry, and no
  route ever created for it, and nothing would fail.

## 2. Final product registry and product-boundary rationale

`docs/internal/product-registry.json`, generated from the audit and
extended by #270–#283, is the single source of truth every downstream
system reads from — `SurfaceChooser.vue`, `scripts/changelog/generate.py`,
`scripts/changelog/schema.py`, `scripts/changelog/check_product_impact.py`,
`scripts/docs-qa/check_routes_links.py`. Six entries:

| id | kind | sourcePath | changelogRoute | installRoute |
|---|---|---|---|---|
| web | public-product | apps/frontend | /reference/changelog/web | /install/web-app |
| desktop | public-product | apps/desktop | /reference/changelog/desktop | /install/desktop-app |
| browser-extension | public-product | apps/browser | /reference/changelog/browser-extension | /install/browser-extension |
| mcp-server | public-product | apps/mcp | /reference/changelog/mcp | /install/mcp-local-cli |
| local-cli | public-product | apps/mcp | /reference/changelog/mcp | /install/mcp-local-cli |
| backend | implementation-dependency | apps/backend | /reference/changelog/server-api | — |

`mcp-server` and `local-cli` deliberately share one source path, changelog
route, and install guide — they're two entry points (`lensword-mcp` and
`lensword`) built from the same `apps/mcp` package, not two products with
independent lifecycles. `backend` is `implementation-dependency`, not
`public-product` — it has no version tag prefix and is never released on
its own; changes to it are folded into whichever public product(s) they
actually affect. This boundary is enforced, not just documented:
`scripts/changelog/validate_registry.py` fails if a `public-product`
lacks a `changelogRoute`/`installRoute`, and
`scripts/docs-qa/check_routes_links.py` fails if either route has no
built page behind it.

## 3. Documentation migration summary

Old scattered `docs/*.md` files were restructured around
[Diátaxis](https://diataxis.fr/) per the mid-epic instruction to make
Setup/Install/Learn/Reference explicit:

- **Setup** (`/setup/`) — the one tutorial: first-run walkthrough.
- **Install** (`/install/*`) — seven how-to guides, one per product plus
  self-hosting, local AI/Ollama, and troubleshooting.
- **Learn** (`/learn/*`) — explanation: choosing a surface, architecture,
  brand.
- **Reference** (`/reference/*`) — changelog, releases, trust,
  MCP/CLI/local-dev reference, ADRs.

`CHANGELOG.md` at the repo root was not deleted — it carries a pointer
block at the top directing to the new system, with its full historical
content preserved below and `@include`'d verbatim into
`/reference/changelog/legacy`, so nothing that used to be reachable
became unreachable.

## 4. README and VitePress architecture

README (#271) was rewritten use-case-first: a surface-comparison table,
a verified quick start, real demo media (not mockups), sponsorship, and a
pointer to the new changelog/trust system, with all detailed procedures
moved into `docs/`. VitePress (#272) builds the Diátaxis structure above
via `docs/.vitepress/config.mts`; theme customization lives in
`docs/.vitepress/theme/` (`custom.css`, `index.ts`,
`components/SurfaceChooser.vue`, which reads the registry directly).

A genuine Windows-specific VitePress bug was found and fixed during #272:
`srcExclude: ['/internal/**']` (leading slash) made the underlying glob
library misresolve the pattern as an absolute path via `path.isAbsolute()`
on win32, corrupting page discovery for the *entire* site (zero pages
built). Fixed by dropping the leading slash — documented in `config.mts`'s
own comment so it isn't reintroduced.

## 5. Brand/logo assets

#270: an original SVG mark (lens + word-line) in `brand/logo/svg/`, with
`scripts/generate-brand-assets.py` deriving every raster
(PNG/WebP/ICO/ICNS) from those vector sources reproducibly — not
hand-exported. Wired into the web favicon/OG image, desktop app icons
(replacing Tauri's default placeholder), and the browser extension's
manifest icons (previously unset entirely — MV3 doesn't accept SVG for
that field, so the extension had no working icon before this).

The brand accent `#ffde59` fails WCAG AA as text on white (~1.3:1); this
was caught and fixed *during* #270, not by #283 — light-mode link text
uses a derived `#7a5f00` (~6:1), dark mode uses the true accent against a
near-black surface (~14:1). Documented in `custom.css`'s own header
comment.

## 6. Product guides and demo scenarios

Each public product has an Install guide (#273–#276) written and verified
against the actual running application, not written from source-reading
alone — see each guide's own verification notes for what was and wasn't
observed on a real OS/browser. Demo media (#278): ~15 real screenshots and
one animated review-session sequence, all captured from the actual running
app, with a `provenance.json` sidecar recording the exact reproducible
fixture (username, group, words) each frame came from — not staged
mockups.

Two accidental unrelated-window screenshot captures happened during #278
(full-screen/hardcoded-region captures picked up other windows on the
machine, once showing another project's API key discussion) — both were
caught immediately during manual review, deleted before use, and the
capture technique was hardened twice (window-bounds capture via
`EnumWindows`+`GetWindowRect`, then `PrintWindow` with exact-title
verification). No leaked content was ever committed or used.

## 7. Changelog/release/tag/compatibility design

#281: `.changes/*.yml` fragments (schema in `.changes/README.md`) are the
canonical record of every observable change; `scripts/changelog/generate.py`
deterministically renders per-product changelog pages, a Main Branch
Activity ledger, a releases index, and a compatibility matrix from
fragments + the registry + `git log`. Product-namespaced version tags
(`desktop-v*`, `web-v*`, `browser-v*`, `mcp-v*`) replace a single ambiguous
`v*` tag. No LensWord product has ever been released — the releases index
and compatibility matrix say so plainly rather than inventing plausible
placeholder data.

#282 turned this from documented convention into an enforced CI gate (see
§8) and added `type: none` — an explicit "no changelog entry needed"
fragment with a mandatory `reason`, reviewed in the PR diff and listed in
an appendix on the changelog overview, rather than silently skipping the
fragment requirement for internal-only changes.

## 8. CI and workflow changes

| Workflow | Added/changed in | What it gates |
|---|---|---|
| `docs.yml` | #272, hardened later | VitePress build + Pages deploy (skips deploy cleanly if Pages isn't enabled — a real 404 the user hit was fixed here) |
| `changelog.yml` | #282 | Registry validity, fragment schema (incl. evidence requirements for "passed" claims), product-impact detection (fails a PR touching a registered product's source with zero fragments), generation idempotency |
| `docs-qa.yml` | #283 | Route/link integrity, code-block syntax, media size/secret scan, accessibility smoke test |
| `release.yml` | #281 | Tag trigger updated to `desktop-v*` (legacy `v*` alias kept) |

None of these workflows commit back to the branch — every one is a
read-only check, so there's no risk of a self-triggering commit loop
(#282's own acceptance criterion).

A real bug was found and fixed while building `changelog.yml`, not by
inspection: `generate.py`'s Main Branch Activity ledger hardcoded
`git log development`. A PR-triggered CI checkout has no local
`development` branch — only `origin/development` — so this would have
silently rendered an empty ledger the first time it ran in CI. Fixed with
a `development` → `origin/development` → `HEAD` fallback.

A second real bug was found by `docs-qa.yml`'s own route/link checker
before it was ever wired into CI: `render_main_branch_activity()` linked
each changelog fragment as `[id](#id)` — a same-page anchor — but
Main Branch Activity never renders fragment entries, only the commit
ledger, so every one of those links was dead by construction. Fixed by
linking to the fragment's actual rendered location (the changelog
overview page) and giving each entry an explicit `<a id>` anchor instead
of relying on VitePress's auto-slugified heading id (which is derived
from the summary text, not the stable fragment id).

A third real bug, found the same way: `docs/install/troubleshooting.md`
linked to `/install/desktop-app#what-works-and-what-is-not-yet-verified`
and `#installing` — anchors that don't exist; the real heading is
"Platform verification matrix" and "Install". Fixed to the real anchors.

## 9. Historical migration and unclassified entries

Main Branch Activity's git-log ledger explicitly labels every commit that
predates the changelog-fragment system as `none (predates this system)`
rather than fabricating a retroactive product assignment for commits that
were never authored with this schema in mind. No commit message was
mined and converted into a change-type/product classification after the
fact — see `generate.py`'s own comment on this.

## 10. Exact test/build commands and results

Run on this branch (`docs/283-qa-verification-gates`, based on `docs/282-changelog-ci-enforcement`, based on `development` at `983c0cb`):

```
$ cd docs && npm ci && npm run docs:build
build complete in 3.21s-4.84s (varies by run)

$ python scripts/changelog/validate_registry.py
docs\internal\product-registry.json: valid.

$ python scripts/changelog/schema.py .changes/*.yml
5 fragment(s) valid.

$ cd scripts/changelog && python -m pytest -v
32 passed

$ python scripts/docs-qa/check_routes_links.py
routes/links valid: 42 built page(s) checked, every registered product has a working guide + changelog route.

$ python scripts/docs-qa/check_code_blocks.py
code blocks valid: 46 Markdown file(s) checked.

$ python scripts/docs-qa/check_media.py
media checks passed: 19 file(s) under docs/media checked for size budgets and sidecar-text secrets.

$ cd scripts/docs-qa && python -m pytest -v
32 passed

$ node scripts/docs-qa/check_accessibility.mjs
Accessibility check passed: 6 page(s) x 2 themes (light/dark), wcag2a/wcag2aa/wcag21aa rule sets,
0 new violations (4 known/acknowledged, see KNOWN_VIOLATIONS).
```

Backend/frontend/desktop test suites were not re-run for this QA pass —
no application code changed in #269–#283 (docs, scripts, and CI config
only); `ci.yml`'s own jobs cover that surface on every PR regardless.

## 11. Route/link/accessibility verification detail

**Route coverage** — every `public-product` in the registry has both an
`installRoute` and `changelogRoute` that resolve to a real built page;
enforced by `check_routes_links.py`'s `check_registered_routes()`, which
fails CI if a future product is registered without one.

**Link integrity** — 42 built pages crawled; every internal `<a href>` and
`<img src>` resolves to a real file, every same-page and cross-page anchor
(`#fragment`) resolves to a real element id. README's own relative
links/images are checked separately (not part of the VitePress build).
Deliberately-dead links inside `/reference/changelog/legacy` (the raw
`CHANGELOG.md` include, whose links are correct for GitHub, not this site
— see `config.mts`'s own `ignoreDeadLinks` comment) are recognized via the
same pattern list, not silently permitted by accident.

**Code examples** — every fenced `json`/`yaml`/`yml` block across `docs/`,
`README.md`, and `CONTRIBUTING.md` is syntactically valid (46 files
checked). `toml` blocks are checked too, when the running Python is 3.11+
(CI is; `tomllib` isn't in the stdlib before that, so this degrades to a
skip-with-warning on an older local interpreter rather than crashing).
**Not done:** executing the commands themselves in a clean environment —
see §12.

**Accessibility** — axe-core (`wcag2a`/`wcag2aa`/`wcag21aa` rule sets)
against 6 representative pages (one per Diátaxis quadrant plus the two
data-heavy generated pages) × 2 color schemes. One real, fixed finding:
`--vp-code-lang-color` (the small language badge on a fenced code block)
measured 2.87:1 light / 3.36:1 dark against a 4.5:1 AA requirement —
VitePress's own default value, overridden in `custom.css`. One real, open
finding, not fixed: Shiki's default `github-light`/`github-dark` comment
token color (`#6A737D`) measures 4.45:1 light / 3.75:1 dark, just under
AA. Not fixed here because the color is set via a per-`<span>` inline
`--shiki-*` custom property with no class to target — the only real fixes
are picking a different Shiki theme pair (needs visual review across every
code sample on the site, not a one-line change) or matching the literal
hex value in a CSS attribute selector (fragile — breaks silently if
Shiki's output changes). Tracked as `KNOWN_VIOLATIONS` in
`check_accessibility.mjs`: CI fails on any *new* violation, this
pre-existing one stays visible in output rather than silently passing or
silently blocking every future PR.

## 12. Remaining limitations and unperformed checks

Named honestly rather than rounded up to "done":

- **Live command execution in clean environments** — documented commands
  (`docker compose up`, `pip install`, `npm run dev`, etc.) are checked
  for syntactic validity in code fences (§11) and were manually verified
  during each product's guide (#273–#276), but there is no automated
  "spin up a clean container/venv and run every documented command" gate.
- **MCP client version verification** — no live interop test against a
  real third-party MCP host exists (documented as a known gap in the MCP
  guide itself, not newly discovered here).
- **Desktop cross-platform manual checks** — macOS and Linux GUI testing
  was not possible from this environment (documented per-platform in the
  desktop guide's own verification matrix, `Unavailable` rather than
  assumed passing).
- **Full historical Git evidence mining** — squash-merge/cherry-pick/bot-commit
  disambiguation beyond the existing sliding-window git-log ledger is not
  implemented (deferred in #282, still open).
- **Release-artifact/checksum/signing validation** — not implemented; no
  LensWord release has ever been cut, so there is nothing real to validate
  against yet.
- **Screenshot pixel-content scanning** — `check_media.py` scans
  file-size budgets and sidecar text (JSON/txt/md) for secret-shaped
  strings and real local paths; it does not OCR screenshot pixels. Every
  screenshot in this repo was manually reviewed for exactly that before
  being committed (see §6's two caught incidents) — that manual review is
  the actual control here, not an automated one.
- **Shiki code-comment contrast** — open, see §11.
- **Real keyboard-navigation/screen-reader testing** — axe-core catches
  structural/contrast violations; it does not replace a human using a
  screen reader or tabbing through the site, which wasn't performed.

## 13. The exact first-time visitor experience

A visitor landing on the GitHub repo sees a use-case-first README: a
surface-comparison table, a verified quick start, real demo screenshots
and an animated review-session, then pointers to the docs site
(`docs/setup/`) for a full tutorial, install guides per product, and the
new changelog/trust system for anyone checking whether a claim is backed
by real evidence. Every route the README links to resolves (§11). No
release has ever been published — the README, releases index, and
compatibility matrix all say this in the same words rather than three
different framings of the same fact.

## 14. The exact experience after the next PR merge and next product release

**Next PR merge:** if it touches a registered product's source with no
`.changes/*.yml` fragment, `changelog.yml` fails the build with an
actionable message before merge is possible (assuming branch protection is
configured to require it — see below). If it adds a fragment naming a
product whose files it didn't touch, or vice versa, `check_product_impact.py`
warns without blocking (path detection is advisory, per #282's own
requirement). Main Branch Activity's ledger picks up the new commit on the
next `generate.py` regeneration.

**Next product release:** cutting a tag matching a product's
`versionTagPrefix` (e.g. `desktop-v0.2.0`) triggers `release.yml`, which
still only produces (currently unsigned) installers — it does not update
the releases index or `releaseStatus` in the registry automatically. That
remains a manual step per `docs/reference/trust/release-process.md`.

**Not yet done: branch protection.** Neither `changelog.yml` nor
`docs-qa.yml` has been added as a required status check in the
repository's branch protection settings — that's a repository-admin
setting change, deliberately left to the user rather than changed
autonomously (same judgment applied earlier in this epic to enabling
GitHub Pages). Both workflows run and report on every PR regardless; they
just don't yet block merge on failure without that setting enabled.
