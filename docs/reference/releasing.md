---
title: Releases & Compatibility
description: How a desktop release is cut, and what "verified" means for one.
---

# Releasing

Pushing a `v*` tag builds the desktop shell on macOS, Windows and Linux and
attaches the installers to a **draft** GitHub release
(`.github/workflows/release.yml`).

```bash
git tag v0.1.0
git push origin v0.1.0
```

The release is a draft on purpose. Whether a given run was signed is not
visible from the workflow's green tick, so a tag should never publish
installers without someone looking at them first.

## Signing

**Everything below is optional, and the workflow produces installers without
any of it.** Those installers are unsigned: macOS shows a Gatekeeper warning
and Windows shows a SmartScreen one, and neither can be dismissed by the user
in a way that scales past "developer testing it on their own machine".

ADR 0001 requires signed — and on macOS, notarized — artifacts before the
measured startup/memory baseline (issue #65) can be taken. That gate is on
signing being configured, not on the packaging workflow existing.

These are **GitHub Actions repository secrets**, not environment variables in a
`.env` file. Add them under *Settings → Secrets and variables → Actions*.

### macOS

| Secret | What it is |
| --- | --- |
| `APPLE_CERTIFICATE` | Base64 of the *Developer ID Application* `.p12` |
| `APPLE_CERTIFICATE_PASSWORD` | Password that `.p12` was exported with |
| `APPLE_SIGNING_IDENTITY` | e.g. `Developer ID Application: Your Name (TEAMID)` |
| `APPLE_ID` | Apple ID used for notarization |
| `APPLE_PASSWORD` | An **app-specific** password, not the account password |
| `APPLE_TEAM_ID` | 10-character team identifier |

```bash
base64 -i certificate.p12 | pbcopy    # value for APPLE_CERTIFICATE
```

Notarization needs all six. With only the first three the app is signed but
not notarized, which still trips Gatekeeper on a machine that has never seen
it.

### Windows

| Secret | What it is |
| --- | --- |
| `WINDOWS_CERTIFICATE` | Base64 of the code-signing `.pfx` |
| `WINDOWS_CERTIFICATE_PASSWORD` | Password that `.pfx` was exported with |

```bash
base64 -i certificate.pfx           # value for WINDOWS_CERTIFICATE
```

The signing command is injected into `tauri.conf.json` by the workflow rather
than committed there. A `signCommand` in the tracked config would run on every
Windows build, so a fork or an unconfigured repository would invoke `signtool`
with no certificate and fail the release instead of producing an unsigned
installer.

Signatures are timestamped against DigiCert's server. Without a timestamp a
signature stops validating the day the certificate expires — including on
installers people downloaded long before that.

### Updater

| Secret | What it is |
| --- | --- |
| `TAURI_SIGNING_PRIVATE_KEY` | Key that signs update manifests |
| `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` | Its password |

```bash
npx @tauri-apps/cli@2 signer generate -w ~/.tauri/lensword.key
```

Only needed once an auto-updater is wired up; nothing consumes update
manifests yet.

### Linux

`.deb` and `.AppImage` are not signed. Linux distribution normally signs at the
repository level rather than per artifact, and there is no repository yet.

## Verifying a release

The workflow has been exercised, but **no installer has been run on any
operating system**. Before treating a tag as a real release:

- macOS: `spctl -a -vv -t install LensWord.app` should report *accepted* and a
  source of *Notarized Developer ID*.
- Windows: the `.exe` properties dialog should show a *Digital Signatures* tab.
- All three: install, launch, sign in, and confirm a reminder produces a native
  notification — the one part of the notification stack (#27 → #31 → #88) that
  has never been observed end to end.

## Deployment

The server side is separate and has no release workflow. See `README.md` for
Docker Compose, and `.env.example` for the stack's configuration.
