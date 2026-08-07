---
title: Verification Levels
description: What every verification status in LensWord's changelog actually means — and what it doesn't prove.
---

# Verification levels

Every changelog entry states exactly what was checked, using these
statuses. A status never implies more than what it directly tested — a
passing backend test proves the backend behaves as tested; it does not
prove a desktop notification displayed on Windows, and a successful Tauri
build does not prove an installer is signed, notarized, or installable.

| Status | Meaning |
|---|---|
| **Declared** | The change is described by whoever made it, with no attached verification evidence yet. |
| **Automated Tests Passed** | The relevant automated test suite completed successfully — scoped to what that suite actually exercises (a backend unit test doesn't test frontend behavior, a frontend unit test doesn't test a packaged browser extension). |
| **Artifact Built** | An installable or distributable artifact was produced successfully (a compiled binary, a Docker image, a zip package) — building is not the same as installing, launching, or using it. |
| **Manually Verified** | A person exercised the actual product or artifact on the stated target platform — the strongest evidence short of production use. |
| **Production Observed** | The behavior was observed in a real deployment or production-equivalent environment, not just a test run. |
| **Verification Unavailable** | Sufficient evidence could not be retrieved in this environment (e.g. no macOS/Linux host was reachable to verify a desktop build) — stated as an environment constraint, not a product finding. |
| **Not Verified** | No verification has been performed for this claim. |

## Why this matters, concretely

A few real examples from this repository's own changelog, because the
distinction is easy to state abstractly and easy to blur in practice:

- The [MCP read-tool fix](/reference/changelog/mcp) has automated tests
  passed (85+ backend tests, 124 `apps/mcp` tests) — but no real MCP
  client (Claude Desktop, Cursor, VS Code) was connected to confirm it
  from a client's perspective. The changelog entry says exactly that.
- The [Desktop Application](/install/desktop-app) has `cargo build`
  passing and a real, screenshotted launch on Windows — but macOS and
  Linux are marked `Unavailable`, not `Not tested` or silently omitted,
  because no host for either was reachable, which is a real gap distinct
  from "nobody has gotten around to it."
- CI compiling the desktop shell on `ubuntu-latest` is evidence the code
  *builds* on Linux. It is not evidence a packaged `.deb`/`.AppImage`
  installs and runs on a real Linux desktop — those are different claims,
  and this documentation doesn't conflate them.

## Where verification is recorded

Each changelog entry ([per product](/reference/changelog/), or the
[combined overview](/reference/changelog/)) states its own verification
line. The underlying data lives in structured fragments under
[`.changes/`](https://github.com/conectlens/lensword/tree/development/.changes)
— see [`.changes/README.md`](https://github.com/conectlens/lensword/blob/development/.changes/README.md)
for the exact schema, and [Release process](/reference/trust/release-process)
for how verification evidence accumulates into an actual release record.
