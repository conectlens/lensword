#!/usr/bin/env python3
"""Syntactically validate fenced json/yaml/toml code blocks in Markdown docs.

Implements #283 TODO 3's "validate JSON/YAML/TOML/config examples
syntactically." Doesn't execute anything — a syntactically valid example can
still be behaviorally wrong, which is out of scope here (see the QA report
for what's covered vs. deferred). Catches the class of error where an
example was hand-edited and a bracket/quote/indent broke it silently, since
docs prose isn't type-checked or run anywhere else.

Usage:
    python scripts/docs-qa/check_code_blocks.py
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

import yaml

try:
    import tomllib  # stdlib on Python 3.11+; CI pins 3.12 (see CONTRIBUTING.md)
except ModuleNotFoundError:
    tomllib = None

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
DOC_ROOTS = [ROOT / "docs", ROOT / "README.md", ROOT / "CONTRIBUTING.md"]
EXCLUDE_DIR_PARTS = {"node_modules", "dist", "cache"}

FENCE_RE = re.compile(r"^```(json|yaml|yml|toml)\s*\n(.*?)^```\s*$", re.MULTILINE | re.DOTALL)


def iter_markdown_files() -> list[pathlib.Path]:
    files: list[pathlib.Path] = []
    for root in DOC_ROOTS:
        if root.is_file():
            files.append(root)
        elif root.is_dir():
            files.extend(
                sorted(
                    f for f in root.rglob("*.md")
                    if not EXCLUDE_DIR_PARTS & set(f.relative_to(root).parts[:-1])
                )
            )
    return files


def check_file(path: pathlib.Path) -> tuple[list[str], int]:
    """Returns (errors, toml_blocks_skipped)."""
    errors = []
    skipped_toml = 0
    text = path.read_text(encoding="utf-8")
    try:
        rel = path.relative_to(ROOT)
    except ValueError:
        rel = path
    for match in FENCE_RE.finditer(text):
        lang = match.group(1)
        body = match.group(2)
        line_no = text.count("\n", 0, match.start()) + 1
        try:
            if lang == "json":
                json.loads(body)
            elif lang in ("yaml", "yml"):
                yaml.safe_load(body)
            elif lang == "toml":
                if tomllib is None:
                    skipped_toml += 1
                    continue
                tomllib.loads(body)
        except json.JSONDecodeError as exc:
            errors.append(f"{rel}:{line_no}: invalid {lang} in fenced code block — {exc}")
        except yaml.YAMLError as exc:
            errors.append(f"{rel}:{line_no}: invalid {lang} in fenced code block — {exc}")
        except Exception as exc:  # tomllib.TOMLDecodeError, only reachable when tomllib is not None
            errors.append(f"{rel}:{line_no}: invalid {lang} in fenced code block — {exc}")
    return errors, skipped_toml


def main(argv: list[str]) -> int:
    errors: list[str] = []
    checked = 0
    skipped_toml = 0
    for path in iter_markdown_files():
        checked += 1
        file_errors, file_skipped = check_file(path)
        errors.extend(file_errors)
        skipped_toml += file_skipped

    if skipped_toml:
        print(f"note: {skipped_toml} toml block(s) not validated — tomllib requires Python 3.11+ (this run is on {sys.version.split()[0]})", file=sys.stderr)

    if errors:
        print(f"{len(errors)} problem(s) found across {checked} file(s):\n", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    print(f"code blocks valid: {checked} Markdown file(s) checked.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
