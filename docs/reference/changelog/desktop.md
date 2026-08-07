---
title: Desktop Application Changelog
description: User-facing changes to Desktop Application, with verification evidence per entry.
---

# Desktop Application changelog

Status — Desktop Application: **unreleased**.

Every entry states exactly what was verified — a passing automated test does not imply a platform was manually checked, and a manual check on one OS does not imply another. See [Verification levels](/reference/trust/verification-levels) for what each status means.

### Documentation: LensWord has a real documentation site (docs/, built with VitePress), organized around Diátaxis (Setup tutorial, Install how-to guides, Learn explanation, Reference material) — replacing a flat, uncurated docs/ folder.

*2026-08-07* — verification: automated tests: passed; artifact build: passed; manual checks — windows: passed; production observation: not_applicable

Every surface (Web, Desktop, Browser Extension, MCP Server, Local CLI) now has a real, verified guide instead of scattered or missing documentation — including install steps, security/privacy behavior, and an honest account of what has and hasn't been tested for that surface.

<details><summary>Technical detail</summary>

docs/.vitepress/config.mts defines the site; every existing doc was moved (not deleted) into the new structure, apps/browser/README.md and apps/mcp/README.md are pulled in via VitePress's markdown @include feature so they can't drift from source, and a SurfaceChooser Vue component reads docs/internal/product-registry.json directly so the surface-comparison table can't drift from the audit that backs it.

</details>

**Known limitations:**
- GitHub Pages deployment for the site is wired up but not yet enabled (repository Settings -> Pages -> Source is still unset) — the site builds successfully in CI but has no public URL yet.

References: [#272](https://github.com/conectlens/lensword/issues/272), [PR #295](https://github.com/conectlens/lensword/pull/295)

### Added: LensWord has a canonical logo and icon set for the first time — a favicon in the web app, real desktop app icons, and a real browser extension icon, replacing generic/unbranded placeholders.

*2026-08-07* — verification: automated tests: passed; artifact build: passed

The web app now has a real favicon and social-preview image, the desktop app has a real icon instead of Tauri's default, and the browser extension shows a real icon in the toolbar and extensions page instead of nothing.

<details><summary>Technical detail</summary>

Original SVG mark (lens + word-line) in brand/logo/svg/, with a reproducible generation script (scripts/generate-brand-assets.py) that derives every PNG/WebP/ICO/ICNS raster asset from the vector sources. Wired into apps/frontend's favicon/Open Graph tags, apps/desktop's Tauri icon set (replacing the default Tauri-generated placeholder), and apps/browser's manifest icons/action.default_icon (previously unset — the extension had no working icon at all, since MV3 doesn't accept SVG for that field).

</details>

**Known limitations:**
- Desktop icon change was not visually re-verified on a packaged installer (none has ever been built) — confirmed only that the icon files exist at the correct paths/sizes referenced by tauri.conf.json.

References: [#270](https://github.com/conectlens/lensword/issues/270), [PR #291](https://github.com/conectlens/lensword/pull/291)
