---
title: Desktop Application Changelog
description: User-facing changes to Desktop Application, with verification evidence per entry.
---

# Desktop Application changelog

Status — Desktop Application: **unreleased**.

Every entry states exactly what was verified — a passing automated test does not imply a platform was manually checked, and a manual check on one OS does not imply another. See [Verification levels](/reference/trust/verification-levels) for what each status means.

<a id="other-language-pronunciation-fallback"></a>

### Fixed: The pronunciation speaker button now works for words whose target language is "Other" (for example Russian, Arabic, or Chinese), instead of always being disabled.

*2026-08-11* — verification: automated tests: passed

A flashcard or review card in a language outside the fixed nine-language list (Russian, Arabic, Chinese, and others sharing those scripts) can now be heard, the same as any listed language, wherever a matching voice is installed. Where no matching voice exists, or the term's script isn't one of the ones recognized, the button stays visible and disabled with the reason on it, exactly as before.

<details><summary>Technical detail</summary>

SupportedLanguage is a closed nine-language enum; any word outside it (Russian, Arabic, Chinese, ...) is stored with target_language "Other", and localeFor('Other') correctly returns null since there is no honest locale to guess from that label alone (see speech.ts's own comment on why). PronunciationButton took that null as final and disabled itself unconditionally for every "Other" word, permanently — reported live against a Russian flashcard at lensword.conectlens.com/flashcards ("меня зовут") whose speaker button produced no sound. Added localeForText in speech.ts: a fallback that guesses a BCP-47 primary subtag from the term's own Unicode script (Cyrillic, Arabic, Hebrew, Greek, Devanagari, Han, Thai) — real evidence localeFor never had access to, since it only ever saw the "Other" label. PronunciationButton now tries this fallback only when the language label itself has no answer, and only ever overrides the disabled state, never a real language's own preferred locale.

</details>

**Known limitations:**
- Script coverage is Cyrillic, Arabic, Hebrew, Greek, Devanagari, Han, and Thai — an "Other" word in a language using a script outside this list (or written in Latin script, e.g. Vietnamese or Indonesian) still gets no locale to speak with and the button stays disabled.
- A script can span multiple languages (Han covers Chinese, Japanese kanji, and more); the guess picks one representative locale per script rather than distinguishing further.
- Not verified with real audio output in a browser — covered by tests against a mocked speechSynthesis, which cannot confirm how a voice actually sounds.

References: [#335](https://github.com/conectlens/lensword/issues/335), [PR #364](https://github.com/conectlens/lensword/pull/364)

<a id="flashcard-animations"></a>

### Changed: Flashcards now animate: each new card fades and slides in, and flipping a card plays a short flip animation instead of swapping the answer in instantly.

*2026-08-11* — verification: automated tests: passed

Flashcard practice at /flashcards feels less like an instant content swap and more like handling a physical deck. No change to what information is shown, when answers are gradable, or any keyboard/swipe behavior.

<details><summary>Technical detail</summary>

Adds card-enter and card-flip keyframes/utilities to tailwind.config.js and applies them in FlashcardStack.tsx — no new dependency. card-enter is applied to the whole stack, which already remounts per word via key={word.id} in FlashcardSessionPage, so the remount restarts the animation for every new card with no extra state. The flip is a scaleX pinch (1 -> 0 -> 1) rather than a true two-sided rotateY flip: a real 3D flip needs both faces present in the DOM at once (the back face hidden only via backface-visibility), but FlashcardStack.test.tsx asserts the hidden translation is genuinely absent from the DOM before reveal, not merely visually hidden, so both faces coexisting would regress that guarantee. The pinch swaps the single face's content at its narrowest point instead, keyed on `revealed` so only the content span remounts — the flip button itself never remounts, so keyboard focus survives a flip. Both animations are neutralized for anyone with prefers-reduced-motion: reduce via the existing global rule in index.css.

</details>

**Known limitations:**
- The flip is a horizontal pinch, not a literal 3D card flip, for the DOM-presence reason above.
- There is no exit animation when a card is answered and the next one appears; the outgoing card is unmounted immediately. The existing FlashcardStack.test.tsx suite asserts onAnswer fires synchronously on answer, and animating the exit would require deferring that call.
- Not verified visually in a real browser — covered by the existing component tests, which run in jsdom and do not execute CSS animation timelines.

References: [#338](https://github.com/conectlens/lensword/issues/338), [PR #364](https://github.com/conectlens/lensword/pull/364)

<a id="pronunciation-playback"></a>

### Added: Review and stabilization cards now have a speaker button that reads the word aloud in its own language.

*2026-08-10* — verification: automated tests: passed

A word can be heard in the language it is stored in while reviewing it, rather than read by whatever default voice the browser picked. Where playback isn't possible — no speech support, no installed voice for that language, or the "Other" language placeholder — the button stays visible and disabled with the reason on it, instead of silently doing nothing.

<details><summary>Technical detail</summary>

Adds lib/speech.ts (a Record<SupportedLanguage, string | null> mapping each stored language label to a BCP-47 tag, plus voice matching), lib/useSpeech.ts (a hook over window.speechSynthesis that subscribes to voiceschanged, because getVoices() is empty on first call in most browsers), and components/ui/PronunciationButton.tsx, wired into ReviewSessionPage and AcquisitionSessionPage. Voice selection prefers an exact locale match and falls back to any voice sharing the primary subtag, so a device carrying only es-MX still speaks Spanish. The issue described SupportedLanguage as free text with a KNOWN_LANGUAGES suggestion list; it is in fact a closed enum of ten values and KNOWN_LANGUAGES does not exist, so the mapping is exhaustive by type rather than open-ended. The pre-existing speechSynthesis call in PracticePage set no lang at all and now resolves one through the same layer. Adds a volume_up entry to the type-safe icon registry.

</details>

**Known limitations:**
- Playback uses the browser's own speech engine, so which voices exist and how good they sound is a property of the user's device and operating system, not of LensWord.
- The "Other" language stores no locale and cannot be spoken; the control is disabled and says so.
- Only one regional variant is preferred per language (for example pt-PT for Portuguese); a device with only the other variant installed falls back to it via primary-subtag matching, but the variant is not user-selectable.
- The button is on the review and stabilization cards only; the word list and MnemoLab card do not have it yet.
- Not verified with real audio output in a browser — the speech API is covered by tests against a mocked speechSynthesis, which cannot confirm how a voice actually sounds.

References: [#335](https://github.com/conectlens/lensword/issues/335)

<a id="mind-palace-3d"></a>

### Changed: Mind Palace rooms are now a navigable 3D space: orbit the room, select a word and click the floor to place it. The flat board remains available.

*2026-08-10* — verification: automated tests: passed; artifact build: passed

A room can be orbited and viewed as a space rather than a flat board, which is the point of a memory palace. Words already placed keep their positions and need no re-placing. A browser without WebGL gets the flat board and a message saying why, instead of an empty screen; the flat board is also still reachable by choice on browsers that do support 3D.

<details><summary>Technical detail</summary>

Adds three, @react-three/fiber and @react-three/drei, imported only by RoomScene3D, which RoomDetailPage loads through React.lazy. The build splits it into its own ~990 kB chunk; the main bundle is unchanged at ~516 kB. Placements keep the existing x_percent/y_percent contract — lib/roomSpace.ts reads them as coordinates on a square floor, which is what they already describe — so no migration is needed, no endpoint changed, and placements made before this feature appear in the 3D room as they are. floorToPercent applies the same 2-98 clamp as the 2D board so both views can store identical positions, and rounds to two decimals because unrounded round-tripping rewrote 2 as 2.0000000000000018 on every place-reload cycle. WebGL support is probed before mounting rather than caught after, since a failed context is a blank canvas that reads as an empty room. The renderer is disposed on unmount.

</details>

**Known limitations:**
- Not verified by looking at the rendered scene. jsdom has no WebGL, so the automated tests cover the coordinate mapping, the round-trip and the WebGL fallback decision — not whether the room actually looks right, which needs a person with a browser.
- Placements remain two-dimensional. Words sit on the floor plane; there is no height axis, because nothing stores one and adding it would be a schema change for an interaction that does not exist yet.
- The camera orbits and zooms but does not pan or walk, so the room is something you look around rather than move through.
- Words are placed by selecting one and clicking the floor. Dragging from the sidebar still works in the flat view only, since a drag has no meaning against a 3D surface.
- The 3D chunk is roughly 990 kB and is fetched the first time a room is opened in 3D.

References: [#339](https://github.com/conectlens/lensword/issues/339)

<a id="flashcard-swipe-practice"></a>

### Added: A Flashcards option on the dashboard practises due words by flipping a card and marking it known or not known, by swipe, button, or arrow key.

*2026-08-10* — verification: automated tests: passed

Due words can be practised by flipping a card and swiping instead of typing an answer, for people who want to skim rather than be tested. The existing multiple-choice and typed review modes are untouched, and both feed the same schedule. Answers cannot be recorded until the card is flipped, so a word is never marked known while its answer is hidden.

<details><summary>Technical detail</summary>

Adds FlashcardStack and FlashcardSessionPage at /flashcards, plus a Flashcards button on the dashboard beside the existing review CTA. It is a separate route rather than a sixth SessionMode: SessionMode is a backend enum describing when a session is taken (walking, night, study break), and flashcards are a way of answering that is orthogonal to all of them. The route starts an ordinary standard session and submits through the existing POST /api/v1/review/sessions/{id}/answers path via queueableRequest, so scheduling, streaks and summaries are the ones the existing mode already produces and no scheduling logic is added client-side. Known/not-known map onto the existing correct/incorrect outcomes rather than introducing new outcome states. Per-card state is reset by keying FlashcardStack on word.id — a remount — rather than an effect, so the next card cannot paint the previous card's answer.

</details>

**Known limitations:**
- Swipe is a pointer gesture only; the same two decisions are always available as buttons and as the left/right arrow keys, which is what keyboard and screen-reader users operate.
- There is no undo for a card already marked, and no way to reshuffle or revisit a card within a session.
- The session always requests 20 standard-mode due words; group scoping is available via a ?group= query parameter but has no UI entry point yet.
- Not verified in a browser with a real touch device — the gesture is covered by tests driving synthetic pointer events, which cannot confirm how the drag feels on hardware.

References: [#338](https://github.com/conectlens/lensword/issues/338)

<a id="edit-group-language"></a>

### Added: A group's name and target language can both be edited after creation, from an Edit button on the group card.

*2026-08-10* — verification: automated tests: passed

A group created with the wrong target language no longer has to be deleted and rebuilt. Words already in the group keep the language they were added with — the editor says so before saving, rather than leaving it to be discovered afterwards.

<details><summary>Technical detail</summary>

PATCH /api/v1/groups/{group_id} previously accepted only `name` (GroupRenameRequest) and no UI called it. The body is now GroupUpdateRequest, where `name` and `target_language` are each optional and an omitted field means "leave it alone", so the rename-only body existing callers send is unchanged; a body with neither field is a 422 rather than a silent no-op. RenameGroupUseCase becomes UpdateGroupUseCase, applying group-level attribute changes, and Group gains a `retarget` method alongside `rename`. A language change invalidates the cached per-user language profile (issue #342) because that cache is derived from which languages the learner studies; a rename deliberately does not, since it cannot affect the profile. Frontend replaces the unused groupsApi.rename with groupsApi.update and adds an EditGroupModal to GroupsPage.

</details>

**Known limitations:**
- Existing words are not offered a bulk language change; retargeting a group that already holds vocabulary leaves those words marked with their original language by design, and changing them is still a per-word edit.
- The edit affordance is on the group card in /groups only; GroupDetailPage has no group-level edit control yet.
- Not exercised in a browser; covered by backend API tests and a component test for the modal.

References: [#337](https://github.com/conectlens/lensword/issues/337)

<a id="companion-chat-assistant"></a>

### Added: A chat assistant is available from the main navigation on web and desktop. Conversations are saved to the account and can be picked up from any connected companion.

*2026-08-10* — verification: automated tests: passed

Users can hold a conversation with the assistant inside the app on web and desktop instead of only through an external MCP client. A provider that is switched off or temporarily down shows an explanatory message and never discards what was typed; when the companion feature is off for the account, the screen explains that rather than failing.

<details><summary>Technical detail</summary>

Adds POST /api/v1/companion/sessions/{id}/chat, which records the user's turn, asks the configured AIProvider via converse(), and records the answer — both as ordinary companion turns, so an in-app conversation stays readable, exportable and resumable through every existing companion route rather than living in a parallel store. The pre-existing POST /turns only records a turn an external MCP companion already produced and never calls a provider, so no endpoint could answer an in-app message before this. The user's turn is stored before the provider is called, and operation_id makes a retried send idempotent (the assistant half is keyed off the same id) so a retry returns the stored exchange instead of prompting the model twice. Frontend adds CompanionChatPage at /assistant, gated on the ai_companion_enabled recall setting, which is now exposed on the frontend RecallSettings type.

</details>

**Known limitations:**
- Replies are returned whole rather than streamed; the UI shows a "Thinking…" indicator for the duration of the call instead of incremental text.
- Sessions are not listed or resumable from the UI yet — ending a chat starts a fresh one next time, though the finished session remains readable through the existing companion export route.
- Corrections returned by the shared converse() contract are parsed but not displayed here; the conversation tutor at /tutor remains the surface that shows them.
- Not exercised against a live AI provider in a running deployment; the provider interaction is covered by tests using a stubbed provider.

References: [#343](https://github.com/conectlens/lensword/issues/343)

<a id="weekly-report-action-feedback"></a>

### Fixed: The weekly report's "Generate AI interpretation" and "Refresh factual snapshot" buttons now show a spinner while working and a visible message when they fail, instead of appearing to do nothing.

*2026-08-09* — verification: automated tests: passed

Pressing either button on the weekly report now gives immediate visible feedback, and a failure — most likely when generating the AI interpretation — is reported on screen with the report still readable, rather than silently doing nothing.

<details><summary>Technical detail</summary>

Both buttons in WeeklyReportPage.tsx called reportsApi.<...>().then(setReport) directly from onClick, with no loading state, no disabled state and no .catch, so a request in flight was invisible and a failed one produced an unhandled promise rejection with nothing rendered. Both now use Button's existing loading prop, which already renders a spinner and disables the control, so no new UI primitive was needed. A single pending-action state disables both buttons while either runs, since each replaces the whole report and racing them would leave whichever finished last silently winning. Action failures render inline through a separate actionError state, kept apart from the page-level error state that replaces the whole view — that is the right response to the report failing to load and the wrong one to a button failing. Retrying clears a previous failure.

</details>

**Known limitations:**
- The interpretation is generated in one request rather than streamed, so the feedback is a spinner for the whole wait rather than progressive output.
- Verified by component tests against a mocked reports API; the buttons were not exercised against a live AI provider.

References: [#344](https://github.com/conectlens/lensword/issues/344)

<a id="themed-select-component"></a>

### Fixed: Dropdowns now open in the app's own dark styling instead of the browser's white system popup, and every dropdown in the app uses the same control.

*2026-08-09* — verification: automated tests: passed

Opening any dropdown in dark mode now shows a dark, app-styled list instead of a white system popup. Keyboard and screen-reader operation is preserved, and dropdowns look and behave identically everywhere in the app rather than varying by screen.

<details><summary>Technical detail</summary>

components/ui/Select.tsx wrapped a native `<select>` and styled its `<option>` elements, which browsers very largely ignore because the open dropdown is OS-level chrome rather than part of the page — so the popup kept rendering light against the app's dark surface no matter what CSS was applied. Rebuilt on @radix-ui/react-select, an unstyled accessible listbox primitive, so the open list is ordinary markup the app themes itself. Radix was chosen over a hand-rolled listbox because the parts that are easy to get wrong are the ones nobody notices until someone depends on them: roving focus, typeahead, aria-activedescendant, returning focus to the trigger on close. All 16 raw `<select>` elements across 11 files were migrated to the shared component, along with the 4 existing call sites, so the audit the issue asked for is complete rather than partial. The API is value/onValueChange rather than a native change event, and gained a size variant for the compact inline dropdowns several toolbars use. Radix reserves the empty string for "nothing selected", so filters offering "Any" or "Leave unchanged" use an exported ANY_OPTION sentinel that call sites map back themselves. Test setup gained the jsdom stubs the primitive needs (hasPointerCapture, ResizeObserver, DOMRect) and a shared selectOption helper that drives the control by keyboard.

</details>

**Known limitations:**
- Visual QA across light and dark themes was not performed. The change is verified by unit tests asserting the open list is rendered by the app rather than as native popup chrome, which is the structural cause of the bug, but no dropdown was observed in a real browser in either theme.
- Adds a runtime dependency (@radix-ui/react-select) to a frontend that previously had only React, the router and the icon library. The bundle grows accordingly. The issue names this trade explicitly, on the grounds that a hand-rolled listbox trades bundle size for accessibility risk.
- The desktop shell's Content-Security-Policy was read and does permit the inline styles the primitive uses for positioning (style-src 'self' 'unsafe-inline'), but this was not confirmed by running the packaged desktop build.

References: [#341](https://github.com/conectlens/lensword/issues/341)

<a id="icon-name-type-safety"></a>

### Fixed: Two icons in the OAuth authorisation screen were silently drawing a placeholder glyph instead of the intended tick and empty circle, because they named icons the app does not define.

*2026-08-09* — verification: automated tests: passed

The consent screen's per-scope tick and empty-circle indicators now render correctly instead of a placeholder glyph. No other visible change — this is mostly a guarantee that a future mistyped icon name fails the build rather than shipping.

<details><summary>Technical detail</summary>

Completes issue #340. The migration from the Material Symbols ligature font to lucide-react removed the failure mode where a mistyped icon name rendered as literal text, but Icon.tsx still declared name as a plain string over a `Record<string, LucideIcon>` with a runtime fallback, so an unknown name survived to runtime as a placeholder glyph — quieter than before and no easier to catch in review. ICONS is now inferred with `satisfies` rather than annotated (annotating it widened the keys back to string, which would have made the new type mean nothing), IconName is keyof typeof ICONS, and the prop takes that type. Button.icon, EmptyState.icon and SettingsPage's ToggleRow propagate it, and the authored icon lists in LandingPage and RoomsPage are typed so a bad name fails where it is written. Server-stored names — a room's icon and a badge's icon — go through an explicit resolveIconName() that falls back to a named `unknown` entry, so the one place unchecked strings enter is visible rather than an inline cast. Turning the type on immediately surfaced check_circle and radio_button_unchecked, referenced by OAuthAuthorizePage and never defined; both are added.

</details>

**Known limitations:**
- The guarantee is a compile-time one, which no runtime test can observe directly. The accompanying tests pin the surface it rests on — the lookup table, the resolver's behaviour on unknown names, and the runtime fallback — rather than the type itself.
- The two corrected icons were verified by unit test, not by loading the OAuth consent screen in a browser.
- Icon names remain the Material Symbols vocabulary rather than lucide's own, deliberately: those strings are persisted server-side on rooms and badges, so renaming them would orphan existing rows.

References: [#340](https://github.com/conectlens/lensword/issues/340)

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

<a id="fix-desktop-build-and-selfhost-env-gaps"></a>

### Fixed: Fixed a desktop-installer build failure (never previously exercised by a real CI run) and a docker-compose self-hosting gap where Ollama/AI and remote-MCP settings couldn't be configured via .env.

*2026-08-07* — verification: automated tests: passed

A CI-built desktop installer (either release channel) now actually builds instead of failing during the frontend-embedding step. Cloudflare deploy workflows no longer fail on an npm peer-dependency conflict before ever reaching the actual deploy step. docker-compose-based self-hosters can now turn on local AI/Ollama suggestions or the remote MCP transport by setting a value in .env, without editing docker-compose.yml directly.

<details><summary>Technical detail</summary>

apps/desktop/src-tauri/tauri.conf.json's beforeBuildCommand used ../../frontend, which is only correct if Tauri executes it relative to the config file's own directory (src-tauri/). It does not — it executes relative to wherever `tauri build` was invoked from (apps/desktop, per CONTRIBUTING.md's documented flow and this project's own tauri-action projectPath), where the correct relative path is one level up (../frontend), not two. Confirmed both the bug and the fix by actually running `npx @tauri-apps/cli@2 build` locally: before the fix, the documented beforeBuildCommand path resolved to a nonexistent sibling directory outside the repo (`<repo-root>/frontend` instead of `<repo-root>/apps/frontend`) and failed with a misleading "no package-lock.json" error from npm; after the fix, the frontend build step inside `tauri build` completes and the Rust build proceeds. This had never been caught because no tag was ever pushed to trigger release.yml, and the desktop CI job (ci.yml) only runs `cargo check`, which doesn't exercise beforeBuildCommand at all.
Separately, docker-compose.yml's backend service environment: block passed through DATABASE_URL/SECRET_KEY/CORS_ORIGINS/FIRST_ADMIN_* but not AI_PROVIDER/OLLAMA_MODEL/OLLAMA_BASE_URL or REMOTE_MCP_ENABLED/MCP_ISSUER_URL, even though the root .env.example's own header comment claimed "anything set there can also be passed through" — for those specific settings, that claim was false. Added the missing passthroughs (with the same working defaults as apps/backend/.env.example) to docker-compose.yml, and documented them in the root .env.example with a pointer to docs/install/local-ai-ollama.md's Docker-specific OLLAMA_BASE_URL guidance (`localhost` inside the container is not the host machine). Also pinned cloudflare/wrangler-action's wranglerVersion to 4.120.0 in the three deploy-*.yml workflows added in #310 — the action's own default (observed via a real failed CI run: 4.86.0) has a @cloudflare/workers-types peer-dependency conflict with the version this project's package.json already installs (^5.x).

</details>

**Known limitations:**
- The desktop build fix was verified up through the frontend-embedding step (beforeBuildCommand completing successfully); the full native Rust/Tauri compilation and installer packaging was not run to completion in this environment (no signing certificates, and a full release build takes longer than was practical to wait out here) — CI is the real gate for that, and this fix directly addresses the exact failure a real CI run on main just produced.
- docker-compose.yml still doesn't pass through the RATE_LIMIT_* or DB_POOL_SIZE/DB_MAX_OVERFLOW/LOG_LEVEL/DB_ECHO/SCHEDULER_JOB_STORE settings — deliberately scoped to the ones a self-hoster is actually likely to want to change (AI/Ollama, remote MCP), not a full mirror of every backend setting; the root .env.example says so explicitly and points at apps/backend/.env.example for the rest.

<a id="desktop-production-default-and-continuous-release"></a>

### Added: A desktop installer built by CI (either release channel) now defaults to the hosted production API instead of a local loopback address, and a new automatic "continuous build" channel publishes an always-current desktop build on every push to main.

*2026-08-07* — verification: automated tests: passed

A LensWord Desktop installer downloaded from GitHub now works against the real hosted service out of the box, with no configuration step, instead of only working once a local backend is also running. A new "Continuous Build" release (tag desktop-continuous, marked prerelease) reflects the current tip of main and updates automatically; the existing desktop-v* tagged-release channel is unchanged in behavior beyond also getting this same production default.

<details><summary>Technical detail</summary>

apps/desktop/api-config/src/lib.rs's DEFAULT_API_BASE is now resolved via option_env!("LENSWORD_RELEASE_API_BASE") at compile time, falling back to the existing http://127.0.0.1:8000 literal when unset. Only CI release builds set that variable (.github/workflows/build-desktop-installers.yml, a new reusable workflow extracted from release.yml's original single-file form so release.yml and the new release-continuous.yml share identical packaging/signing logic rather than risking drift between two copies). cargo build/cargo tauri dev never set it, so local development is unaffected — verified by running the existing 25-test suite unchanged, then re-running with LENSWORD_RELEASE_API_BASE set and confirming the one test that hardcodes the loopback literal fails for exactly the expected reason (the compiled constant genuinely changed). The runtime LENSWORD_API_URL env var and api-endpoint config file both still outrank the compiled-in default either way, so a downloaded installer remains fully self-hostable. release-continuous.yml triggers on push to main (path-filtered to apps/desktop and apps/frontend), deletes and recreates a rolling `desktop-continuous` GitHub prerelease each time via `gh release delete` before invoking the shared reusable workflow — chosen specifically to avoid depending on unverified behavior of tauri-action's own handling of re-publishing to an already-existing tag.

</details>

**Known limitations:**
- Not verified end to end against a real deploy — the production API (lensword-api.conectlens.com) this defaults to did not exist as a live service when this was written (see the Cloudflare deployment PR); a downloaded installer using the new default won't actually reach a server until that's deployed.
- release-continuous.yml itself has not run for real (no push to main happened from this session) — the reusable workflow it calls is verified only by inspection and by the fact that release.yml's unchanged packaging/signing steps already work; the new delete-then-recreate rolling-release step is untested against a live GitHub Releases API.

<a id="desktop-linux-appindicator-build-dep"></a>

### Fixed: The Linux desktop installer (AppImage/.deb/.rpm) build no longer fails — it was missing a required system tray dependency.

*2026-08-07* — verification: production observation: observed

Linux users get an actual AppImage/.deb/.rpm from the release/continuous build pipeline again, instead of the build job failing after a full ~5-minute compile with no artifacts produced.

<details><summary>Technical detail</summary>

A real run of the desktop-installer build workflow (build-desktop-installers.yml, ubuntu-latest) panicked during bundling: `Can't detect any appindicator library`. The Rust build itself succeeded (this app uses a system tray — see apps/frontend/src/lib/tray.ts/useTraySync); the panic is inside tauri-cli's bundler, which does its own pkg-config-based lookup for a tray/appindicator library at bundle time, separate from plain compilation — which is why ci.yml's "Desktop shell (Rust, ubuntu-latest)" job (cargo check/test/clippy only, no `tauri build` bundle step) never hit this. Added libayatana-appindicator3-dev to this workflow's apt-get install list, matching Tauri's own documented Linux prerequisites for tray-icon support.

</details>

**Known limitations:**
- Not verified against a real completed CI run of this workflow yet (the fix is a one-line apt-get addition matching Tauri's documented Linux dependency list, not something reproducible in this sandbox, which has no Tauri/GTK toolchain) — verify on the next release-continuous run.

<a id="desktop-fonts-blocked-by-csp"></a>

### Fixed: The desktop app's icons and headings now render correctly. They were invisible/wrong before: the Material Symbols icon font failed to load, so icon ligatures (e.g. "translate") showed as literal words instead of glyphs.

*2026-08-07* — verification: automated tests: passed; artifact build: passed; production observation: observed

Desktop app users see real icons and the intended headings/body font instead of literal icon-name text and a system font fallback. No change for web app users (Cloudflare Pages), who never hit this.

<details><summary>Technical detail</summary>

apps/frontend loaded Montserrat, Poppins, and Material Symbols Outlined from fonts.googleapis.com/fonts.gstatic.com via a <link> in index.html. The web build has no CSP and never showed a problem. The Tauri desktop shell's CSP (apps/desktop/src-tauri/tauri.conf.json: style-src 'self' 'unsafe-inline'; font-src 'self' data:) blocks both origins outright, so in the desktop build the stylesheet link and the font files behind it silently failed to load. Text fell back to a system sans-serif (headings/ body, easy to miss) and Material Symbols' ligature spans fell back to rendering their literal name text (e.g. "translate" — visually obvious, reported by a real screenshot of the register page). Fixed by self-hosting instead of loosening the CSP: apps/frontend/public/fonts now carries Montserrat (single variable-weight file, Latin unicode-range), Poppins (four static weights, Latin), and a glyph-subsetted Material Symbols Outlined file containing only the icon names src/ actually references (see components/ui/Icon.tsx callers) — 257KB static, vs 3.85MB for the full variable-axis font, since the app never toggles Icon's `filled` prop to true anywhere today. @font-face rules added to src/index.css; the Google Fonts <link>/preconnect tags removed from index.html. font-src/style-src 'self' already covers same-origin files, so no CSP change was needed or made — self-hosting fixes both build targets from one source without loosening either one's security policy.

</details>

**Known limitations:**
- Montserrat/Poppins are self-hosted Latin-only (matching the weights already in use); non-Latin UI text (there isn't any in this app's chrome today) would fall back to the `sans-serif` stack rather than these fonts specifically.
- The Material Symbols subset only contains the icon names in use as of this fix. Adding a new `<Icon name="...">` value requires regenerating apps/frontend/public/fonts/material-symbols-outlined.woff2 the same way (fonts.googleapis.com/css2?family=Material+Symbols+Outlined&text=...) or it will silently render as literal text again, same failure mode.
