#!/usr/bin/env python3
"""Tests for scripts/changelog/schema.py.

Covers the highest-value validation scenarios from issue #281's
specification: unknown product, missing required field, breaking change
without migration, invalid verification status, security type without a
real security_impact, and duplicate fragment IDs. Does not attempt the
full 20-scenario list the issue names (squash-merge/cherry-pick/GitHub
API-failure handling belongs to the generator's git-log integration, not
fragment schema validation, and isn't covered here) — see this file's
module docstring in the PR description for what's deferred to #282.

Usage:
    cd scripts/changelog && python -m pytest test_schema.py -v
"""
import pathlib
import sys
import tempfile

import pytest
import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from schema import validate_fragment, main  # noqa: E402

PRODUCT_IDS = {"web", "desktop", "browser-extension", "mcp-server", "local-cli", "backend"}

VALID_FRAGMENT = {
    "id": "example-fix",
    "products": ["web"],
    "type": "fixed",
    "summary": "Example fix.",
    "user_impact": "Nothing visible changes.",
    "release_status": "unreleased",
    "breaking": False,
    "migration": "none",
    "known_limitations": [],
    "compatibility": {"requires": {"server_api": None}},
    "verification": {
        "automated_tests": {"status": "passed", "commands": ["pytest -v"], "workflow_url": None},
        "artifact_build": {"status": "not_run", "artifacts": []},
        "manual_platform_checks": {"macos": "not_applicable", "windows": "not_applicable", "linux": "not_applicable"},
        "production_observation": {"status": "not_observed"},
    },
    "security_impact": "none",
    "documentation_required": True,
    "date": "2026-08-07",
    "references": {"issues": [], "pull_requests": [], "commits": []},
}


def write_fragment(tmp_path: pathlib.Path, data: dict, filename: str | None = None) -> pathlib.Path:
    path = tmp_path / (filename or f"{data['id']}.yml")
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def test_valid_fragment_has_no_errors(tmp_path):
    path = write_fragment(tmp_path, VALID_FRAGMENT)
    assert validate_fragment(path, PRODUCT_IDS) == []


def test_unknown_product_rejected(tmp_path):
    data = {**VALID_FRAGMENT, "id": "bad-product", "products": ["quantum-teleporter"]}
    path = write_fragment(tmp_path, data)
    errors = validate_fragment(path, PRODUCT_IDS)
    assert any("unknown product id" in e for e in errors)


def test_missing_required_field_rejected(tmp_path):
    data = {k: v for k, v in VALID_FRAGMENT.items() if k != "summary"}
    data["id"] = "missing-summary"
    path = write_fragment(tmp_path, data)
    errors = validate_fragment(path, PRODUCT_IDS)
    assert any("missing required field" in e for e in errors)


def test_breaking_without_migration_rejected(tmp_path):
    data = {**VALID_FRAGMENT, "id": "breaking-no-migration", "breaking": True, "migration": "none"}
    path = write_fragment(tmp_path, data)
    errors = validate_fragment(path, PRODUCT_IDS)
    assert any("migration" in e for e in errors)


def test_breaking_with_migration_accepted(tmp_path):
    data = {**VALID_FRAGMENT, "id": "breaking-with-migration", "breaking": True, "migration": "Update your config: rename X to Y."}
    path = write_fragment(tmp_path, data)
    assert validate_fragment(path, PRODUCT_IDS) == []


def test_invalid_verification_status_rejected(tmp_path):
    data = {**VALID_FRAGMENT, "id": "bad-verification"}
    data["verification"] = {**VALID_FRAGMENT["verification"], "automated_tests": {"status": "definitely_maybe", "commands": [], "workflow_url": None}}
    path = write_fragment(tmp_path, data)
    errors = validate_fragment(path, PRODUCT_IDS)
    assert any("automated_tests.status" in e for e in errors)


def test_security_type_requires_real_impact(tmp_path):
    data = {**VALID_FRAGMENT, "id": "security-no-impact", "type": "security", "security_impact": "none"}
    path = write_fragment(tmp_path, data)
    errors = validate_fragment(path, PRODUCT_IDS)
    assert any("security_impact" in e for e in errors)


def test_security_type_with_real_impact_accepted(tmp_path):
    data = {**VALID_FRAGMENT, "id": "security-real-impact", "type": "security", "security_impact": "Fixed a token-leak in log output."}
    path = write_fragment(tmp_path, data)
    assert validate_fragment(path, PRODUCT_IDS) == []


def test_id_must_match_filename(tmp_path):
    data = {**VALID_FRAGMENT, "id": "correct-id"}
    path = write_fragment(tmp_path, data, filename="wrong-filename.yml")
    errors = validate_fragment(path, PRODUCT_IDS)
    assert any("does not match filename" in e for e in errors)


def test_duplicate_ids_detected_across_files(tmp_path, capsys):
    write_fragment(tmp_path, {**VALID_FRAGMENT, "id": "dup"}, "dup.yml")
    write_fragment(tmp_path, {**VALID_FRAGMENT, "id": "dup"}, "dup-copy.yml")
    registry = tmp_path / "registry.json"
    registry.write_text('{"products": [{"id": "web"}]}', encoding="utf-8")
    exit_code = main(["--registry", str(registry), str(tmp_path / "dup.yml"), str(tmp_path / "dup-copy.yml")])
    assert exit_code == 1
    assert "duplicate id" in capsys.readouterr().err


def test_multi_product_fragment_accepted(tmp_path):
    data = {**VALID_FRAGMENT, "id": "multi-product", "products": ["web", "desktop", "browser-extension"]}
    path = write_fragment(tmp_path, data)
    assert validate_fragment(path, PRODUCT_IDS) == []


def test_none_type_with_reason_accepted(tmp_path):
    data = {
        **VALID_FRAGMENT, "id": "internal-refactor", "type": "none",
        "reason": "Internal refactor of test helpers, no observable behavior change.",
        "documentation_required": False,
    }
    path = write_fragment(tmp_path, data)
    assert validate_fragment(path, PRODUCT_IDS) == []


def test_none_type_without_reason_rejected(tmp_path):
    data = {**VALID_FRAGMENT, "id": "no-reason", "type": "none", "documentation_required": False}
    path = write_fragment(tmp_path, data)
    errors = validate_fragment(path, PRODUCT_IDS)
    assert any("requires a non-empty 'reason'" in e for e in errors)


def test_none_type_with_documentation_required_true_rejected(tmp_path):
    data = {
        **VALID_FRAGMENT, "id": "bad-doc-flag", "type": "none",
        "reason": "Some internal change.", "documentation_required": True,
    }
    path = write_fragment(tmp_path, data)
    errors = validate_fragment(path, PRODUCT_IDS)
    assert any("documentation_required: false" in e for e in errors)


def test_automated_tests_passed_without_evidence_rejected(tmp_path):
    data = {**VALID_FRAGMENT, "id": "unevidenced-tests"}
    data["verification"] = {
        **VALID_FRAGMENT["verification"],
        "automated_tests": {"status": "passed", "commands": [], "workflow_url": None},
    }
    path = write_fragment(tmp_path, data)
    errors = validate_fragment(path, PRODUCT_IDS)
    assert any("passed requires at least one command or a workflow_url" in e for e in errors)


def test_automated_tests_passed_with_command_accepted(tmp_path):
    data = {**VALID_FRAGMENT, "id": "evidenced-tests"}
    data["verification"] = {
        **VALID_FRAGMENT["verification"],
        "automated_tests": {"status": "passed", "commands": ["pytest -v"], "workflow_url": None},
    }
    path = write_fragment(tmp_path, data)
    assert validate_fragment(path, PRODUCT_IDS) == []


def test_artifact_build_passed_without_evidence_rejected(tmp_path):
    data = {**VALID_FRAGMENT, "id": "unevidenced-build"}
    data["verification"] = {
        **VALID_FRAGMENT["verification"],
        "artifact_build": {"status": "passed", "artifacts": []},
    }
    path = write_fragment(tmp_path, data)
    errors = validate_fragment(path, PRODUCT_IDS)
    assert any("passed requires at least one artifact reference" in e for e in errors)


def test_invalid_yaml_reported_not_crashed(tmp_path):
    path = tmp_path / "broken.yml"
    path.write_text("id: [unclosed", encoding="utf-8")
    errors = validate_fragment(path, PRODUCT_IDS)
    assert len(errors) == 1
    assert "invalid YAML" in errors[0]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
