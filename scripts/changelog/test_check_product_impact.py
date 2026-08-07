#!/usr/bin/env python3
"""Tests for scripts/changelog/check_product_impact.py.

Builds a real, throwaway git repo per test — the script's own logic shells
out to `git diff`, so faking that call would test the mock, not the diff
handling (which base...head triple-dot range, whether renames confuse
prefix matching, etc.).

Usage:
    cd scripts/changelog && python -m pytest test_check_product_impact.py -v
"""
import json
import pathlib
import subprocess

import pytest

from check_product_impact import check

REGISTRY = {
    "products": [
        {"id": "web", "name": "Web Application", "sourcePath": "apps/frontend", "runtimeDependencies": ["apps/backend"]},
        {"id": "backend", "name": "Backend (API)", "sourcePath": "apps/backend", "runtimeDependencies": []},
    ]
}


def run(repo: pathlib.Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def init_repo(tmp_path: pathlib.Path) -> pathlib.Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    run(repo, "init", "-q", "-b", "main")
    run(repo, "config", "user.email", "test@example.com")
    run(repo, "config", "user.name", "Test")
    (repo / "apps" / "frontend").mkdir(parents=True)
    (repo / "apps" / "backend").mkdir(parents=True)
    (repo / "apps" / "frontend" / "placeholder.txt").write_text("x", encoding="utf-8")
    (repo / "apps" / "backend" / "placeholder.txt").write_text("x", encoding="utf-8")
    (repo / ".changes").mkdir()
    run(repo, "add", "-A")
    run(repo, "commit", "-q", "-m", "initial")
    run(repo, "branch", "base")
    return repo


def write_registry(repo: pathlib.Path) -> pathlib.Path:
    path = repo / "registry.json"
    path.write_text(json.dumps(REGISTRY), encoding="utf-8")
    return path


def commit_change(repo: pathlib.Path, rel_path: str, content: str, message: str) -> None:
    path = repo / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    run(repo, "add", "-A")
    run(repo, "commit", "-q", "-m", message)


def test_touched_product_without_fragment_fails(tmp_path):
    repo = init_repo(tmp_path)
    registry = write_registry(repo)
    commit_change(repo, "apps/frontend/new.tsx", "x", "add frontend file")
    errors, warnings = check("base", "HEAD", registry, repo)
    assert any("no changelog fragment" in e for e in errors)


def test_touched_product_with_matching_fragment_passes(tmp_path):
    repo = init_repo(tmp_path)
    registry = write_registry(repo)
    commit_change(repo, "apps/frontend/new.tsx", "x", "add frontend file")
    commit_change(repo, ".changes/my-change.yml", "id: my-change\nproducts: [web]\n", "add fragment")
    errors, warnings = check("base", "HEAD", registry, repo)
    assert errors == []
    assert warnings == []


def test_untouched_product_no_check_needed(tmp_path):
    repo = init_repo(tmp_path)
    registry = write_registry(repo)
    commit_change(repo, "README.md", "docs only", "docs change")
    errors, warnings = check("base", "HEAD", registry, repo)
    assert errors == []
    assert warnings == []


def test_fragment_names_untouched_product_warns(tmp_path):
    repo = init_repo(tmp_path)
    registry = write_registry(repo)
    commit_change(repo, "apps/frontend/new.tsx", "x", "add frontend file")
    commit_change(repo, ".changes/my-change.yml", "id: my-change\nproducts: [web, backend]\n", "add fragment")
    errors, warnings = check("base", "HEAD", registry, repo)
    assert errors == []
    assert any("backend" in w and "no changed file" in w for w in warnings)


def test_touched_product_not_named_in_any_fragment_warns(tmp_path):
    repo = init_repo(tmp_path)
    registry = write_registry(repo)
    commit_change(repo, "apps/frontend/new.tsx", "x", "add frontend file")
    commit_change(repo, "apps/backend/new.py", "x", "add backend file")
    commit_change(repo, ".changes/my-change.yml", "id: my-change\nproducts: [web]\n", "add fragment")
    errors, warnings = check("base", "HEAD", registry, repo)
    assert errors == []
    assert any("backend" in w and "no fragment in this PR names it" in w for w in warnings)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
