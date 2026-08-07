---
title: Desktop Application
description: Building and running LensWord's desktop shell, and what's verified vs. not.
---

# Desktop application

LensWord has a desktop shell ([Tauri 2](https://v2.tauri.app)) under
`apps/desktop/`. It hosts the same frontend build as the browser version and
talks to a LensWord server over the network —
[ADR 0002](../reference/adr/0002-desktop-backend-mode.md) decided the first release is
**remote-only**, so the app does not bundle a database or a Python runtime and
needs a server to point at.

## Installing

Tagged releases build installers for all three platforms and attach them to a
GitHub release: `.dmg` for macOS, `.msi`/`.exe` for Windows,
`.deb`/`.AppImage` for Linux.

> **No release has been published yet.** Until one is, build from source with
> the instructions below. When a release does exist, its artifacts are
> **unsigned** unless the repository's signing secrets are configured — macOS
> will show a Gatekeeper warning and Windows a SmartScreen one. See
> [docs/releasing.md](../reference/releasing.md).

## Building from source

Requires a Rust toolchain ([rustup](https://rustup.rs)) and your platform's
webview development packages, listed in the
[Tauri prerequisites](https://v2.tauri.app/start/prerequisites/).

```bash
(cd apps/frontend && npm ci && npm run build)   # the shell embeds this build
(cd apps/desktop && npx @tauri-apps/cli@2 build)
```

The artifact lands under `apps/desktop/target/release/bundle/`. On macOS, add
`CI=1` if you are building over SSH or from a headless process — the `.dmg`
step ends with an AppleScript that needs a GUI session.

CI currently builds and tests the desktop shell on **macOS and Linux only**
(`.github/workflows/ci.yml`); Windows is only built by the release workflow
when a `v*` tag is pushed, which has never happened against this repository.

## Pointing it at a server

The endpoint is read from `LENSWORD_API_URL`, then from an `api-endpoint` file
in the OS application-config directory, then defaults to
`http://127.0.0.1:8000`.

It must be a **loopback address or an `https://` origin**. Plain HTTP to a
remote host is refused rather than silently accepted, so a self-hosted server
the shell will talk to has to serve HTTPS.

## What works, and what is not yet verified

The shell stores your authentication token in the operating system's
credential store (Keychain, Credential Manager, Secret Service) rather than in
webview `localStorage`, and it polls for reminder notifications and raises
native toasts with Start / Remind later / Skip today actions.

**No toast has been observed on any operating system.** The path is
unit-tested end to end, but confirming it needs a signed packaged build
(ROADMAP 3.1). Treat native notifications as implemented and unverified.

Startup, memory and installer-size figures have not been measured either, but
the harness that will measure them exists: `scripts/desktop-baseline.py`. Point
it at a packaged build and it reports every ADR 0001 Phase 3.1 gate with a
pass/fail against the documented bar. Run without `--signed` it labels every
figure `NOT-THE-GATE` and exits non-zero, because signing and notarisation
change startup time and an unsigned number flatters the result. It also prints
the packaged-app checks that need a person, so a report cannot look complete
without them.

See [docs/internal/repo-audit.md](https://github.com/conectlens/lensword/blob/development/docs/internal/repo-audit.md) for the full
evidence behind the desktop surface's release status.
