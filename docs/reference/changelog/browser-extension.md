---
title: Browser Extension Changelog
description: User-facing changes to Browser Extension, with verification evidence per entry.
---

# Browser Extension changelog

Status — Browser Extension: **unreleased**.

Every entry states exactly what was verified — a passing automated test does not imply a platform was manually checked, and a manual check on one OS does not imply another. See [Verification levels](/reference/trust/verification-levels) for what each status means.

<a id="browser-extension-signin-flow"></a>

### Changed: The browser extension popup now signs in with your LensWord email and password and lets you pick a group from a dropdown, instead of asking you to paste a raw access token and type a numeric group ID by hand.

*2026-08-10* — verification: manual checks — macos: passed

Anyone loading the extension now signs in with their LensWord account instead of hunting for a bearer token in DevTools and typing a group ID from a URL. An expired session now shows a distinct "sign in again" notification rather than a generic failure. Loading the extension for local development requires running `npm run build:debug` in apps/browser first — it previously worked with zero build step.

<details><summary>Technical detail</summary>

popup.js replaces the manual token/group-ID form with email+password sign-in against POST /api/v1/auth/login, followed by GET /api/v1/groups to populate a <select>. Only the resulting access token, chosen group ID, and email are persisted to chrome.storage.local; the password is sent once and never stored. service-worker.js now distinguishes a 401 (expired token) from other capture failures with its own notification and clears the stale token automatically. The API URL is no longer a popup field: it is a fixed value baked into a generated config.js at build time (build-config.mjs), sourced from apps/browser/.env.local (debug, http://localhost:18420) or .env.production (release, the hosted API) — both popup.js and service-worker.js import API_URL from it, so building config.js (npm run build:debug or build:release) is now a required step before loading the extension. Also fixes a CSS bug where `section { display: grid }` overrode the `hidden` attribute's default `display: none` (author styles beat UA styles regardless of specificity), which had made the signed-in and signed-out sections of the popup render simultaneously, and switches the popup's color scheme from a generic blue to the project's brand tokens (#ffde59/#f5c400/#121212).

</details>

**Known limitations:**
- Sign-out only clears local extension storage; it does not revoke the access token server-side. Compromised-token concerns still require revoking the token from the account, same as before this change.
- No password reset, 2FA, or "remember multiple accounts" support — one signed-in account at a time, same constraint the previous manual-token flow had.

References: [PR #356](https://github.com/conectlens/lensword/pull/356)

<a id="cloud-ai-provider-adapters"></a>

### Added: AI_PROVIDER now accepts gemini, vertex, or openai alongside the existing none/ollama, so a hosted deployment that cannot run its own Ollama daemon can still enable real AI features (mnemonic suggestions, vocabulary extraction/enrichment, the conversation tutor, learning paths, and the companion coach).

*2026-08-08* — verification: automated tests: passed

Self-hosters and the LensWord Cloud deployment can enable AI features on a platform that cannot run Ollama (e.g. Render) by setting AI_PROVIDER=gemini/vertex/openai and the corresponding API key/project ID, instead of being limited to a local-only Ollama install or no AI at all. No change for an existing AI_PROVIDER=none or AI_PROVIDER=ollama deployment.

<details><summary>Technical detail</summary>

Refactored OllamaProvider onto a new _TextGeneratingProvider Template Method base (app/infrastructure/ai_providers/base.py) — request construction, JSON/candidate parsing, and the companion-coach evidence/forbidden-claim contract (validate_generated_content) moved up from OllamaProvider into the shared base, behind two abstract hooks (_generate_text/_generate_json) every concrete adapter implements. Added GeminiProvider and VertexAIProvider (google-genai SDK, sharing one _GoogleGenAIProvider base since both call client.aio.models.generate_content identically and differ only in how the client is constructed — API key vs. Application Default Credentials) and OpenAIProvider (openai SDK). Registered in both SUPPORTED_AI_PROVIDERS tuples and build_ai_provider, which fails fast at startup with a clear ValueError if a cloud provider is selected without its one required field (GEMINI_API_KEY / VERTEX_PROJECT_ID / OPENAI_API_KEY). Generalized the admin ai-settings API: AISettingsResponse now reports gemini_api_key_set/openai_api_key_set booleans rather than ever echoing a configured key back, and PUT treats a blank key as "leave the stored one alone." /probe stays a real reachability+model-list check for Ollama but does not fire a billed generation call for a cloud provider on every admin page load — it reports whether the required credential looks configured instead (live_check_performed on the response marks the difference explicitly).

</details>

**Known limitations:**
- Gemini, Vertex AI, and OpenAI adapter code is covered by unit tests against a mocked transport only. No live-model verification pass has been run against a real Gemini, Vertex AI, or OpenAI account — no credentials were available in the environment this was built in. See docs/install/cloud-ai-providers.md's "Verification status" section.
- Vertex AI's Application Default Credentials resolution has not been verified end-to-end in an actual Docker/Render deployment — only that the google-genai SDK's own credential-loading path is reached correctly in a mocked-transport test.

References: [#315](https://github.com/conectlens/lensword/issues/315)

<a id="byok-ai-credentials"></a>

### Added: Signed-in users can now supply their own Gemini, OpenAI, or Vertex AI key on the Settings page ("Bring Your Own Key") and have it used automatically for their own AI requests, instead of being limited to whatever the deployment itself is configured with (or nothing, if the deployment has AI switched off).

*2026-08-08* — verification: automated tests: passed

A signed-in user can add, update, or remove their own Gemini/OpenAI/ Vertex AI key from the Settings page. Once added, their own AI requests (mnemonic suggestions, vocabulary enrichment, the conversation tutor, learning paths, the companion coach) use that key automatically. No change for a user who does not configure one — AI features work exactly as before, off the deployment's own configuration.

<details><summary>Technical detail</summary>

New user-scoped API (GET/PUT/DELETE /api/v1/me/ai-credentials[/{provider}]) alongside the existing admin-only, deployment-wide /api/v1/ai-settings — no admin opt-in gate required per user. Provider-agnostic Strategy pattern for extensibility: CredentialSchema subclasses per provider (app/domain/services/ai_credentials.py, zero third-party imports, matching the domain layer's existing boundary) registered in PROVIDER_CREDENTIAL_SCHEMAS validate each provider's own payload shape (a bare api_key for Gemini/OpenAI; a GCP service-account JSON plus project_id/location for Vertex AI) and declare which fields are safe to echo back (Vertex's project_id/location) versus never (the secret). A new provider needs one schema class plus one builder function in app/infrastructure/ai_providers/credential_mapping.py — nothing else in the stack changes. Stored encrypted (UserAICredentialModel, migration 20260808_01_user_ai_credentials) with application-level authenticated encryption (cryptography.fernet.Fernet) under one master key, AI_CREDENTIAL_ENCRYPTION_KEY — deliberately not a cloud KMS/Vault, to avoid adding a second service to this project's self-hosted-first Docker/Render/SQLite posture. The first reversibly-encrypted secret this codebase has ever stored; every other credential (passwords, OAuth tokens) is one-way hashed. resolve_ai_provider_for_user (app/api/deps.py) is the shared precedence policy behind every AI-serving route (twelve REST endpoints via PerUserAIProvider, plus the MCP invocation boundary via app.api.mcp_auth.get_ai_provider_for_actor, which resolves caller identity differently — a remote MCP OAuth token is not a login JWT): no stored credential falls back to the deployment default unchanged; a user's single stored credential is used regardless of the deployment's own provider; with more than one, whichever matches the deployment's own AI_PROVIDER wins, otherwise it falls back rather than guessing. A credential that exists but is currently unusable (wrong encryption key, unusable key material) deliberately raises the same AIProviderUnavailableError every other provider failure does, rather than silently falling back and spending the deployment's own budget on a user's broken personal key. New Settings page section (ByokCredentialsCard) mirrors the existing MCP connection credential field's write-only pattern: every field is password/textarea input, nothing is ever pre-filled from a saved value.

</details>

**Known limitations:**
- Fully covered by unit tests against a mocked transport only — no real Gemini/OpenAI/Vertex AI credentials were available to verify a live round trip through a user's own stored key. See docs/install/cloud-ai-providers.md's "Bring Your Own Key" section.
- This is the first reversibly-encrypted secret this codebase has ever stored (every prior credential is one-way hashed) and handles real financial-risk credentials. A focused security review was performed before this reached development, which found and this fragment's change fixes one SSRF (a self-signed Vertex AI service_account_json's token_uri, trusted verbatim by google-auth's own token-refresh HTTP call, could be pointed at an internal address such as the cloud metadata endpoint — closed by allowlisting token_uri to Google's real OAuth endpoint, since a genuine key never has any other value). No other findings survived the review's false-positive filtering pass.
- A user who configures credentials for more than one provider, neither matching the deployment's own AI_PROVIDER, cannot currently choose explicitly which one is used — the system falls back to the deployment default in that specific case rather than guessing. No UI exists yet for an explicit "active provider" choice.
- There is no key-rotation or re-encryption tooling if AI_CREDENTIAL_ENCRYPTION_KEY itself needs to change after credentials have already been stored under the old one.

<a id="lensword-documentation-site"></a>

### Documentation: LensWord has a real documentation site (docs/, built with VitePress), organized around Diátaxis (Setup tutorial, Install how-to guides, Learn explanation, Reference material) — replacing a flat, uncurated docs/ folder.

*2026-08-07* — verification: automated tests: passed; artifact build: passed; manual checks — windows: passed; production observation: not_applicable

Every surface (Web, Desktop, Browser Extension, MCP Server, Local CLI) now has a real, verified guide instead of scattered or missing documentation — including install steps, security/privacy behavior, and an honest account of what has and hasn't been tested for that surface.

<details><summary>Technical detail</summary>

docs/.vitepress/config.mts defines the site; every existing doc was moved (not deleted) into the new structure, apps/browser/README.md and apps/mcp/README.md are pulled in via VitePress's markdown @include feature so they can't drift from source, and a SurfaceChooser Vue component reads docs/internal/product-registry.json directly so the surface-comparison table can't drift from the audit that backs it.

</details>

**Known limitations:**
- GitHub Pages deployment for the site is wired up but not yet enabled (repository Settings -> Pages -> Source is still unset) — the site builds successfully in CI but has no public URL yet.

References: [#272](https://github.com/conectlens/lensword/issues/272), [PR #295](https://github.com/conectlens/lensword/pull/295)

<a id="lensword-brand-identity"></a>

### Added: LensWord has a canonical logo and icon set for the first time — a favicon in the web app, real desktop app icons, and a real browser extension icon, replacing generic/unbranded placeholders.

*2026-08-07* — verification: automated tests: passed; artifact build: passed

The web app now has a real favicon and social-preview image, the desktop app has a real icon instead of Tauri's default, and the browser extension shows a real icon in the toolbar and extensions page instead of nothing.

<details><summary>Technical detail</summary>

Original SVG mark (lens + word-line) in brand/logo/svg/, with a reproducible generation script (scripts/generate-brand-assets.py) that derives every PNG/WebP/ICO/ICNS raster asset from the vector sources. Wired into apps/frontend's favicon/Open Graph tags, apps/desktop's Tauri icon set (replacing the default Tauri-generated placeholder), and apps/browser's manifest icons/action.default_icon (previously unset — the extension had no working icon at all, since MV3 doesn't accept SVG for that field).

</details>

**Known limitations:**
- Desktop icon change was not visually re-verified on a packaged installer (none has ever been built) — confirmed only that the icon files exist at the correct paths/sizes referenced by tauri.conf.json.

References: [#270](https://github.com/conectlens/lensword/issues/270), [PR #291](https://github.com/conectlens/lensword/pull/291)

<a id="browser-notification-icon-fix"></a>

### Fixed: Capture notifications ("Saved to LensWord", error notifications) now show the LensWord icon instead of a broken image.

*2026-08-07* — verification: not verified

Every capture notification (success or failure) now renders with a real icon instead of a missing-image placeholder.

<details><summary>Technical detail</summary>

service-worker.js's three chrome.notifications.create() calls referenced iconUrl: 'icon.svg'. Chrome's notifications API does not support SVG icons (confirmed against Chrome's own extension documentation and a matching real-world "Unable to download all specified images" bug report). Fixed to reference icons/icon48.png, the PNG icon set added by the brand-assets work.

</details>

**Known limitations:**
- Not confirmed by loading the extension into a real Chrome instance and observing a live notification — chrome:// pages could not be driven by this documentation session's browser automation. Fix is based on Chrome's documented SVG limitation plus a matching reported failure, not a directly observed broken/fixed notification.

References: [#275](https://github.com/conectlens/lensword/issues/275), [PR #299](https://github.com/conectlens/lensword/pull/299)
