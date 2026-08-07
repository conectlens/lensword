#!/usr/bin/env python3
"""Validate docs/internal/product-registry.json's structural integrity.

Fragment schema validation (schema.py) trusts this file's product IDs are
real; this script is what makes that trust warranted. Run it before
schema.py in CI so a broken registry fails with a registry-shaped error
instead of a confusing cascade of "unknown product id" fragment errors.

Usage:
    python scripts/changelog/validate_registry.py
    python scripts/changelog/validate_registry.py --registry path/to/registry.json
"""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
DEFAULT_REGISTRY = ROOT / "docs" / "internal" / "product-registry.json"
DEFAULT_CONFIG_MTS = ROOT / "docs" / ".vitepress" / "config.mts"

REQUIRED_PRODUCT_FIELDS = (
    "id", "name", "kind", "sourcePath", "purpose", "runtimeDependencies",
    "install", "platforms", "versionSource", "currentVersion", "status",
    "ciCoverage", "releaseChannel", "changelogRoute", "versionTagPrefix",
    "releaseStatus", "artifactTypes",
)
VALID_KINDS = {"public-product", "implementation-dependency"}


def validate(registry_path: pathlib.Path = DEFAULT_REGISTRY, config_path: pathlib.Path = DEFAULT_CONFIG_MTS) -> list[str]:
    errors: list[str] = []

    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"{registry_path.name}: cannot read/parse registry — {exc}"]

    products = registry.get("products")
    if not isinstance(products, list) or not products:
        return [f"{registry_path.name}: 'products' must be a non-empty list"]

    ids: list[str] = []
    names: list[str] = []
    routes: dict[str, list[str]] = {}

    for i, p in enumerate(products):
        if not isinstance(p, dict):
            errors.append(f"products[{i}]: entry must be a mapping")
            continue
        label = p.get("id", f"<index {i}>")
        missing = [f for f in REQUIRED_PRODUCT_FIELDS if f not in p]
        if missing:
            errors.append(f"product {label!r}: missing required field(s) {missing}")
            continue

        ids.append(p["id"])
        names.append(p["name"])

        if p["kind"] not in VALID_KINDS:
            errors.append(f"product {label!r}: kind {p['kind']!r} must be one of {sorted(VALID_KINDS)}")

        source = ROOT / p["sourcePath"]
        if not source.exists():
            errors.append(f"product {label!r}: sourcePath {p['sourcePath']!r} does not exist on disk")

        if p["kind"] == "public-product":
            if not p.get("changelogRoute"):
                errors.append(f"product {label!r}: public-product requires a non-empty changelogRoute")
            else:
                routes.setdefault(p["changelogRoute"], []).append(p["id"])
            if not p.get("versionTagPrefix"):
                errors.append(f"product {label!r}: public-product requires a non-empty versionTagPrefix")

        deps = p.get("runtimeDependencies")
        if not isinstance(deps, list):
            errors.append(f"product {label!r}: runtimeDependencies must be a list")

    dup_ids = sorted({i for i in ids if ids.count(i) > 1})
    if dup_ids:
        errors.append(f"duplicate product id(s): {dup_ids}")
    dup_names = sorted({n for n in names if names.count(n) > 1})
    if dup_names:
        errors.append(f"duplicate product name(s): {dup_names}")

    # A route may legitimately serve more than one product (mcp-server and
    # local-cli intentionally share /reference/changelog/mcp) — generate.py's
    # render_product_page relies on that, so it's not an error on its own.
    # What *is* an error: registering a route that no page in config.mts
    # navigation actually links to, since nothing would ever surface it.
    try:
        config_label = str(config_path.relative_to(ROOT))
    except ValueError:
        config_label = str(config_path)
    if config_path.exists():
        config_text = config_path.read_text(encoding="utf-8")
        for route in routes:
            if route not in config_text:
                errors.append(
                    f"changelogRoute {route!r} (product(s) {routes[route]}) is not "
                    f"referenced anywhere in {config_label} navigation"
                )
    else:
        errors.append(f"{config_label} not found — cannot verify route/nav consistency")

    ids_set = set(ids)
    for uc in registry.get("useCases", []):
        owner = uc.get("ownerProduct")
        if owner is not None and owner not in ids_set:
            errors.append(f"use case {uc.get('id', '<unknown>')!r}: ownerProduct {owner!r} is not a registered product id")

    return errors


def main(argv: list[str]) -> int:
    registry_path = DEFAULT_REGISTRY
    config_path = DEFAULT_CONFIG_MTS
    args = list(argv)
    if "--registry" in args:
        i = args.index("--registry")
        registry_path = pathlib.Path(args[i + 1])
        del args[i : i + 2]
    if "--config" in args:
        i = args.index("--config")
        config_path = pathlib.Path(args[i + 1])
        del args[i : i + 2]

    errors = validate(registry_path, config_path)
    if errors:
        print(f"{len(errors)} problem(s) found in {registry_path}:\n", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    try:
        label = registry_path.relative_to(ROOT)
    except ValueError:
        label = registry_path
    print(f"{label}: valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
