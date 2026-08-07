# Changelog fragments

One YAML file per externally-observable change, describing exactly what
changed, for which LensWord product(s), and what evidence backs the claim.
`scripts/changelog/generate.py` reads every fragment here plus
`docs/internal/product-registry.json` and writes the per-product changelog
pages under `docs/reference/changelog/` deterministically — the fragments
are the source of truth; the generated Markdown is a build output, not
something to hand-edit.

## Authoring a fragment

Copy an existing fragment as a starting point, or use this schema:

```yaml
id: unique-stable-kebab-case-id       # matches the filename (without .yml)
products:                              # product IDs from docs/internal/product-registry.json
  - web
  - desktop
type: added                            # added | changed | fixed | security | deprecated | removed | performance | documentation | none
summary: Concise, user-facing description of what changed.
technical_summary: null                # optional — maintainer-facing detail the summary omits
user_impact: What changes for someone using the product, in plain language.
release_status: unreleased             # unreleased | released — set by the release process, not by hand
breaking: false
migration: none                        # "none", or explicit steps if breaking: true
known_limitations: []                  # unresolved gaps this change doesn't close
compatibility:
  requires:
    server_api: null                   # a version constraint string, or null if not declared
verification:
  automated_tests:
    status: not_run                    # passed | failed | not_run | unavailable — "passed" requires commands or workflow_url below
    commands: []
    workflow_url: null
  artifact_build:
    status: not_run                    # passed | failed | not_run | unavailable — "passed" requires at least one artifact below
    artifacts: []
  manual_platform_checks:
    macos: not_run                     # passed | failed | not_run | not_applicable
    windows: not_run
    linux: not_run
  production_observation:
    status: not_observed               # observed | not_observed | not_applicable
security_impact: none                  # "none", or a bounded factual description
documentation_required: true
date: '2026-08-07'                     # the date this fragment was authored (ISO 8601)
references:
  issues: []
  pull_requests: []
  commits: []
```

**`type: none`** — the explicit "this change needs no changelog entry" fragment.
Requires a mandatory `reason` field (a top-level key alongside the ones
above) and `documentation_required: false`. It's excluded from every
product's rendered changelog page, but still validated by the schema and
listed in a "No changelog entry" appendix on the
[changelog overview](../docs/reference/changelog/index.md) for reviewer
visibility — this is what makes it a reviewed decision rather than a
silent skip:

```yaml
id: ci-workflow-cleanup
products: [web]
type: none
reason: Renamed a CI job for clarity; no user-observable effect.
documentation_required: false
# ...the rest of the required fields still apply (summary, user_impact,
# verification, date, references, etc.) — only 'reason' is added on top.
```

**Verification status is never inflated.** A passing backend test proves
the backend behaves as tested — it does not prove a desktop notification
displayed on Windows, or that a browser extension installs from a packaged
artifact. Fill in exactly what was checked and leave the rest `not_run` or
`unavailable`. See
[Verification levels](../docs/reference/trust/verification-levels.md) for
what each status means in the rendered changelog.

**Multi-product changes get one fragment, not several.** A shared backend
or contract change that affects Web, Desktop, Browser Extension, and MCP
simultaneously lists all four in `products` — the generator renders it into
every affected product's changelog from that one file, so the four views
can't drift out of sync with each other.

**Internal-only changes** (no externally observable behavior — a CI fix, a
refactor, an internal test) still get a fragment; use `type: none` with a
`reason` (see above) and `documentation_required: false`, and a
`user_impact` of `None — internal change.`, rather than skipping the
fragment.

## CI enforcement (#282)

`.github/workflows/changelog.yml` runs on every pull request and fails the
build if:

- `docs/internal/product-registry.json` is structurally invalid or out of
  sync with the docs navigation (`validate_registry.py`)
- any fragment under `.changes/` fails schema validation, including a
  `passed` verification claim with no referenced commands, workflow, or
  artifacts (`schema.py`)
- the PR touches a registered product's source (`apps/frontend`,
  `apps/backend`, `apps/desktop`, `apps/browser`, `apps/mcp`) and adds no
  fragment at all (`check_product_impact.py`) — a fragment naming a product
  the diff doesn't touch, or vice versa, is a warning, not a failure: path
  detection is an aid, not proof
- the generated changelog/releases/compatibility pages don't match what
  `generate.py` actually produces from the current fragments + registry

## Validating fragments

```bash
python scripts/changelog/validate_registry.py
python scripts/changelog/schema.py .changes/*.yml
python scripts/changelog/check_product_impact.py --base origin/development --head HEAD
```

`schema.py` exits non-zero and prints every problem found (unknown product
ID, invalid enum value, missing required field, breaking change with no
migration steps, security claim with `security_impact: none`, a `passed`
status with no evidence, etc.) rather than stopping at the first one.

## Regenerating the changelog pages

```bash
python scripts/changelog/generate.py
```

Deterministic and idempotent — running it twice against the same fragments
and registry produces byte-identical output. Run it after adding or
editing a fragment, and commit the regenerated pages alongside the
fragment.
