# LensWord brand assets

LensWord's mark reads as a magnifying glass ("Lens") focused on a line of
text ("Word") — a lens finding and holding a word in place, the same idea
behind spaced repetition and forced recall. It is original artwork, built
from primitive shapes (a ring, a line, two rounded bars) rather than derived
from any third-party icon or trademark.

## Canonical source

Every raster asset in this repository is generated from the vector sources
under [`brand/logo/svg/`](../brand/logo/svg/) and
[`brand/og/lensword-social-preview.svg`](../brand/og/lensword-social-preview.svg).
**Never hand-edit a PNG, WebP, ICO, or ICNS file directly** — edit the SVG
and re-run the regeneration script:

```bash
pip install svglib reportlab rlPyCairo pycairo pillow numpy
python scripts/generate-brand-assets.py
```

This rewrites every generated file under `brand/logo/png/`,
`brand/logo/webp/`, `brand/og/`, `apps/frontend/public/` (favicons + Open
Graph image), `apps/browser/icons/` (extension toolbar/store icons), and
`apps/desktop/src-tauri/icons/` (desktop app icon set) from the SVG sources.

## Color

| Token | Value | Use |
|---|---|---|
| `accent` | `#ffde59` | Primary brand yellow — the mark's color on dark backgrounds, matches `tailwind.config.js`'s `accent.DEFAULT` |
| `accent-dark` | `#f5c400` | Hover/pressed state, matches `tailwind.config.js`'s `accent.dark` |
| `ink` | `#121212` | Near-black — the mark's color on light backgrounds and the icon chip background, matches `tailwind.config.js`'s `ink` |
| white | `#ffffff` | The mark's color on dark, colorful, or photographic backgrounds where neither accent nor ink has enough contrast |

These are the app's existing Tailwind color tokens (`apps/frontend/tailwind.config.js`) — the brand system reuses them rather than introducing a second palette.

## Variants

| File | Description | When to use |
|---|---|---|
| `lensword-mark-ink.svg` | Icon-only mark, ink (`#121212`), transparent background | On light backgrounds (GitHub README, light-mode docs) |
| `lensword-mark-white.svg` | Icon-only mark, white, transparent background | On dark backgrounds (dark-mode docs, dark UI chrome) |
| `lensword-mark-color.svg` | Icon-only mark, accent yellow, transparent background | On dark or neutral backgrounds where the mark should read as brand-colored, not neutral |
| `lensword-icon-square.svg` | Accent mark on an `#121212` rounded-square chip | App icons, favicons, social/store icons — anything that needs to be self-contained and legible over any surrounding page background |
| `lensword-lockup-ink.svg` / `-white.svg` | Icon + "LensWord" wordmark, horizontal | README header, docs navbar, anywhere the name should appear next to the mark |
| `lensword-social-preview.svg` | 1200×630 Open Graph / social card | Link previews (Slack, X/Twitter, Discord, etc.) |

## Sizes generated

Icon-only and chip variants: 16, 32, 48, 64, 128, 256, 512px (plus 1024px
for the chip, used as the desktop app's macOS `.icns` source). Lockups: 1x
and 2x raster exports at their native 340×100 aspect ratio. All as both PNG
(broad compatibility) and WebP (smaller, used wherever the consumer
supports it — README embeds, the frontend favicon/OG image, and the brand
asset directory itself).

## Safe spacing and minimum size

Keep clear space around the mark equal to at least the width of one ring
stroke (10% of the mark's bounding box) on every side. Below 16px the
internal word-bars stop being individually legible and the mark reads as a
silhouette — this is expected and acceptable at favicon size; do not use
the mark below 16px.

## Where it's wired in today

- `README.md` — lockup at the top of the file, theme-aware via a `<picture>` element (white lockup in GitHub dark mode, ink lockup otherwise).
- `apps/frontend/index.html` — favicon family (`favicon.svg`, `favicon-16x16.png`, `favicon-32x32.png`, `apple-touch-icon.png`) and Open Graph metadata (`og-image.png`).
- `apps/browser/manifest.json` — extension toolbar/management icons (16/32/48/128px). Chrome's MV3 `icons`/`default_icon` fields require PNG, not SVG, so `icon.svg` alone (the pre-existing, unbranded placeholder) was never actually wired into the extension UI; it now matches the canonical mark and the manifest references the generated PNGs.
- `apps/desktop/src-tauri/icons/` — the full Tauri-generated icon set (macOS `.icns`, Windows `.ico` and Store tile PNGs, Linux PNGs), replacing the unbranded default Tauri template icons. Safe to replace because no desktop release, tag, or signed build has ever been published (see [`docs/internal/repo-audit.md`](internal/repo-audit.md)) — nothing signed or store-listed depended on the old art.
- VitePress navbar, home hero, and favicon: not yet applicable — VitePress doesn't exist in this repository yet (tracked by #272). When it's scaffolded, it should reuse `brand/logo/svg/lensword-icon-square.svg` and the lockup variants rather than introducing new artwork.

## Audit of prior assets

No canonical LensWord logo existed before this change. `apps/browser/icon.svg`
was a generic blue placeholder (unrelated color, and unreferenced by the
extension's manifest — Chrome MV3 doesn't accept SVG for `icons`, so it was
never actually displayed anywhere). `apps/desktop/src-tauri/icons/*` was the
default icon set generated by Tauri's `tauri icon` scaffolding command, never
replaced with real artwork. `apps/frontend` had no favicon or `<link
rel="icon">` at all. All of these are now replaced by the canonical system
above; nothing was preserved because nothing pre-existing was LensWord
branded.
