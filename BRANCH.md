# Branching rules

This document is the single source of truth for how code moves through
this repository. It exists because of a real incident: `main` was being
updated by cherry-picking individual fix commits directly onto it while
`development` kept its own copies of the same fixes. Both branches ended
up with the same *content* but different *commits* for the same change.
The next time `development` was merged into `main` (or `main` merged back
into `development` to clear a stale "out of date" PR banner), those
duplicate commits collided in generated history views —
`docs/reference/changelog/main-branch-activity.md`'s rolling
last-40-commits window filled up with two entries per change and pushed
real historical entries out of the window. Not a data-loss bug, but a
confusing, self-inflicted one. The rule that prevents it:

## The rule

**`main` only ever changes by merging a pull request from `development`.
No direct pushes to `main`. No cherry-picking individual commits onto
`main`. No exceptions for "urgent" fixes — an urgent fix still goes
through a PR, it just moves through review faster.**

```
feature/fix branch  →  PR  →  development  →  PR  →  main
```

- **`main`** — production. What Render (backend, MCP) and Cloudflare
  Pages (frontend) actually deploy from on every push. Only receives
  commits by merging a `development → main` pull request.
- **`development`** — the shared integration branch. All feature and fix
  branches target this, not `main`.
- **Feature/fix branches** — branch off `development`, named descriptively
  (`fix/review-session-timer`, `feat/mnemolab-voting`), merged back into
  `development` via PR (see `CONTRIBUTING.md`).
- **Promoting `development` to `main`** is its own explicit step, done
  when `development` is in a release-worthy state — not something that
  happens as a side effect of landing an unrelated fix.

## Before opening a `development → main` PR

`development` must be green first:

- All required CI checks passing on `development` itself (Backend,
  Backend on Postgres, Frontend, Docker build validation — whatever the
  repo's branch protection currently requires; check
  `Settings → Branches` if unsure).
- Changelog fragments valid (`python scripts/changelog/schema.py
  .changes/*.yml`) and the generated changelog pages committed
  (`python scripts/changelog/generate.py`, then check `git status` is
  clean).
- No open, unresolved merge conflicts against `main`.

Only then open (or update) the PR and let it merge normally.

## What this means in practice

- If `main` needs a fix that isn't yet on `development`: commit the fix
  to `development` first, let it pass CI there, then open/merge a PR to
  `main`. Do not push the fix to `main` directly "to save time" — that's
  exactly the pattern that caused the incident this document exists to
  prevent.
- If a `development → main` PR shows "out of date": update it by merging
  the *latest `main`* into the PR's branch (GitHub's "Update branch"
  button, or `gh api repos/<org>/<repo>/pulls/<n>/update-branch -X PUT`)
  — never by pushing directly to `main` to route around it.
- If a required status check is genuinely a false positive (a structural
  CI artifact, not a real failure) and bypassing it is truly necessary,
  that still happens through the PR merge (`gh pr merge --admin`), with
  the reason stated and the repo owner's explicit sign-off for that
  specific merge — not a direct push.
- Hotfix branches, if ever needed for a production-only emergency, still
  follow `branch → PR → main`; they are just prioritized for fast review,
  not exempted from the PR step.

## Why not just cherry-pick when it's faster?

Cherry-picking preserves *content* but not *commit identity* — the same
change becomes two different commits (different SHA) on the two
branches. Git's merge/diff tooling, this repo's changelog ledger
generator, and GitHub's own PR UI all reason about *commits*, not just
file content. Two independent copies of the same change look like two
different changes to all of that tooling, and the confusion compounds
every time the branches are reconciled. A PR merge keeps one commit
graph, one history, one source of truth.
