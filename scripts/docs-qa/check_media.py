#!/usr/bin/env python3
"""Enforce file-size budgets and scan for accidental secrets/paths in docs media.

Implements the automatable slice of #283 TODO 5 (media quality and
privacy). What this does NOT do, and why: it does not OCR or otherwise
inspect screenshot *pixel content* for leaked tokens/paths/emails — that
needs real image-understanding tooling this environment doesn't have, and
is why every screenshot in this repo was manually reviewed for exactly that
before being committed (see the two incidents recorded in this session:
both caught during manual review, before anything was used or committed —
not by an automated scan). This script covers what regex-over-text-content
*can* catch: file-size budgets, and secret-shaped strings or real local
filesystem paths in the sidecar JSON/text files that accompany the media
(e.g. provenance.json), which a screenshot-content scan wouldn't touch
either.

Usage:
    python scripts/docs-qa/check_media.py
"""
from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
MEDIA_DIR = ROOT / "docs" / "media"


def _label(path: pathlib.Path) -> pathlib.Path | str:
    try:
        return path.relative_to(ROOT)
    except ValueError:
        return str(path)

# Budgets are deliberately generous relative to what's actually committed
# (see the QA report for real sizes) — this catches a genuinely oversized
# capture (e.g. an accidental uncompressed PNG export), not normal variance.
SIZE_BUDGETS_BYTES = {
    ".webp": 1_500_000,
    ".png": 1_500_000,
    ".gif": 4_000_000,
    ".jpg": 1_500_000,
    ".jpeg": 1_500_000,
}

SECRET_PATTERNS = [
    ("AWS access key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("GitHub token", re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}")),
    ("Slack token", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")),
    ("OpenAI-style API key", re.compile(r"sk-[A-Za-z0-9]{20,}")),
    ("Private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    (
        "real local Windows user path",
        re.compile(r"C:\\Users\\(?!Public\\|demo|example)[A-Za-z0-9_]+\\"),
    ),
]

# Fixture data is expected to look credential-shaped (see provenance.json) —
# only flag it if it *isn't* pointed at an obviously fake domain/account.
FIXTURE_EMAIL_ALLOWLIST = re.compile(r"@example\.(com|org|net)$", re.IGNORECASE)
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def check_file_sizes(media_dir: pathlib.Path) -> list[str]:
    errors = []
    if not media_dir.exists():
        return errors
    for path in media_dir.rglob("*"):
        if not path.is_file():
            continue
        budget = SIZE_BUDGETS_BYTES.get(path.suffix.lower())
        if budget is None:
            continue
        size = path.stat().st_size
        if size > budget:
            errors.append(
                f"{_label(path)}: {size:,} bytes exceeds the "
                f"{budget:,}-byte budget for {path.suffix} files"
            )
    return errors


def check_secrets_and_paths(media_dir: pathlib.Path) -> list[str]:
    errors = []
    if not media_dir.exists():
        return errors
    text_suffixes = {".json", ".txt", ".md", ".csv"}
    for path in media_dir.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in text_suffixes:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        rel = _label(path)
        for label, pattern in SECRET_PATTERNS:
            if pattern.search(text):
                errors.append(f"{rel}: looks like it contains a {label} — verify and remove before committing")
        for email in EMAIL_RE.findall(text):
            if not FIXTURE_EMAIL_ALLOWLIST.search(email):
                errors.append(f"{rel}: contains an email address not on an allowlisted fixture domain ({email!r}) — confirm this isn't a real address")
    return errors


def main(argv: list[str]) -> int:
    errors = check_file_sizes(MEDIA_DIR) + check_secrets_and_paths(MEDIA_DIR)

    if errors:
        print(f"{len(errors)} problem(s) found:\n", file=sys.stderr)
        for e in errors:
            # Avoid logging potential sensitive payloads (for example, specific
            # matched addresses) while still reporting actionable context.
            safe_error = re.sub(r"\s*\([^)]*\)\s*", " (redacted) ", e).strip()
            print(f"  - {safe_error}", file=sys.stderr)
        return 1

    count = sum(1 for p in MEDIA_DIR.rglob("*") if p.is_file()) if MEDIA_DIR.exists() else 0
    print(f"media checks passed: {count} file(s) under docs/media checked for size budgets and sidecar-text secrets.")
    print("note: screenshot pixel content is not scanned automatically — see this script's docstring.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
