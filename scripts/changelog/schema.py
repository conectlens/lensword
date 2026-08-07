#!/usr/bin/env python3
"""Validate LensWord changelog fragments against the schema in .changes/README.md.

Hand-rolled rather than a jsonschema dependency, matching this repository's
existing convention (see apps/backend/app/application/mcp/contracts.py's
validate_payload) — fails closed on unknown fields and malformed values,
and reports every problem found rather than stopping at the first one.

Usage:
    python scripts/changelog/schema.py .changes/*.yml
    python scripts/changelog/schema.py --registry docs/internal/product-registry.json .changes/*.yml

Exit code 0 if every fragment is valid, 1 otherwise.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
DEFAULT_REGISTRY = ROOT / "docs" / "internal" / "product-registry.json"

CHANGE_TYPES = {"added", "changed", "fixed", "security", "deprecated", "removed", "performance", "documentation"}
TEST_STATUSES = {"passed", "failed", "not_run", "unavailable"}
PLATFORM_STATUSES = {"passed", "failed", "not_run", "not_applicable"}
OBSERVATION_STATUSES = {"observed", "not_observed", "not_applicable"}
RELEASE_STATUSES = {"unreleased", "released"}
ID_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

REQUIRED_TOP_LEVEL = (
    "id", "products", "type", "summary", "user_impact", "release_status",
    "breaking", "migration", "known_limitations", "compatibility",
    "verification", "security_impact", "documentation_required", "date", "references",
)
OPTIONAL_TOP_LEVEL = ("technical_summary",)
ALL_TOP_LEVEL = set(REQUIRED_TOP_LEVEL) | set(OPTIONAL_TOP_LEVEL)


def load_product_ids(registry_path: pathlib.Path) -> set[str]:
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    return {p["id"] for p in registry["products"]}


def validate_fragment(path: pathlib.Path, product_ids: set[str]) -> list[str]:
    errors: list[str] = []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        return [f"{path.name}: invalid YAML — {exc}"]

    if not isinstance(data, dict):
        return [f"{path.name}: fragment must be a YAML mapping"]

    def err(msg: str) -> None:
        errors.append(f"{path.name}: {msg}")

    unknown = set(data) - ALL_TOP_LEVEL
    if unknown:
        err(f"unknown field(s): {sorted(unknown)}")
    missing = [f for f in REQUIRED_TOP_LEVEL if f not in data]
    if missing:
        err(f"missing required field(s): {missing}")
        return errors  # further checks assume presence

    stem = path.stem
    if data["id"] != stem:
        err(f"id {data['id']!r} does not match filename {stem!r}")
    if not ID_RE.match(data["id"]):
        err(f"id {data['id']!r} must be kebab-case (lowercase, digits, hyphens)")

    if not isinstance(data["products"], list) or not data["products"]:
        err("products must be a non-empty list")
    else:
        unknown_products = [p for p in data["products"] if p not in product_ids]
        if unknown_products:
            err(f"unknown product id(s) {unknown_products} — not in {sorted(product_ids)}")

    if data["type"] not in CHANGE_TYPES:
        err(f"type {data['type']!r} must be one of {sorted(CHANGE_TYPES)}")

    if not isinstance(data["summary"], str) or not data["summary"].strip():
        err("summary must be a non-empty string")

    if not isinstance(data["user_impact"], str) or not data["user_impact"].strip():
        err("user_impact must be a non-empty string")

    if data["release_status"] not in RELEASE_STATUSES:
        err(f"release_status {data['release_status']!r} must be one of {sorted(RELEASE_STATUSES)}")

    if not isinstance(data["breaking"], bool):
        err("breaking must be a boolean")
    if data["breaking"] and (not data.get("migration") or data["migration"] == "none"):
        err("breaking: true requires explicit migration instructions, not 'none'")

    if not isinstance(data["known_limitations"], list):
        err("known_limitations must be a list")

    compat = data["compatibility"]
    if not isinstance(compat, dict) or "requires" not in compat:
        err("compatibility must be a mapping with a 'requires' key")

    verification = data["verification"]
    if not isinstance(verification, dict):
        err("verification must be a mapping")
    else:
        at = verification.get("automated_tests", {})
        if at.get("status") not in TEST_STATUSES:
            err(f"verification.automated_tests.status must be one of {sorted(TEST_STATUSES)}")
        ab = verification.get("artifact_build", {})
        if ab.get("status") not in TEST_STATUSES:
            err(f"verification.artifact_build.status must be one of {sorted(TEST_STATUSES)}")
        mpc = verification.get("manual_platform_checks", {})
        for platform in ("macos", "windows", "linux"):
            if mpc.get(platform) not in PLATFORM_STATUSES:
                err(f"verification.manual_platform_checks.{platform} must be one of {sorted(PLATFORM_STATUSES)}")
        po = verification.get("production_observation", {})
        if po.get("status") not in OBSERVATION_STATUSES:
            err(f"verification.production_observation.status must be one of {sorted(OBSERVATION_STATUSES)}")

    if not isinstance(data["security_impact"], str) or not data["security_impact"].strip():
        err("security_impact must be a non-empty string ('none' if there is no security impact)")
    if data["type"] == "security" and data["security_impact"].strip().lower() == "none":
        err("type: security requires a real security_impact description, not 'none'")

    if not isinstance(data["documentation_required"], bool):
        err("documentation_required must be a boolean")

    if not isinstance(data["date"], str) or not DATE_RE.match(data["date"]):
        err("date must be an ISO 8601 date string (YYYY-MM-DD)")

    refs = data["references"]
    if not isinstance(refs, dict) or not all(k in refs for k in ("issues", "pull_requests", "commits")):
        err("references must be a mapping with issues, pull_requests, and commits lists")

    return errors


def main(argv: list[str]) -> int:
    registry_path = DEFAULT_REGISTRY
    args = list(argv)
    if "--registry" in args:
        i = args.index("--registry")
        registry_path = pathlib.Path(args[i + 1])
        del args[i : i + 2]

    if not args:
        print("usage: schema.py [--registry PATH] <fragment.yml> [...]", file=sys.stderr)
        return 2

    product_ids = load_product_ids(registry_path)
    all_errors: list[str] = []
    checked = 0
    seen_ids: dict[str, str] = {}
    for arg in args:
        path = pathlib.Path(arg)
        checked += 1
        errors = validate_fragment(path, product_ids)
        all_errors.extend(errors)
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            fid = data.get("id") if isinstance(data, dict) else None
        except yaml.YAMLError:
            fid = None
        if fid:
            if fid in seen_ids:
                all_errors.append(f"{path.name}: duplicate id {fid!r} (already used by {seen_ids[fid]})")
            else:
                seen_ids[fid] = path.name

    if all_errors:
        print(f"{len(all_errors)} problem(s) found across {checked} fragment(s):\n", file=sys.stderr)
        for e in all_errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    print(f"{checked} fragment(s) valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
