# PyPI publishing setup (Local CLI)

Maintainer/ops reference, not part of the published docs site (`srcExclude:
['internal/**']` in `config.mts`).

**Nothing described on the PyPI side of this document has been done yet.**
This is the setup the repo owner needs to do once, by hand, on pypi.org —
the workflow file (`.github/workflows/publish-cli.yml`) and the package
(`apps/cli`, `lensword-cli`) exist and were verified to build correctly in
this pass (see "What was actually verified" below), but no trusted
publisher has been registered, no tag has been pushed, and `pip install
lensword-cli` does not work against the real PyPI index yet. See
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

## Why Trusted Publishing, not an API token

The workflow authenticates to PyPI via [Trusted Publishing](https://docs.pypi.org/trusted-publishers/)
— GitHub Actions' OIDC identity, exchanged for a short-lived PyPI upload
token at publish time. There is no `PYPI_API_TOKEN` (or any other) secret
to create or rotate; the trust relationship is configured once, on PyPI's
own dashboard, and tied to this exact repository, workflow file, and
environment.

## One-time setup on PyPI (repo owner does this)

PyPI supports registering a trusted publisher for a project **before that
project exists** — the first successful publish from the matching workflow
run creates it. Do this once:

1. Sign in to [pypi.org](https://pypi.org) with the account that should own
   the `lensword-cli` project.
2. Go to **Your account → Publishing** (directly:
   [pypi.org/manage/account/publishing/](https://pypi.org/manage/account/publishing/)).
3. Under **Add a new pending publisher**, fill in exactly:

   | Field | Value |
   |---|---|
   | PyPI Project Name | `lensword-cli` |
   | Owner | `conectlens` |
   | Repository name | `lensword` |
   | Workflow name | `publish-cli.yml` |
   | Environment name | `pypi` |

   The **Environment name** field matters — it must match the
   `environment: pypi` line in `publish-cli.yml`'s `publish` job exactly, or
   PyPI will reject the OIDC token from a workflow run that doesn't present
   that environment claim.
4. Submit. PyPI shows it under "Pending publishers" until the first
   successful publish, at which point it becomes a normal trusted publisher
   for the now-existing `lensword-cli` project.

## One-time setup on GitHub (repo owner does this)

Create the `pypi` environment so the trusted-publisher claim above has
something to match, and so protection rules can be added later:

1. **Settings → Environments → New environment**, name it exactly `pypi`.
2. Optionally add **required reviewers** here — since the workflow already
   scopes the job to this environment (`environment: pypi` in
   `publish-cli.yml`), adding a required reviewer later makes every publish
   (tag push or manual dispatch) pause for approval before it can reach
   PyPI, with no workflow change needed.

No environment secrets are needed — trusted publishing does not use one.

## Triggering a release

Once both setup steps above are done:

```bash
# apps/cli/pyproject.toml's version must already read "0.1.0" (or whatever
# is being released) before tagging — publish-cli.yml's guard step fails
# the run otherwise.
git tag cli-v0.1.0
git push origin cli-v0.1.0
```

The tag push triggers `publish-cli.yml`, which verifies the tag's version
against `apps/cli/pyproject.toml`, builds the sdist/wheel with `python -m
build`, checks them with `twine check`, and publishes via
`pypa/gh-action-pypi-publish`.

`workflow_dispatch` also triggers this workflow manually (Actions tab →
"Publish Local CLI (PyPI)" → Run workflow) — useful for exercising the
build/check steps before the first real tag exists, or before the PyPI
trusted publisher is configured. Run before that configuration is done, it
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
