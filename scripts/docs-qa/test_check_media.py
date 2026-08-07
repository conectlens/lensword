#!/usr/bin/env python3
"""Tests for scripts/docs-qa/check_media.py.

Usage:
    cd scripts/docs-qa && python -m pytest test_check_media.py -v
"""
import pathlib

import pytest

from check_media import check_file_sizes, check_secrets_and_paths


def test_undersized_file_passes(tmp_path):
    media = tmp_path / "media"
    media.mkdir()
    (media / "shot.webp").write_bytes(b"x" * 1000)
    assert check_file_sizes(media) == []


def test_oversized_file_rejected(tmp_path):
    media = tmp_path / "media"
    media.mkdir()
    (media / "shot.png").write_bytes(b"x" * 2_000_000)
    errors = check_file_sizes(media)
    assert len(errors) == 1
    assert "exceeds" in errors[0]


def test_unbudgeted_extension_ignored(tmp_path):
    media = tmp_path / "media"
    media.mkdir()
    (media / "notes.json").write_bytes(b"x" * 2_000_000)
    assert check_file_sizes(media) == []


def test_aws_key_detected(tmp_path):
    media = tmp_path / "media"
    media.mkdir()
    (media / "notes.json").write_text('{"key": "AKIAABCDEFGHIJKLMNOP"}', encoding="utf-8")
    errors = check_secrets_and_paths(media)
    assert any("AWS access key" in e for e in errors)


def test_github_token_detected(tmp_path):
    media = tmp_path / "media"
    media.mkdir()
    (media / "notes.txt").write_text("token: ghp_" + "a" * 36, encoding="utf-8")
    errors = check_secrets_and_paths(media)
    assert any("GitHub token" in e for e in errors)


def test_real_windows_user_path_detected(tmp_path):
    media = tmp_path / "media"
    media.mkdir()
    (media / "notes.txt").write_text(r"seen at C:\Users\realperson\Documents", encoding="utf-8")
    errors = check_secrets_and_paths(media)
    assert any("real local Windows user path" in e for e in errors)


def test_demo_windows_path_allowlisted(tmp_path):
    media = tmp_path / "media"
    media.mkdir()
    (media / "notes.txt").write_text(r"C:\Users\demo\Documents", encoding="utf-8")
    assert check_secrets_and_paths(media) == []


def test_fixture_email_on_example_domain_allowed(tmp_path):
    media = tmp_path / "media"
    media.mkdir()
    (media / "notes.json").write_text('{"email": "demo.reviewer@example.com"}', encoding="utf-8")
    assert check_secrets_and_paths(media) == []


def test_non_fixture_email_flagged(tmp_path):
    media = tmp_path / "media"
    media.mkdir()
    (media / "notes.json").write_text('{"email": "realperson@gmail.com"}', encoding="utf-8")
    errors = check_secrets_and_paths(media)
    assert any(e.endswith("realperson@gmail.com") for e in errors)


def test_binary_image_content_not_scanned(tmp_path):
    media = tmp_path / "media"
    media.mkdir()
    # Secret-shaped bytes inside a .webp are not text-scanned — documented
    # limitation (see module docstring), not a bug this test hides.
    (media / "shot.webp").write_bytes(b"AKIAABCDEFGHIJKLMNOP")
    assert check_secrets_and_paths(media) == []


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
