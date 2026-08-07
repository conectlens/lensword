#!/usr/bin/env python3
"""Tests for scripts/changelog/validate_registry.py.

Usage:
    cd scripts/changelog && python -m pytest test_validate_registry.py -v
"""
import json
import pathlib

import pytest

from validate_registry import validate

VALID_PRODUCT = {
    "id": "web",
    "name": "Web Application",
    "kind": "public-product",
    "sourcePath": ".",  # repo root always exists — tests don't depend on real product paths
    "purpose": "x",
    "runtimeDependencies": [],
    "install": ["x"],
    "platforms": ["x"],
    "versionSource": "x",
    "currentVersion": "0.1.0",
    "status": "public",
    "ciCoverage": [],
    "releaseChannel": None,
    "changelogRoute": "/reference/changelog/web",
    "versionTagPrefix": "web-v",
    "releaseStatus": "unreleased",
    "artifactTypes": [],
}


def write_registry(tmp_path: pathlib.Path, products: list[dict], use_cases: list | None = None) -> pathlib.Path:
    path = tmp_path / "registry.json"
    path.write_text(json.dumps({"products": products, "useCases": use_cases or []}), encoding="utf-8")
    return path


def write_config(tmp_path: pathlib.Path, routes: list[str]) -> pathlib.Path:
    path = tmp_path / "config.mts"
    body = "\n".join(f"link: '{r}'," for r in routes)
    path.write_text(body, encoding="utf-8")
    return path


def test_valid_registry_has_no_errors(tmp_path):
    registry = write_registry(tmp_path, [VALID_PRODUCT])
    config = write_config(tmp_path, ["/reference/changelog/web"])
    assert validate(registry, config) == []


def test_duplicate_ids_rejected(tmp_path):
    registry = write_registry(tmp_path, [VALID_PRODUCT, {**VALID_PRODUCT, "name": "Other"}])
    config = write_config(tmp_path, ["/reference/changelog/web"])
    errors = validate(registry, config)
    assert any("duplicate product id" in e for e in errors)


def test_duplicate_names_rejected(tmp_path):
    registry = write_registry(tmp_path, [VALID_PRODUCT, {**VALID_PRODUCT, "id": "web2"}])
    config = write_config(tmp_path, ["/reference/changelog/web"])
    errors = validate(registry, config)
    assert any("duplicate product name" in e for e in errors)


def test_missing_field_rejected(tmp_path):
    incomplete = {k: v for k, v in VALID_PRODUCT.items() if k != "purpose"}
    registry = write_registry(tmp_path, [incomplete])
    config = write_config(tmp_path, [])
    errors = validate(registry, config)
    assert any("missing required field" in e for e in errors)


def test_nonexistent_source_path_rejected(tmp_path):
    registry = write_registry(tmp_path, [{**VALID_PRODUCT, "sourcePath": "apps/does-not-exist-xyz"}])
    config = write_config(tmp_path, ["/reference/changelog/web"])
    errors = validate(registry, config)
    assert any("does not exist on disk" in e for e in errors)


def test_invalid_kind_rejected(tmp_path):
    registry = write_registry(tmp_path, [{**VALID_PRODUCT, "kind": "made-up-kind"}])
    config = write_config(tmp_path, ["/reference/changelog/web"])
    errors = validate(registry, config)
    assert any("kind" in e for e in errors)


def test_route_not_in_nav_rejected(tmp_path):
    registry = write_registry(tmp_path, [VALID_PRODUCT])
    config = write_config(tmp_path, ["/reference/changelog/somewhere-else"])
    errors = validate(registry, config)
    assert any("not referenced anywhere in" in e for e in errors)


def test_shared_route_across_products_accepted(tmp_path):
    p2 = {**VALID_PRODUCT, "id": "cli", "name": "Local CLI"}
    registry = write_registry(tmp_path, [VALID_PRODUCT, p2])
    config = write_config(tmp_path, ["/reference/changelog/web"])
    errors = validate(registry, config)
    assert errors == []


def test_unknown_use_case_owner_rejected(tmp_path):
    registry = write_registry(
        tmp_path, [VALID_PRODUCT],
        use_cases=[{"id": "uc1", "ownerProduct": "not-a-real-product"}],
    )
    config = write_config(tmp_path, ["/reference/changelog/web"])
    errors = validate(registry, config)
    assert any("not a registered product id" in e for e in errors)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
