# LensWord Browser Extension

This Chrome MV3 extension captures selected text through the context menu and
creates a word in a configured LensWord group. It uses the existing authenticated
word endpoint, so tenant ownership and validation remain server-side.

## Load locally

1. Open `chrome://extensions`.
2. Enable Developer mode.
3. Choose **Load unpacked** and select `apps/browser`.
4. Open the extension popup, enter the LensWord API URL, a bearer access token,
   and a group ID. The popup requests permission only for that configured API
   origin.

The first release uses `Spanish` as the target language and leaves translations
empty; the saved word can be enriched in LensWord afterward. No page content is
read until the user explicitly selects text and invokes the context menu.
