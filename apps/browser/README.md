# LensWord Browser Extension

This Chrome MV3 extension captures selected text through the context menu and
creates a word in a configured LensWord group. It uses the existing authenticated
word endpoint, so tenant ownership and validation remain server-side.

## API URL

The backend URL is a fixed value baked in at build time, not something typed
into the popup — see `config.js` (generated, gitignored) and
`build-config.mjs`. It comes from one of two committed env files:

- `.env.local` → `http://localhost:18420`, used for local development.
- `.env.production` → the hosted production API, used for a real release.

## Build and load locally

1. `npm run build:debug` (or `npm run build:release` for a production
   build) — generates `config.js` from the matching env file above.
   Required before loading the extension; without it the popup and service
   worker fail to import `./config.js`.
2. Open `chrome://extensions`.
3. Enable Developer mode.
4. Choose **Load unpacked** and select `apps/browser`.
5. Open the extension popup and sign in with your LensWord email and
   password. Pick which group captures should be saved into from the
   dropdown. The popup requests host permission for the configured API
   origin only at sign-in time.

The first release uses `Spanish` as the target language and leaves translations
empty; the saved word can be enriched in LensWord afterward. No page content is
read until the user explicitly selects text and invokes the context menu.
