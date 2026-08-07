#!/usr/bin/env python3
"""Compare a PR's changed files against declared product impact.

Implements #282 TODO 4: path detection is a warning/validation aid, not
absolute truth (a change can be fragment-worthy without touching a
product's sourcePath, e.g. a shared contract change, or vice versa) — so
only one thing here is a hard failure: a PR that touches a registered
product's source and includes *no* changelog fragment at all. Everything
else (a fragment naming a product with no changed files under its path, a
touched backend with no fragment naming its consumer products) is a
warning, matching CONTRIBUTING.md's existing "every observable change gets
a fragment, including internal-only ones" policy — this script is what
makes that policy enforceable instead of just documented.

Usage:
    python scripts/changelog/check_product_impact.py --base origin/development --head HEAD
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
REGISTRY_PATH = ROOT / "docs" / "internal" / "product-registry.json"
CHANGES_DIR = ".changes/"

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None


def changed_files(base: str, head: str, repo_root: pathlib.Path = ROOT) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...{head}"],
        cwd=repo_root, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True,
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


def touched_products(files: list[str], products: list[dict]) -> dict[str, list[str]]:
    """Map product id -> changed files under that product's sourcePath."""
    hits: dict[str, list[str]] = {}
    for p in products:
        prefix = p["sourcePath"].rstrip("/") + "/"
        matched = [f for f in files if f.startswith(prefix) or f == p["sourcePath"]]
        if matched:
            hits[p["id"]] = matched
    return hits


def load_fragment_products(fragment_files: list[str], repo_root: pathlib.Path = ROOT) -> dict[str, list[str]]:
    """Map fragment filename -> declared products, from the fragment's own content."""
    out: dict[str, list[str]] = {}
    for rel in fragment_files:
        path = repo_root / rel
        if not path.exists():
            continue  # deleted in this diff
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            continue  # schema.py reports the parse error; not this script's job
        if isinstance(data, dict) and isinstance(data.get("products"), list):
            out[rel] = data["products"]
    return out


def check(base: str, head: str, registry_path: pathlib.Path = REGISTRY_PATH, repo_root: pathlib.Path = ROOT) -> tuple[list[str], list[str]]:
    """Returns (errors, warnings)."""
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    products = registry["products"]
    product_names = {p["id"]: p["name"] for p in products}

    files = changed_files(base, head, repo_root)
    fragment_files = [f for f in files if f.startswith(CHANGES_DIR) and f.endswith(".yml")]
    hits = touched_products(files, products)

    errors: list[str] = []
    warnings: list[str] = []

    if hits and not fragment_files:
        touched = ", ".join(f"{product_names[pid]} ({pid})" for pid in sorted(hits))
        errors.append(
            f"changed files touch {touched} but this PR adds no changelog "
            f"fragment under .changes/. Every change to a registered product's "
            f"source needs one — for a change with no user-observable effect, "
            f"add a fragment with type: none and a reason (see .changes/README.md)."
        )
        return errors, warnings

    if not fragment_files:
        return errors, warnings  # nothing touched a registered product; nothing to check

    fragment_products = load_fragment_products(fragment_files, repo_root)
    declared: set[str] = set()
    for prods in fragment_products.values():
        declared.update(prods)

    for pid in hits:
        if pid not in declared:
            warnings.append(
                f"{product_names.get(pid, pid)} ({pid}) has changed files "
                f"({', '.join(hits[pid][:3])}{', ...' if len(hits[pid]) > 3 else ''}) "
                f"but no fragment in this PR names it in 'products' — confirm this is "
                f"intentional (e.g. a test-only or non-observable change already covered "
                f"by another fragment)."
            )

    for pid in declared:
        if pid in product_names and pid not in hits:
            warnings.append(
                f"a fragment names {product_names[pid]} ({pid}) but no changed file falls "
                f"under its sourcePath — path detection can miss shared-contract changes, "
                f"so this is informational, not necessarily wrong."
            )

    if "backend" in hits and declared and not (declared - {"backend"}):
        consumers = ", ".join(p["name"] for p in products if "backend" in p.get("runtimeDependencies", []) if p["id"] not in declared)
        if consumers:
            warnings.append(
                f"backend changed and every declared fragment names only 'backend', which "
                f"is not independently released — confirm whether {consumers} are actually "
                f"affected and should be listed too."
            )

    return errors, warnings


def main(argv: list[str]) -> int:
    if yaml is None:
        print("PyYAML is required: pip install pyyaml", file=sys.stderr)
        return 2

    base = "origin/development"
    head = "HEAD"
    args = list(argv)
    if "--base" in args:
        i = args.index("--base")
        base = args[i + 1]
        del args[i : i + 2]
    if "--head" in args:
        i = args.index("--head")
        head = args[i + 1]
        del args[i : i + 2]

    errors, warnings = check(base, head)

    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)
    if errors:
        print("", file=sys.stderr)
        for e in errors:
            print(f"error: {e}", file=sys.stderr)
        return 1

    print(f"product-impact check passed ({len(warnings)} warning(s)).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
