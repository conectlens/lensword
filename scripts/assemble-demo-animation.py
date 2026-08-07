#!/usr/bin/env python3
"""Assemble captured demo frames into a compact animated WebP.

Reads the numbered PNG frames scripts/capture-demo-media.mjs produced under
docs/media/demo-frames/<scenario>/ and encodes them into a single animated
WebP (GitHub renders animated WebP inline in README.md, and it produces a
noticeably smaller file than an equivalent GIF at the same visual quality —
WebP's inter-frame compression is simply better than GIF's LZW, and this
demo is flat UI, not photographic content, which is exactly where that gap
is largest). A static fallback (the frame with the sharpest, most legible
state — here, the "Correct!" result) is saved alongside it for anywhere an
animation isn't wanted.

Usage:
    pip install pillow
    python scripts/assemble-demo-animation.py
"""
from __future__ import annotations

import pathlib
import subprocess

from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCENARIO_DIR = ROOT / "docs" / "media" / "demo-frames" / "review-session"
OUT_DIR = ROOT / "docs" / "media" / "screenshots"

# (filename, hold duration in ms) — hold the question and result frames
# longer than the mid-transition typed/next frames, so the animation reads
# clearly instead of flickering.
FRAMES = [
    ("01-question.png", 1400),
    ("02-typed.png", 900),
    ("03-result.png", 1400),
    ("04-next.png", 1600),
]

MAX_BYTES = 400_000  # documented budget for this animation


def main() -> None:
    images = []
    durations = []
    for name, duration in FRAMES:
        path = SCENARIO_DIR / name
        if not path.exists():
            raise SystemExit(f"missing frame: {path} — run scripts/capture-demo-media.mjs first")
        images.append(Image.open(path).convert("RGB"))
        durations.append(duration)

    out_path = OUT_DIR / "web-review-session-demo.webp"
    images[0].save(
        out_path,
        "WEBP",
        save_all=True,
        append_images=images[1:],
        duration=durations,
        loop=0,
        quality=80,
        method=6,
    )
    size = out_path.stat().st_size
    print(f"wrote {out_path} ({size:,} bytes, {len(images)} frames)")
    if size > MAX_BYTES:
        raise SystemExit(f"animation exceeds the {MAX_BYTES:,}-byte budget — reduce frame count/quality")

    # Static fallback: the "Correct!" frame is the most self-explanatory
    # single image if the animation can't be shown.
    fallback_path = OUT_DIR / "web-review-session-demo-fallback.webp"
    images[2].save(fallback_path, "WEBP", quality=85, method=6)
    print(f"wrote {fallback_path} ({fallback_path.stat().st_size:,} bytes)")

    provenance = SCENARIO_DIR / "provenance.json"
    if provenance.exists():
        rev = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False
        ).stdout.strip()
        print(f"source frames generated at revision recorded in {provenance} (current HEAD: {rev[:12]})")


if __name__ == "__main__":
    main()
