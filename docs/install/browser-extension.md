---
title: Browser Extension
description: Capture selected text from any webpage into a LensWord group — install, permissions, security model, and verified behavior.
---

# Browser Extension

LensWord Capture (`apps/browser`, Chrome MV3) saves text you select on any
webpage straight into a LensWord vocabulary group via a right-click context
menu. Choose it when you want to capture words while reading elsewhere on
the web, rather than typing them into LensWord by hand afterward.

It's real and functional today, but developer-mode only: no official
package is published anywhere, install is a manual "Load unpacked," and
there is zero CI coverage for this surface. Everything on this page was
verified directly against the current source and, where noted, against a
real running backend — not written from the manifest alone.

## Confirmed extension details

| | |
|---|---|
| Manifest version | 3 |
| Extension version | `0.1.0` (`manifest.json`) |
| Supported browsers | Chromium-based (Chrome; Edge/Brave/Opera share the same extension platform but were **not individually tested**) |
| Firefox | **Not supported/not tested.** No `browser_specific_settings`, and MV3 API coverage differs enough between Firefox and Chromium that compatibility isn't assumed either way |
| Permissions (fixed) | `contextMenus`, `storage`, `notifications` |
| Permissions (optional, granted at save-time) | `optional_host_permissions: ["http://*/*", "https://*/*"]` declared in the manifest as the *possible* universe — but the actual runtime grant requested via `chrome.permissions.request()` is narrowed to just the origin computed from the API URL you enter, not a blanket grant |
| Popup | Three fields (API URL, access token, group ID) + Save; reads/writes `chrome.storage.local` |
| Context menu | One item, `contexts: ['selection']` — only appears when text is selected, never injected unconditionally |
| Backend call | `POST {apiUrl}/api/v1/groups/{groupId}/words` with `Authorization: Bearer {token}`, body `{ term, target_language: "Spanish", translations: [] }` |
| Default target language | Hardcoded `"Spanish"` — saving into a group with a different target language still succeeds (the backend doesn't cross-check word language against group language), so the saved word's language tag won't match a non-Spanish group |
| Packaging/release state | No package published anywhere (Chrome Web Store or otherwise); source-only |

## First-success guide

### 1. Load the unpacked extension

1. Open `chrome://extensions`.
2. Enable **Developer mode** (top right).
3. Click **Load unpacked** and select the `apps/browser` folder.

There is no packaged/store build to install instead — see
[Packaging state](#packaging-and-compatibility) below for exactly why and
what a package would look like if you build one yourself.

### 2. Configure it

Open the extension's popup (click its toolbar icon) and fill in:

![Browser extension popup with API URL, access token, and group ID fields](../media/screenshots/browser-popup.webp)

*Shown rendered standalone (`popup.html` opened directly), not loaded as an
extension — `chrome://` pages are outside this documentation's browser
automation, see [Verified capture flow](#verified-capture-flow) below.*

- **API URL** — your LensWord backend, e.g. `http://localhost:18420` for
  the [Docker Compose quick start](/setup/), or your server's HTTPS origin
  if self-hosted.
- **Access token** — see [Getting your token](#getting-your-token-safely) below.
- **Group ID** — the numeric ID of the group you want captures saved into
  (visible in the group's URL in the web app, e.g. `/groups/1` → `1`).

Clicking **Save settings** triggers a Chrome permission prompt for the
specific origin you entered — this is `chrome.permissions.request()` asking
for exactly that origin, not a broad grant. Accepting it is required; the
extension can't reach your server without it.

### 3. Capture a word

1. Select text on any webpage.
2. Right-click the selection → **Save "…" to LensWord**.
3. A native notification confirms the save (or explains what went wrong).
4. Open the group in the LensWord web app to see the word, then enrich it
   (translation, example sentence, mnemonic) there — the extension only
   captures the term itself.

### Getting your token safely

The extension has no login flow of its own — it expects a bearer token you
already have. The safest way to get one without exposing your password:
log into the LensWord web app, open browser DevTools → Application →
Local/Session storage (or Network tab on any authenticated request) to copy
the access token your own session is already using, then paste it into the
popup. Treat it like a password: anyone with it can act as you against the
LensWord API until it expires or is revoked (see
[Security & privacy](#security-privacy) below).

## Verified capture flow

`chrome://` pages can't be driven by this documentation pass's browser
automation tooling, so the popup/context-menu UI itself was verified by
source review rather than a live click-through. The **backend half of the
capture flow was verified live**: the exact request `service-worker.js`
makes was reproduced against a real `docker compose up --build` instance.

```bash
curl -X POST "http://localhost:18420/api/v1/groups/1/words" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"term":"la ventana","target_language":"Spanish","translations":[]}'
# → HTTP 201, full word object returned
```

Failure paths were verified the same way:

| Scenario | Result |
|---|---|
| Invalid/expired token | `401 {"detail":"Could not validate credentials"}` |
| Nonexistent group ID | `404 {"detail":"Group '99999' was not found"}` |

Both messages are specific enough to act on and don't leak anything beyond
what the request itself already implied — matching the verification
matrix's "failure states are understandable and do not leak secrets."

**A real bug was found and fixed during this pass:** all three
`chrome.notifications.create()` calls in `service-worker.js` referenced
`iconUrl: 'icon.svg'`. Chrome's notifications API does not support SVG
icons (confirmed against Chrome's own extension documentation and a
reported "Unable to download all specified images" failure for the same
pattern) — every capture notification would have shown with a missing or
broken icon. Fixed to reference the PNG icon set added in the brand-assets
work (`icons/icon48.png`).

## Security & privacy

- **Page content is read only after you explicitly select text and choose
  "Save to LensWord" from the context menu.** The content script/menu is
  scoped to `contexts: ['selection']` — there is no background scanning,
  no automatic capture, and no access to page content outside that
  explicit action.
- **Host permission is limited to your configured API origin, not every
  site.** The manifest declares a broad *optional* permission
  (`http://*/*`, `https://*/*`) because it can't know your server's origin
  in advance, but the actual grant Chrome asks you to approve — via
  `chrome.permissions.request({ origins: [origin] })` in `popup.js` — is
  computed from the exact API URL you typed in, and nothing broader is
  ever requested.
- **Token storage:** your access token is stored in `chrome.storage.local`
  — local to this browser profile, not synced to Google's servers the way
  `chrome.storage.sync` would be, and not exposed to web pages.
- **Manually copying a bearer token carries real risk:** it's a live
  credential with the same reach as your normal login session until it
  expires or is revoked. Don't paste it anywhere other than this popup,
  and treat leaking it as equivalent to leaking your password.
- **Logout/revocation:** the extension has no logout button. To revoke
  access, clear the token field in the popup and save (removes it from
  `chrome.storage.local`), and separately invalidate the token
  server-side if you're concerned it was exposed — this extension has no
  session-management UI, so revocation is a backend/account concern, not
  something the extension itself provides.
- **Tenant ownership is enforced server-side, not by the extension.** The
  extension merely sends a bearer token; every authorization decision
  (does this token's owner have write access to this group?) happens in
  the backend, the same as any other API client. The extension proves
  nothing about backend security on its own — it's a thin client over the
  same authenticated API the web app uses.

## Packaging and compatibility

There is no build step — `apps/browser` is plain static files loaded
directly, confirmed by the absence of any bundler config or build script in
the directory. A distributable package is just a zip of the source:

```bash
cd apps/browser
zip -r -X lensword-capture-0.1.0.zip . -x ".*"
shasum -a 256 lensword-capture-0.1.0.zip
```

(PowerShell equivalent: `Compress-Archive -Path * -DestinationPath lensword-capture-0.1.0.zip`.)

Running this against the current source (this documentation pass)
produced an 11-file, 18,998-byte archive with sha256
`158bc210de3d0df959c762402cc3e3f8b60f393382c11228252c5e516c788ef7` — **this
exact hash will change the moment any extension file changes**; it's
recorded here as a worked example of the command, not a value to check
future builds against. Re-run the command yourself to get the current one.

This zip is for sideloading/manual distribution only — it is **not** what
the Chrome Web Store expects for a store listing (which has its own review
and packaging process this project hasn't gone through), and there is no
official artifact of any kind published today. Don't conflate "I built a
zip" with "this is published" — nothing here is.

## Troubleshooting

- **Context-menu item doesn't appear** — it only shows when text is
  selected (`contexts: ['selection']`); right-click without a selection
  and it won't be there. Reload the extension from `chrome://extensions`
  if it's missing even with text selected.
- **Extension can't reach the API** — check the API URL in the popup is
  correct and that you accepted the permission prompt when saving
  settings; without a granted host permission, every request is blocked
  by Chrome before it leaves the browser.
- **Invalid/expired token** — capture fails with a notification showing
  `Could not validate credentials`; get a fresh token (see
  [Getting your token safely](#getting-your-token-safely)) and re-save it in the popup.
- **Incorrect group ID** — capture fails with `Group '<id>' was not
  found`; check the ID in the group's URL in the web app.
- **Host permission rejected** — if you decline the Chrome permission
  prompt, settings are not saved (the popup shows an error) and no
  capture will work until you save again and accept it.
- **HTTPS/CORS/origin mismatch** — the extension calls the API directly
  from the service worker, not from a page context, so browser CORS
  enforcement doesn't apply the same way it does to the web app; a
  self-hosted server over plain HTTP works for the extension even though
  browsers increasingly restrict mixed content elsewhere. This is a
  narrower attack surface than the web app's CORS story, not a stricter
  one — don't assume HTTPS is enforced here just because it matters
  elsewhere in this project.
- **Word created but translation/enrichment missing** — expected. The
  extension only ever sends `term`, hardcoded `target_language: "Spanish"`,
  and empty `translations`. Open the word in the web app or MnemoLab to
  add a translation, example sentence, or mnemonic.
- **Browser doesn't support the declared manifest/features** — this is an
  MV3 extension; browsers without MV3 support (old Chrome versions, or
  browsers that never adopted it) can't load it at all. Not tested against
  any specific minimum Chrome version.

See [docs/internal/repo-audit.md](https://github.com/conectlens/lensword/blob/development/docs/internal/repo-audit.md)
for the evidence behind this surface's overall release status, and
[Choose your surface](/learn/choose-a-surface) for how it compares to the
other ways to use LensWord.
