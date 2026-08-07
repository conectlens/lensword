---
title: Desktop Application Changelog
description: User-facing changes to Desktop Application, with verification evidence per entry.
---

# Desktop Application changelog

Status — Desktop Application: **unreleased**.

Every entry states exactly what was verified — a passing automated test does not imply a platform was manually checked, and a manual check on one OS does not imply another. See [Verification levels](/reference/trust/verification-levels) for what each status means.

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
