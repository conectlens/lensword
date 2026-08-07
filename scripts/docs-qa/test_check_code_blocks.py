#!/usr/bin/env python3
"""Tests for scripts/docs-qa/check_code_blocks.py.

Usage:
    cd scripts/docs-qa && python -m pytest test_check_code_blocks.py -v
"""
import pathlib

import pytest

from check_code_blocks import check_file, iter_markdown_files


def write(tmp_path: pathlib.Path, name: str, content: str) -> pathlib.Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


def test_valid_json_block_passes(tmp_path):
    path = write(tmp_path, "doc.md", "Example:\n\n```json\n{\"a\": 1}\n```\n")
    errors, skipped = check_file(path)
    assert errors == []


def test_invalid_json_block_rejected(tmp_path):
    path = write(tmp_path, "doc.md", "Example:\n\n```json\n{a: 1}\n```\n")
    errors, skipped = check_file(path)
    assert len(errors) == 1
    assert "doc.md" in errors[0]


def test_valid_yaml_block_passes(tmp_path):
    path = write(tmp_path, "doc.md", "```yaml\nkey: value\nlist:\n  - one\n```\n")
    errors, skipped = check_file(path)
    assert errors == []


def test_invalid_yaml_block_rejected(tmp_path):
    path = write(tmp_path, "doc.md", "```yaml\nkey: [unclosed\n```\n")
    errors, skipped = check_file(path)
    assert len(errors) == 1


def test_non_json_yaml_fence_ignored(tmp_path):
    path = write(tmp_path, "doc.md", "```bash\nnot json { at all\n```\n")
    errors, skipped = check_file(path)
    assert errors == []


def test_multiple_blocks_all_checked(tmp_path):
    path = write(
        tmp_path, "doc.md",
        "```json\n{\"ok\": true}\n```\n\nSome text.\n\n```json\n{bad}\n```\n",
    )
    errors, skipped = check_file(path)
    assert len(errors) == 1


def test_iter_markdown_files_excludes_node_modules(tmp_path, monkeypatch):
    docs = tmp_path / "docs"
    (docs / "node_modules" / "pkg").mkdir(parents=True)
    (docs / "node_modules" / "pkg" / "README.md").write_text("```json\n{bad}\n```\n", encoding="utf-8")
    (docs / "real.md").write_text("fine", encoding="utf-8")

    import check_code_blocks
    monkeypatch.setattr(check_code_blocks, "ROOT", tmp_path)
    monkeypatch.setattr(check_code_blocks, "DOC_ROOTS", [docs])

    files = iter_markdown_files()
    assert docs / "real.md" in files
    assert not any("node_modules" in str(f) for f in files)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
