---
title: Release Process
description: How a merged change becomes a published LensWord release, and how to verify one.
---

# Release process

## What counts as a LensWord product

Five surfaces are independently distributable today: Web Application,
Desktop Application, Browser Extension, MCP Server, and Local CLI (the
last two share `apps/mcp` but have distinct entry points and use cases).
The shared backend (`apps/backend`) is not independently released — every
other product depends on it, but it has no install method, version, or
release channel of its own. See
[docs/internal/repo-audit.md](https://github.com/conectlens/lensword/blob/development/docs/internal/repo-audit.md)
for the full evidence behind that boundary, including why it isn't just
"every `apps/*` folder is a product."

Different surfaces have different release statuses because they're built,
tested, and distributed differently: the web app is CI-tested and served
from a Docker image; the desktop app needs platform-specific build
toolchains and, eventually, signing certificates; the browser extension
has no CI at all and no store presence; the MCP server and CLI aren't
published to PyPI. Treating them as one undifferentiated "LensWord
version" would hide that a desktop-only bug fix, say, has nothing to do
with whether the web app changed.

## Merged is not released

A pull request merging into `development` means the change exists in
source control — nothing more. It is not available in any downloadable,
hosted, packaged, or published product until it's part of that product's
actual release artifact. [Main Branch Activity](/reference/changelog/main-branch-activity)
tracks what's merged; [each product's changelog](/reference/changelog/)
tracks what's changed for that product, still `unreleased` until a real
release exists; [Releases](/reference/releases/) will hold the immutable
record once one does.

Statuses used throughout: **Merged** (in `development`, nothing more),
**Unreleased** (described in a changelog fragment, not yet part of a
release), **Released** (part of an actual tagged/published release for
that specific product), **Reverted** (merged, then undone), **Internal**
(no externally observable effect).

## How a change is documented

Every externally observable change gets a
[changelog fragment](https://github.com/conectlens/lensword/tree/development/.changes)
— a YAML file naming which product(s) it affects, what changed, and
exactly what verification backs it (see
[Verification levels](/reference/trust/verification-levels)). A change
affecting several products (a shared backend contract change, for
example) gets **one** fragment listing all of them, not a copy per
product — `scripts/changelog/generate.py` renders it into every affected
product's page from that single source, so the views can't drift apart.
[`.changes/README.md`](https://github.com/conectlens/lensword/blob/development/.changes/README.md)
has the full schema and authoring guide.

Fragment validation (`scripts/changelog/schema.py`) exists today as a
script contributors and reviewers can run by hand. CI enforcement —
failing a pull request that changes observable behavior without a
fragment, or that claims verification it can't back up — is tracked
separately in
[issue #282](https://github.com/conectlens/lensword/issues/282) and
doesn't exist yet.

## Versioning and tags

Each product versions independently, with its own tag prefix, rather than
one ambiguous `v*` tag standing in for the whole ecosystem:

| Product | Tag prefix | Version source |
|---|---|---|
| Web Application | `web-v` | `apps/frontend/package.json` |
| Desktop Application | `desktop-v` | `apps/desktop/src-tauri/tauri.conf.json` |
| Browser Extension | `browser-v` | `apps/browser/manifest.json` |
| MCP Server / Local CLI | `mcp-v` | `apps/mcp/pyproject.toml` (both entry points ship in one package) |

This is a **documented decision, not yet a completed migration**: no tag
of any kind has ever been pushed against this repository (`git tag -l` is
empty), and `.github/workflows/release.yml` still triggers on a bare `v*`
tag for desktop only. Updating that workflow to the namespaced convention
above, and cutting a first real release under it, is follow-up work this
page intentionally doesn't claim is already done.

## Promoting a change from Unreleased to Released

A change becomes `Released` for a specific product only when that
product's own release record includes it — never merely because its
commit reached `development`. A release record (once one exists) will
include the version, tag, exact commit SHA, every changelog entry it
contains, breaking changes and migration steps, known limitations,
supported platforms, artifact names and SHA-256 checksums, signing status,
and links back to the originating pull requests and issues.

## Compatibility

[The compatibility matrix](/reference/trust/compatibility) reports what
each product requires from the shared backend/API. Today, every cell
reads `Not declared` — no product has ever shipped a release that could
carry a real compatibility constraint, so the honest answer is that none
exists yet, not a guess at what it might be.

## Verifying a release yourself

Once a release exists: check the tag matches the commit SHA in the
release record (`git show <tag>`), recompute the SHA-256 of any
downloaded artifact and compare it against the one published in the
release record, and check the linked CI workflow run actually corresponds
to that commit. Don't trust a "signed" or "notarized" label without a
signature you can independently verify — see
[Releases & compatibility](/reference/releasing) for the current desktop
build/signing process specifically.

## Internal-only changes

A change with no externally observable effect (an internal refactor, a
CI-only fix) still gets a fragment rather than being silently
undocumented — set `documentation_required: false` and a `user_impact` of
`None — internal change.` A CI-enforced `changelog: none` escape hatch
with a mandatory reason, for things too trivial to warrant even that
(a comment typo), is planned as part of #282 and doesn't exist yet.
