# OCR golden-image fixtures (issue #222)

Four images covering the categories issue #84's own verification bar named
(subtitles, scans, low contrast, multilingual), checked in rather than
generated at test time so what a golden-image test asserts against is
exactly what a reviewer can open and look at.

Regenerate with [ImageMagick](https://imagemagick.org/) if a fixture ever
needs to change — the exact commands used, run from this directory:

```sh
ARIAL_BOLD="/System/Library/Fonts/Supplemental/Arial Bold.ttf"
TIMES="/System/Library/Fonts/Supplemental/Times New Roman.ttf"
ARIAL="/System/Library/Fonts/Supplemental/Arial.ttf"
JP_FONT="/System/Library/Fonts/ヒラギノ角ゴシック W4.ttc"

# Subtitle: white bold text with a black stroke over a dark gradient,
# the way a video's burned-in subtitles look.
magick -size 640x360 gradient:'#334455'-'#112233' \
  -gravity South -font "$ARIAL_BOLD" -pointsize 36 \
  -fill white -stroke black -strokewidth 2 \
  -annotate +0+40 "STAY WHERE YOU ARE" \
  subtitle.png

# Scan: black serif text, slightly rotated, blurred and noised to
# simulate a photographed or scanned page rather than a clean screenshot.
magick -size 640x200 xc:white -gravity Center -font "$TIMES" -pointsize 32 -fill black \
  -annotate +0+0 "The quick brown fox jumps over the lazy dog" \
  -rotate 1.5 -blur 0x0.6 +noise Gaussian -attenuate 0.15 \
  scan.png

# Low contrast: light gray text on a near-white background.
magick -size 640x120 xc:'#f5f5f5' -gravity Center -font "$ARIAL" -pointsize 30 -fill '#aaaaaa' \
  -annotate +0+0 "Please review this document carefully" \
  low_contrast.png

# Multilingual: Japanese text, to exercise a script the recognition
# model is not trained on. See the corresponding test's comment in
# ocr_capture.rs for what this fixture actually verifies (fails closed,
# not "gets Japanese right").
magick -size 640x160 xc:white -gravity Center -font "$JP_FONT" -pointsize 40 -fill black \
  -annotate +0+0 "こんにちは世界" \
  multilingual.png
```

Font paths are macOS system fonts, used only as a one-time generation
tool — the resulting PNGs are static binary fixtures with no dependency
on the fonts (or ImageMagick) at test time.
