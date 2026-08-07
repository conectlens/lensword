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
type: added                            # added | changed | fixed | security | deprecated | removed | performance | documentation
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
    status: not_run                    # passed | failed | not_run | unavailable
    commands: []
    workflow_url: null
  artifact_build:
    status: not_run                    # passed | failed | not_run | unavailable
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
refactor, an internal test) still get a fragment; set
`documentation_required: false` and use a `user_impact` of `None — internal
change.` rather than skipping the fragment. A CI-enforced
`changelog: none` escape hatch with a mandatory reason (for truly
non-observable changes like typo fixes in code comments) is planned as
part of #282's CI enforcement; it doesn't exist yet, so every change
described in a pull request gets a real fragment for now.

## Validating fragments

```bash
python scripts/changelog/schema.py .changes/*.yml
```

Exits non-zero and prints every problem found (unknown product ID, invalid
enum value, missing required field, breaking change with no migration
steps, security claim with `security_impact: none`, etc.) rather than
stopping at the first one.

## Regenerating the changelog pages

```bash
python scripts/changelog/generate.py
```

Deterministic and idempotent — running it twice against the same fragments
and registry produces byte-identical output. Run it after adding or
editing a fragment, and commit the regenerated pages alongside the
fragment.
