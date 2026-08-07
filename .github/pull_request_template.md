## Summary

<!-- What does this change do, and why? -->

## Related issues

<!-- Link any related issues, e.g. Closes #123 -->

## Changes

<!-- Bullet list of the notable changes -->

-

## Testing

<!-- How was this verified? Check off what applies and add commands/output where useful. -->

- [ ] `scripts/verify.sh` passes (runs all four gates below)
- [ ] `cd apps/backend && python -m pytest` passes
- [ ] `cd apps/frontend && npm run lint` passes
- [ ] `cd apps/frontend && npm run build` passes (type check + build)
- [ ] `cd apps/frontend && npm test` passes
- [ ] Manually verified in the browser / via API docs (describe below)

## Screenshots (if UI change)

<!-- Before/after screenshots for visual changes -->

## Checklist

- [ ] I've read [CONTRIBUTING.md](../CONTRIBUTING.md)
- [ ] I've updated relevant documentation (README, docstrings, etc.)
- [ ] I've added or updated tests covering this change
- [ ] This change does not introduce new secrets, credentials, or hard-coded environment-specific values

## Changelog fragment

<!--
Does this change anything a user of a LensWord product would notice —
new/changed/fixed behavior, a security fix, a deprecation? If so, add a
fragment under .changes/ (see .changes/README.md) naming the affected
product(s) and the verification actually performed, and validate it:

    python scripts/changelog/schema.py .changes/your-fragment.yml

No user-observable effect (internal-only, CI-only, docs-only)? Still add a
fragment, with `type: none` and a `reason` — see .changes/README.md.

CI enforces this (.github/workflows/changelog.yml, #282): a PR touching a
registered product's source with no fragment at all fails the build.
-->

- [ ] This PR changes user-observable behavior for one or more LensWord products, and I've added a validated fragment under `.changes/`
- [ ] This PR has no user-observable effect (internal-only change, docs-only, CI-only) — no fragment needed
- [ ] Affected product(s): <!-- web / desktop / browser-extension / mcp-server / local-cli / none -->
- [ ] Breaking change: <!-- yes (migration steps included in the fragment) / no -->
- [ ] Compatibility impact: <!-- e.g. requires a specific server/API version, or none -->

