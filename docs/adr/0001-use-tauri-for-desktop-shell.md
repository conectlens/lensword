# ADR 0001: Use Tauri 2 for the desktop shell

- Status: Accepted
- Date: 2026-07-23
- Decision owners: LensWord maintainers
- Related issues: [#29](https://github.com/conectlens/lensword/issues/29),
  [#30](https://github.com/conectlens/lensword/issues/30),
  [#31](https://github.com/conectlens/lensword/issues/31)

## Context

LensWord needs a desktop shell for macOS, Windows, and Linux. The shell must:

- load the existing Vite, React, and TypeScript frontend without rewriting it;
- support native reminder notifications on all three target operating systems;
- produce signed, installable artifacts in CI;
- keep both a remote API and a future bundled FastAPI backend viable until
  [the backend-mode decision](https://github.com/conectlens/lensword/issues/17)
  is made; and
- expose the smallest practical native attack surface to frontend code.

The two candidates considered were Tauri 2 and Electron. Electron provides a
single bundled Chromium runtime, a JavaScript main process, and mature desktop
APIs. Tauri uses each operating system's webview, a Rust host process, and
explicit capabilities for access to native commands and plugins.

## Decision

Use **Tauri 2** for the LensWord desktop shell.

Phase 3.1 will wrap the unmodified `frontend` production build in a Tauri
project. Desktop-only integration will live outside `frontend/src` except for
small, typed adapter boundaries that are also usable in the browser build.

This decision does not choose between a bundled local backend and a remote-only
desktop mode. Tauri supports external binaries, including Python API servers
packaged as self-contained executables, so both options remain available for
the separate Phase 3.4 decision.

## Decision drivers

The drivers are ordered by importance.

1. **Least privilege.** Native access must be denied unless a window needs a
   named capability. The initial shell only needs the notification permission
   and any narrowly scoped commands required to select or start an API mode.
2. **Small distribution footprint.** LensWord should not bundle Chromium and
   Node solely to display an existing web application. Tauri uses the operating
   system webview and compiles its host into a native binary.
3. **Fit with the roadmap.** Tauri has maintained notification, sidecar,
   bundling, signing, and updater paths for the three target desktop platforms.
4. **Frontend reuse.** Tauri accepts a normal web frontend and can consume the
   current Vite build output.
5. **Operational clarity.** Platform-native CI jobs can build and sign each
   installer. A Rust toolchain is additional complexity, but it is isolated to
   the desktop shell.

## Options considered

| Criterion | Tauri 2 | Electron |
| --- | --- | --- |
| Existing Vite/React frontend | Supported directly | Supported directly |
| Runtime | OS webview plus compiled Rust host | Bundled Chromium and Node |
| Native API boundary | Capability-scoped commands and plugins | Preload/IPC boundary; renderer hardening is application-owned |
| Notifications | Official plugin on macOS, Windows, and Linux; Windows requires an installed app | Built-in cross-platform API with mature platform-specific options |
| Python backend | First-class external-binary/sidecar packaging path | Can spawn a packaged child process, but lifecycle and IPC are application-owned |
| Rendering consistency | Can differ with OS webview versions | Consistent bundled Chromium |
| Team/tooling cost | Adds Rust and platform webview prerequisites | Stays primarily in TypeScript/JavaScript |
| Installer/runtime cost | Does not bundle a browser runtime by default | Bundles Chromium and Node with the app |
| Security maintenance | Narrow allowlisted capabilities; OS services update the webview on supported systems | Must promptly ship Electron updates for Chromium, Node, Electron, and npm dependencies |

Electron's stronger notification surface and rendering consistency do not
outweigh its runtime footprint and broader privileged JavaScript environment
for LensWord's current needs. LensWord needs basic scheduled reminder toasts,
not advanced desktop automation.

## Security requirements

Phase 3 implementations must meet all of these requirements:

- Load only bundled frontend assets in the privileged webview. A remote server
  is an API origin, not a source of executable UI.
- Configure a restrictive content security policy. Do not leave Tauri's CSP
  disabled in production.
- Grant capabilities to exact windows or webviews and exact commands. Do not
  enable a plugin's broad default permission set when a smaller set is enough.
- Do not persist desktop authentication tokens in webview `localStorage`.
  Keep them behind a typed native adapter backed by operating-system credential
  storage, and expose only the minimum operations the frontend needs.
- Keep shell/process execution unavailable to frontend code. If a bundled
  backend is chosen later, start the fixed sidecar name from Rust and use fixed
  arguments rather than accepting a command line from the webview.
- If a bundled backend is chosen, bind it to a random loopback port, require a
  per-launch bootstrap secret, reject development JWT secrets, and terminate
  the child process when the shell exits.
- Allow API connections only to the configured local loopback endpoint or an
  explicit HTTPS origin. Never silently downgrade a remote API to HTTP.
- Store signing and updater keys only in CI secrets. Release artifacts must be
  signed, macOS artifacts must be notarized, and updater metadata must be
  signature-verified.
- Treat notification title and body as untrusted display text: limit their
  length and never interpret them as markup or commands.

## Performance and release gates

Phase 3.1 establishes a measured baseline on signed release builds; it must not
claim performance wins from framework marketing. Measurements include the full
process tree, including operating-system webview helpers. The shell is
acceptable when:

- the existing `npm run build` output loads without changes required solely for
  Tauri inside `frontend/src`;
- five cold and twenty warm launches per platform show warm median startup at
  or below 2 seconds and p95 at or below 3 seconds;
- idle shell memory is at or below 150 MiB after 60 seconds, or combined shell
  and sidecar memory is at or below 300 MiB if Python is bundled;
- idle CPU p95 stays below 1% during a 10-minute minimized or tray-resident run;
- twenty launch/quit cycles leave no child or sidecar processes after 5 seconds;
- an 8-hour tray soak shows no more than 10% memory growth;
- installer size is measured and recorded for `.dmg`, `.exe`/`.msi`, and
  `.AppImage`/`.deb`, with shell and bundled-backend costs reported separately;
- nested-route relaunch, keyboard navigation, authentication, API error
  handling, the core review flow, room drag-and-drop, and the mind map pass a
  packaged-app smoke test on macOS, Windows, and Linux;
- CI runs `cargo fmt --check`, `cargo clippy -- -D warnings`, Rust tests,
  frontend lint/build/tests, and a Tauri production build; and
- dependency and vulnerability scanning covers Cargo and npm lockfiles.

Phase 3.2 must additionally prove that an installed, signed package can request
notification permission and display a native reminder on each operating
system. Browser mocks and development-mode toasts do not satisfy that gate.

## Consequences

### Positive

- The shipped shell does not carry an extra browser and Node runtime by
  default.
- Native permissions can be reviewed as a small, explicit capability list.
- A bundled Python backend remains possible without requiring Python on the
  user's machine.
- The current frontend toolchain and browser deployment remain first-class.

### Negative

- Contributors building the desktop shell need Rust and operating-system
  webview prerequisites.
- System webviews can expose cross-platform rendering differences, so packaged
  smoke tests are required on every target OS.
- Tauri's desktop notification API is less feature-rich than Electron's in
  some areas. The current requirement is a basic reminder toast; interactive
  notification actions are not part of this decision.
- Release engineering still requires platform signing identities, macOS
  notarization, and native CI runners.

## Revisit triggers

Re-open this decision before Phase 3.3 only if a packaged Phase 3.1/3.2
prototype demonstrates one of the following with a reproducible test:

- a required reminder notification cannot be delivered reliably on a supported
  target OS;
- an OS-webview incompatibility breaks a core LensWord flow and cannot be fixed
  without forking the browser frontend;
- a bundled-backend proof of concept cannot securely supervise and terminate
  the packaged Python sidecar; or
- measured startup, memory, or installer results fail the gates above and an
  Electron spike materially improves the failing metric.

## Sources

Primary documentation consulted for this decision:

- [Tauri architecture](https://v2.tauri.app/concept/architecture/)
- [Tauri capabilities](https://v2.tauri.app/reference/acl/capability/)
- [Tauri notification plugin](https://v2.tauri.app/plugin/notification/)
- [Tauri external binaries / sidecars](https://v2.tauri.app/develop/sidecar/)
- [Tauri distribution](https://v2.tauri.app/distribute/)
- [Electron architecture](https://www.electronjs.org/docs/latest/)
- [Electron security checklist](https://www.electronjs.org/docs/latest/tutorial/security)
- [Electron notifications](https://www.electronjs.org/docs/latest/tutorial/notifications)
- [Electron packaging](https://www.electronjs.org/docs/latest/tutorial/tutorial-packaging)
