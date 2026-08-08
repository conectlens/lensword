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

Fragment validation (`scripts/changelog/schema.py`) is enforced in CI
(`.github/workflows/changelog.yml`, [issue #282](https://github.com/conectlens/lensword/issues/282)):
a pull request that touches a registered product's source with no
changelog fragment at all fails the build, and a `passed` verification
claim with no referenced command, workflow, or artifact is rejected at
authoring time.

## Versioning and tags

Each product versions independently, with its own tag prefix, rather than
one ambiguous `v*` tag standing in for the whole ecosystem:

| Product | Tag prefix | Version source | Publish workflow |
|---|---|---|---|
| Web Application | `web-v` | `apps/frontend/package.json` | none yet |
| Desktop Application | `desktop-v` | `apps/desktop/src-tauri/tauri.conf.json` | `.github/workflows/release.yml` |
| Browser Extension | `browser-v` | `apps/browser/manifest.json` | none yet |
| MCP Server | `mcp-v` | `apps/mcp/pyproject.toml` | none yet — not published to PyPI |
| Local CLI | `cli-v` | `apps/cli/pyproject.toml` | `.github/workflows/publish-cli.yml` |

Since [#311](https://github.com/conectlens/lensword/issues/311) split the
Local CLI (`apps/cli`, `lensword-cli`) out of the MCP server (`apps/mcp`,
`lensword-mcp`), the two version independently under their own tag
prefixes and package sources — they are no longer "both entry points ship
in one package." `docs/internal/product-registry.json`'s `mcp-server` and
`local-cli` entries are the source of truth for this split.

`.github/workflows/release.yml` triggers on the namespaced `desktop-v*`
convention above (`v*` still works too, as a legacy alias — see that
workflow's own comment). `.github/workflows/publish-cli.yml` triggers on
`cli-v*` (see `docs/internal/pypi-publishing.md` for the one-time PyPI/GitHub
setup it still needs). No tag of any kind had been pushed against this
repository until `desktop-v0.1.0`; see [Releases](/reference/releases/) for
the current record.

## Release channels (desktop)

Two distinct channels produce desktop installers, both via
`.github/workflows/build-desktop-installers.yml` (shared packaging/signing
logic, so they can't silently drift apart):

- **Tagged releases** (`.github/workflows/release.yml`, triggered by
  pushing a `desktop-v*` tag) — a specific, deliberately cut version.
  Published as a GitHub Releases **draft** so a tag never publishes
  installers without someone looking first.
- **Continuous build** (`.github/workflows/release-continuous.yml`,
  triggered by every push to `main` that touches the desktop shell or
  frontend) — always reflects the current tip of `main`. Published
  immediately (not a draft) under a fixed rolling tag,
  `desktop-continuous`, replacing the previous build's release and assets
  each time; marked `prerelease: true` so it's visually distinct from a
  real release in GitHub's own UI. This is what "download and try what's
  on `main` right now" means for this project — it is explicitly **not**
  a stable or reviewed release, and its own release notes say so.

Both channels bake the hosted production endpoints in as the
zero-configuration default (`apps/desktop/api-config/src/lib.rs`'s
`DEFAULT_API_BASE`, set at compile time via `LENSWORD_RELEASE_API_BASE` —
see that file's doc comment): the backend at
`https://lensword-api.conectlens.com`. A local `cargo tauri dev`/`cargo
build` never sets that variable, so local development keeps defaulting to
`http://127.0.0.1:8000` unaffected, and the runtime `LENSWORD_API_URL`
environment variable and the `api-endpoint` config file both still
outrank the compiled-in default in either build — self-hosting a
downloaded installer against your own backend remains fully supported,
only the out-of-the-box default changes. See
[Self-Hosting & Deployment](/install/self-hosting) and
[docs/internal/cloudflare-deployment.md](https://github.com/conectlens/lensword/blob/development/docs/internal/cloudflare-deployment.md)
for how `lensword-api.conectlens.com` itself is deployed, and
`lensword-mcp.conectlens.com`/`lensword.conectlens.com` for the MCP
server's remote transport and the hosted web app, respectively.

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
