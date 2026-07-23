# ADR 0002: Desktop backend mode — bundled local backend vs. remote-only

- Status: Proposed
- Date: 2026-07-23
- Decision owners: LensWord maintainers
- Related issues: [#17](https://github.com/conectlens/lensword/issues/17),
  [#30](https://github.com/conectlens/lensword/issues/30),
  [#65](https://github.com/conectlens/lensword/issues/65)
- Builds on: [ADR 0001](0001-use-tauri-for-desktop-shell.md)

## Context

ADR 0001 chose Tauri 2 for the desktop shell and deliberately left one question
open: whether the desktop application

- **bundles a local backend** — ships a self-contained FastAPI process as a
  Tauri sidecar so the user needs neither Docker nor a server, or
- **is remote-only** — talks to a hosted or self-hosted LensWord server over
  HTTPS, and ships only the shell plus the frontend.

ADR 0001 kept both viable: it records that "Tauri supports external binaries,
including Python API servers packaged as self-contained executables, so both
options remain available for the separate Phase 3.4 decision," and its
*Security requirements* already spell out what a bundled backend would have to
satisfy (random loopback port, per-launch bootstrap secret, rejection of
development JWT secrets, and child-process termination on shell exit).

The decision is genuine because it trades user convenience against distribution
size, release-engineering cost, and the security surface of supervising a child
process — and because it interacts with work already scheduled elsewhere on the
roadmap. Phase 4 (cloud, multi-tenant hosting on Postgres) is being built
regardless; the measured baseline that Phase 3.1 owes ADR 0001 (#65) has a
tighter budget when a Python sidecar is present (combined shell-and-sidecar
memory ≤ 300 MiB, versus ≤ 150 MiB for the shell alone).

The runtime endpoint contract that makes either mode possible already exists:
`frontend/src/lib/runtimeConfig.ts` resolves the API base URL from the Tauri
host at runtime, and the host validates that the endpoint is a loopback address
or an explicit HTTPS origin. Nothing in the current shell forecloses either
mode.

## Decision

**Recommended: ship the first desktop release remote-only, and keep the
architecture sidecar-ready rather than sidecar-dependent.**

Concretely:

1. The first desktop release connects to a user-supplied LensWord server — the
   hosted service delivered by Phase 4, or a self-hosted instance — over an
   explicit HTTPS origin, using the existing runtime-endpoint adapter.
2. No Python interpreter, backend code, or database is bundled into the desktop
   installer for this release.
3. The loopback branch of the endpoint contract is retained and kept working,
   so a later bundled-backend mode is an additive capability, not a rewrite.
4. The bundled-backend option is deferred, not rejected. It is revisited when
   the triggers below are met — most naturally after Phase 4 has produced a
   hardened, packageable backend.

This decision is a recommendation to the maintainers. Issue #17 remains open
until it is accepted, amended, or rejected.

## Decision drivers

Ordered by weight for LensWord's current stage.

1. **Smallest secure shell, soonest.** Remote-only ships the least code and the
   narrowest attack surface. It needs none of the child-process supervision
   that ADR 0001's security requirements demand of a bundled backend, so the
   first release does not block on that work being done correctly.
2. **Release-engineering cost.** Bundling a self-contained Python process
   multiplies signing and notarization work — the sidecar binary must itself be
   signed on macOS — and inflates installer size on every platform. Phase 3.3
   (#16) and the measured baseline (#65) are both cheaper without it.
3. **The convenience gap is already being closed elsewhere.** The primary
   argument for bundling is "no Docker, no server for the user." Phase 4's
   hosted deployment delivers exactly that convenience without putting a
   database and a Python runtime on every user's machine.
4. **Reversibility.** Choosing remote-only now preserves the bundled path;
   choosing bundled now would commit the project to sidecar supervision,
   per-user database migrations, and a larger signed artifact before any of
   that is required.
5. **Measured-baseline headroom.** A shell-only process is measured against the
   150 MiB idle budget; a bundled sidecar is measured against 300 MiB combined
   and adds an 8-hour soak surface for two processes instead of one.

## Options considered

| Criterion | Remote-only (recommended) | Bundled local backend |
| --- | --- | --- |
| User setup | Needs a reachable server (hosted or self-hosted) | None beyond installing the app |
| Installer size | Shell + frontend only | Adds a self-contained Python runtime and dependencies |
| Signing / notarization | One binary to sign per platform | Shell **and** sidecar binary to sign; larger notarization payload |
| Security surface | HTTPS client only | Loopback port binding, bootstrap-secret handshake, JWT-secret rejection, child-process lifecycle |
| Offline use | Unavailable without a reachable server | Available |
| Data location | On the server the user chose | On the user's machine (local SQLite/Postgres) |
| Measured-baseline budget (ADR 0001) | ≤ 150 MiB idle shell | ≤ 300 MiB combined shell + sidecar |
| Fit with Phase 4 | Directly consumes the hosted service | Diverges from the hosted path; two backend deployment shapes to maintain |
| Reversibility | Bundling remains available later | Reverting to remote-only means dropping shipped sidecar machinery |

The bundled backend's decisive advantage is genuine — zero-dependency offline
use is the most convenient possible experience, and for a single-user local
tool it is the natural default. It does not outweigh the cost for the *first*
desktop release, because that release lands before Phase 4's hardened backend
exists and because the convenience it buys is largely the convenience Phase 4
delivers by another route. The advantage grows once a packageable, secured
backend already exists; that is the condition the revisit triggers name.

## Consequences

### Positive

- The first desktop release ships the smallest, most auditable shell and does
  not depend on the correct supervision of a packaged Python child process.
- Release engineering signs one binary per platform, and the measured baseline
  (#65) is taken against the tighter, simpler shell-only budget.
- Desktop and hosted deployments share one backend deployment shape, so
  server-side fixes reach both without a second packaging path.

### Negative

- The desktop app is unusable without a reachable server, which is a real
  regression against the "no Docker, no server" convenience a bundled backend
  would offer. Users who want a purely local, offline install are not served by
  the first release.
- Self-hosters must stand up a server themselves until the hosted service
  (Phase 4) is available.
- The loopback branch of the endpoint contract is carried and tested without
  yet shipping a backend behind it, a small ongoing maintenance cost taken
  deliberately to keep the bundled path open.

## Revisit triggers

Re-open this decision and reconsider bundling a local backend when any of the
following holds:

- Phase 4 has produced a backend that can be packaged as a self-contained,
  signable binary and meets ADR 0001's bundled-backend security requirements in
  a reproducible test.
- User demand for a fully offline, server-free desktop install is demonstrated
  and is not satisfied by the hosted service.
- The hosted service is delayed such that remote-only leaves the desktop app
  without any usable backend for its intended audience.

## Sources

Primary documentation consulted for this decision:

- [Tauri external binaries / sidecars](https://v2.tauri.app/develop/sidecar/)
- [Tauri distribution and code signing](https://v2.tauri.app/distribute/)
- [Tauri capabilities](https://v2.tauri.app/reference/acl/capability/)
- [ADR 0001](0001-use-tauri-for-desktop-shell.md), *Security requirements* and
  *Performance and release gates*
