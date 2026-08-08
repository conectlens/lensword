# PyPI publishing setup (Local CLI)

Maintainer/ops reference, not part of the published docs site (`srcExclude:
['internal/**']` in `config.mts`).

**Nothing described on the PyPI side of this document has been done yet.**
This is the setup the repo owner needs to do once, by hand, on pypi.org —
the workflow files (`.github/workflows/publish-cli.yml`,
`.github/workflows/publish-cli-auto-version.yml`) and the package
(`apps/cli`, `lensword-cli`) exist and were verified to build correctly in
this pass (see "What was actually verified" below), but no API token has
been created, no tag has been pushed, and `pip install lensword-cli` does
not work against the real PyPI index yet. See
`docs/internal/product-registry.json`'s `local-cli` entry (`statusNote`)
and `docs/install/mcp-local-cli.md` for how that's represented publicly.

## What's published here

| Package | Source | Workflow | Version source |
|---|---|---|---|
| `lensword-cli` (`lensword` entry point) | `apps/cli` | `.github/workflows/publish-cli.yml` | `apps/cli/pyproject.toml#version` |

Only the Local CLI. The MCP server (`lensword-mcp`, `apps/mcp`) is not
published by this workflow — it has no PyPI publish workflow of its own yet;
npm distribution for the CLI is explicitly out of scope here too (see issue
#311 TODO 2, tracked separately).

## Two workflows, two jobs

- `.github/workflows/publish-cli-auto-version.yml` — runs on every push to
  `main` that touches `apps/cli/**`. Bumps the patch component of
  `apps/cli/pyproject.toml`'s version, commits that bump (tagged
  `[auto-version]` in the message so the bump commit doesn't re-trigger
  itself), and pushes a matching `cli-vX.Y.Z` tag. This is the "correct
  versioning on every change" half — no one needs to hand-edit the version
  or remember to tag.
- `.github/workflows/publish-cli.yml` — runs on `cli-v*` tag push (pushed by
  the workflow above, or manually) or `workflow_dispatch`. Verifies the
  tag's version against `apps/cli/pyproject.toml`, builds the sdist/wheel,
  checks them with `twine check`, and publishes to PyPI.

Because the bump happens on `main` before the tag is cut, the tag always
points at a commit where `pyproject.toml` already matches — `publish-cli.yml`'s
guard step never sees a mismatch from this path.

## Why an API token, not Trusted Publishing

The workflow authenticates to PyPI with a `PYPI_API_TOKEN` secret rather
than [Trusted Publishing](https://docs.pypi.org/trusted-publishers/)'s OIDC
exchange. This is a deliberate tradeoff, not the default recommendation:
Trusted Publishing needs no secret to create or rotate, while a token is a
long-lived credential that must be scoped to the `lensword-cli` project only
and rotated if it ever leaks. Chosen anyway for this project; revisit if the
token needs rotating or scoping ever becomes a problem.

## One-time setup on PyPI (repo owner does this)

1. Sign in to [pypi.org](https://pypi.org) with the account that should own
   the `lensword-cli` project.
2. After the first manual `twine upload` or once the project exists,
   go to **Your account → API tokens**
   ([pypi.org/manage/account/token/](https://pypi.org/manage/account/token/))
   and create a token **scoped to the `lensword-cli` project only** (not an
   account-wide token).
3. Copy the token (`pypi-...`) — PyPI shows it exactly once.

## One-time setup on GitHub (repo owner does this)

1. **Settings → Environments → New environment**, name it exactly `pypi`.
2. Add an **environment secret** named `PYPI_API_TOKEN` with the token value
   from the PyPI step above.
3. Optionally add **required reviewers** on this environment — since the
   workflow already scopes the job to it (`environment: pypi` in
   `publish-cli.yml`), a required reviewer makes every publish (auto-tag or
   manual) pause for approval before it can reach PyPI, with no workflow
   change needed.

## Triggering a release

Normal path: merge any change under `apps/cli/**` to `main`.
`publish-cli-auto-version.yml` bumps the patch version, commits, tags, and
pushes — `publish-cli.yml` then builds and publishes automatically. No
manual tagging needed.

Manual path (still supported, e.g. for a non-patch bump — edit
`apps/cli/pyproject.toml`'s version by hand first):

```bash
# apps/cli/pyproject.toml's version must already read the version being
# released before tagging — publish-cli.yml's guard step fails otherwise.
git tag cli-v0.1.0
git push origin cli-v0.1.0
```

`workflow_dispatch` also triggers `publish-cli.yml` manually (Actions tab →
"Publish Local CLI (PyPI)" → Run workflow) — useful for exercising the
build/check steps before the first real tag exists, or before
`PYPI_API_TOKEN` is configured. Run before that configuration is done, it
will fail at the final publish step with a PyPI authentication error; that
failure is expected and confirms the workflow reaches PyPI correctly, not
that anything else is broken.

## What was actually verified in this pass

- `apps/cli` installs cleanly with `pip install -e apps/cli` in a fresh
  Python 3.12 virtualenv, and the `lensword` entry point runs.
- `apps/mcp` installs cleanly with `pip install -e apps/cli -e apps/mcp` in
  a fresh virtualenv (its new `lensword-cli==0.1.0` dependency resolves
  against the local editable install, not PyPI), and `lensword-mcp` fails
  closed (exit 2, names the missing variables) exactly as before the split.
- The `apps/mcp` Docker image (`render.yaml`'s `lensword-mcp` service)
  builds successfully with the updated build context/Dockerfile that
  installs both packages from source, and the resulting container still
  fails closed the same way.
- `publish-cli.yml`'s YAML is well-formed and its steps (checkout, guard,
  build, twine check) were reasoned through against `apps/cli`'s actual
  `pyproject.toml`, but the workflow has not been run in GitHub Actions
  (no trusted publisher exists yet to authenticate against) and no PyPI
  publish has ever happened for this project.
