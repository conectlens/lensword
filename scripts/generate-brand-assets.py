#!/usr/bin/env python3
"""Regenerate LensWord raster brand assets from the canonical vector sources
under brand/logo/svg/ and brand/og/.

The canonical logo is vector (SVG). Every PNG, WebP, ICO, and ICNS file in
this repository is derived from those SVGs by this script — never hand-edit
a raster brand asset directly; edit the SVG and re-run this script instead.

Usage:
    pip install svglib reportlab rlPyCairo pycairo pillow numpy
    python scripts/generate-brand-assets.py

Deterministic: given the same SVG sources and the same library versions,
this script produces byte-identical output.
"""
from __future__ import annotations

import pathlib
import sys

import numpy as np
from PIL import Image
from reportlab.graphics import renderPM
from svglib.svglib import svg2rlg

ROOT = pathlib.Path(__file__).resolve().parent.parent
SVG = ROOT / "brand" / "logo" / "svg"
OG_SVG = ROOT / "brand" / "og" / "lensword-social-preview.svg"
LOGO_PNG = ROOT / "brand" / "logo" / "png"
LOGO_WEBP = ROOT / "brand" / "logo" / "webp"
OG_OUT = ROOT / "brand" / "og"
FRONTEND_PUBLIC = ROOT / "apps" / "frontend" / "public"
BROWSER_ICONS = ROOT / "apps" / "browser" / "icons"
DESKTOP_ICONS = ROOT / "apps" / "desktop" / "src-tauri" / "icons"


def render_svg(svg_path: pathlib.Path, target_w: int, target_h: int) -> Image.Image:
    """Render an SVG to an RGBA PIL image at an exact pixel size.

    Renders twice (white and black backgrounds) and reconstructs true alpha
    from the difference, since the underlying renderPM/rlPyCairo backend
    does not expose a transparent-background render mode directly. Flat
    vector fills make this reconstruction exact.
    """
    drawing = svg2rlg(str(svg_path))
    sx = target_w / drawing.width
    sy = target_h / drawing.height
    drawing.width = target_w
    drawing.height = target_h
    drawing.scale(sx, sy)

    white_bytes = _draw_to_array(drawing, bg=0xFFFFFF)
    black_bytes = _draw_to_array(drawing, bg=0x000000)

    alpha = np.clip(255.0 - (white_bytes - black_bytes).mean(axis=2), 0, 255)
    safe_alpha = np.clip(alpha[..., None] / 255.0, 1e-6, None)
    color = np.clip(np.where(alpha[..., None] > 0.5, black_bytes / safe_alpha, 0), 0, 255)
    out = np.dstack([color, alpha]).astype(np.uint8)
    img = Image.fromarray(out, "RGBA")
    if img.size != (target_w, target_h):
        img = img.resize((target_w, target_h), Image.LANCZOS)
    return img


def _draw_to_array(drawing, bg: int) -> np.ndarray:
    tmp = ROOT / f".__brand_render_{bg:06x}.png"
    renderPM.drawToFile(drawing, str(tmp), fmt="PNG", bg=bg, dpi=96)
    arr = np.asarray(Image.open(tmp).convert("RGB"), dtype=np.float64)
    tmp.unlink()
    return arr


def save(img: Image.Image, png_path: pathlib.Path | None, webp_path: pathlib.Path | None = None) -> None:
    if png_path:
        png_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(png_path, "PNG", optimize=True)
    if webp_path:
        webp_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(webp_path, "WEBP", lossless=True, quality=100, method=6)


def save_ico(img_256: Image.Image, ico_path: pathlib.Path, sizes: list[int]) -> None:
    ico_path.parent.mkdir(parents=True, exist_ok=True)
    img_256.save(ico_path, format="ICO", sizes=[(s, s) for s in sizes])


def save_icns(img_1024: Image.Image, icns_path: pathlib.Path) -> None:
    icns_path.parent.mkdir(parents=True, exist_ok=True)
    img_1024.save(icns_path, format="ICNS")


def main() -> None:
    mark_variants = {
        "lensword-mark-ink": SVG / "lensword-mark-ink.svg",
        "lensword-mark-white": SVG / "lensword-mark-white.svg",
        "lensword-mark-color": SVG / "lensword-mark-color.svg",
    }
    mark_sizes = [16, 32, 48, 64, 128, 256, 512]
    for name, path in mark_variants.items():
        for size in mark_sizes:
            img = render_svg(path, size, size)
            save(img, LOGO_PNG / f"{name}-{size}.png", LOGO_WEBP / f"{name}-{size}.webp")
    print(f"mark variants: {len(mark_variants)} x {len(mark_sizes)} sizes")

    icon_square_sizes = [16, 32, 48, 64, 128, 256, 512, 1024]
    icon_square_svg = SVG / "lensword-icon-square.svg"
    icon_renders: dict[int, Image.Image] = {}
    for size in icon_square_sizes:
        img = render_svg(icon_square_svg, size, size)
        icon_renders[size] = img
        save(img, LOGO_PNG / f"lensword-icon-square-{size}.png", LOGO_WEBP / f"lensword-icon-square-{size}.webp")
    print(f"icon-square: {len(icon_square_sizes)} sizes")

    for name, path in {
        "lensword-lockup-ink": SVG / "lensword-lockup-ink.svg",
        "lensword-lockup-white": SVG / "lensword-lockup-white.svg",
    }.items():
        for scale, suffix in [(1, ""), (2, "@2x")]:
            img = render_svg(path, 340 * scale, 100 * scale)
            save(img, LOGO_PNG / f"{name}{suffix}.png", LOGO_WEBP / f"{name}{suffix}.webp")
    print("lockups: 2 variants x 2 scales")

    og_img = render_svg(OG_SVG, 1200, 630)
    save(og_img, OG_OUT / "lensword-social-preview.png", OG_OUT / "lensword-social-preview.webp")
    print("open graph social preview: 1200x630")

    # apps/frontend/public — favicon family + Open Graph image
    save(icon_renders[16], FRONTEND_PUBLIC / "favicon-16x16.png")
    save(icon_renders[32], FRONTEND_PUBLIC / "favicon-32x32.png")
    apple_touch = render_svg(icon_square_svg, 180, 180)
    save(apple_touch, FRONTEND_PUBLIC / "apple-touch-icon.png")
    save_ico(icon_renders[256], FRONTEND_PUBLIC / "favicon.ico", [16, 32, 48])
    (FRONTEND_PUBLIC / "favicon.svg").write_text(icon_square_svg.read_text(encoding="utf-8"), encoding="utf-8")
    save(og_img, FRONTEND_PUBLIC / "og-image.png")
    print("frontend public/: favicon family + og-image.png")

    # apps/browser — MV3 toolbar/store icons (SVG icons are not valid MV3 action icons)
    for size in (16, 32, 48, 128):
        save(icon_renders[size], BROWSER_ICONS / f"icon{size}.png")
    (ROOT / "apps" / "browser" / "icon.svg").write_text(icon_square_svg.read_text(encoding="utf-8"), encoding="utf-8")
    print("browser icons/: 16/32/48/128")

    # apps/desktop/src-tauri/icons — replace the unbranded Tauri-default set.
    # No release/tag has ever been published (see docs/internal/repo-audit.md),
    # so nothing signed or store-listed depends on the old placeholder art.
    save(icon_renders[32], DESKTOP_ICONS / "32x32.png")
    save(icon_renders[64], DESKTOP_ICONS / "64x64.png")
    save(icon_renders[128], DESKTOP_ICONS / "128x128.png")
    save(icon_renders[256], DESKTOP_ICONS / "128x128@2x.png")
    save(icon_renders[512], DESKTOP_ICONS / "icon.png")
    save_ico(icon_renders[256], DESKTOP_ICONS / "icon.ico", [16, 24, 32, 48, 64, 128, 256])
    save_icns(icon_renders[1024], DESKTOP_ICONS / "icon.icns")
    windows_tile_sizes = {
        "Square30x30Logo.png": 30,
        "Square44x44Logo.png": 44,
        "Square71x71Logo.png": 71,
        "Square89x89Logo.png": 89,
        "Square107x107Logo.png": 107,
        "Square142x142Logo.png": 142,
        "Square150x150Logo.png": 150,
        "Square284x284Logo.png": 284,
        "Square310x310Logo.png": 310,
        "StoreLogo.png": 50,
    }
    for filename, size in windows_tile_sizes.items():
        img = render_svg(icon_square_svg, size, size)
        save(img, DESKTOP_ICONS / filename)
    print(f"desktop icons/: core set + {len(windows_tile_sizes)} Windows tile sizes")

    print("done.")


if __name__ == "__main__":
    sys.exit(main())
