#!/usr/bin/env python3
"""Tests for scripts/docs-qa/check_routes_links.py's pure logic.

Doesn't invoke npm/vitepress — builds tiny fake dist trees directly, since
the parsing/resolution logic is what can regress, not VitePress's own build.

Usage:
    cd scripts/docs-qa && python -m pytest test_check_routes_links.py -v
"""
import json
import pathlib

import pytest

from check_routes_links import (
    check_internal_links,
    check_readme_links,
    check_registered_routes,
    collect_pages,
    is_ignored_dead_link,
    route_to_dist_file,
)

REGISTRY = {
    "products": [
        {"id": "web", "kind": "public-product", "installRoute": "/install/web-app", "changelogRoute": "/reference/changelog/web"},
        {"id": "backend", "kind": "implementation-dependency"},
    ]
}


def write(dist: pathlib.Path, rel: str, html: str) -> None:
    path = dist / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")


def test_route_to_dist_file_root():
    dist = pathlib.Path("/fake/dist")
    assert route_to_dist_file("/", dist) == dist / "index.html"


def test_route_to_dist_file_nested(tmp_path):
    dist = tmp_path / "dist"
    write(dist, "install/web-app.html", "<html></html>")
    assert route_to_dist_file("/install/web-app", dist) == dist / "install" / "web-app.html"


def test_route_to_dist_file_nested_falls_back_to_index_when_no_html_file(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    assert route_to_dist_file("/install/web-app", dist) == dist / "install" / "web-app" / "index.html"


def test_registered_routes_pass_when_pages_exist(tmp_path):
    dist = tmp_path / "dist"
    write(dist, "install/web-app.html", "<html></html>")
    write(dist, "reference/changelog/web.html", "<html></html>")
    errors = check_registered_routes(REGISTRY, dist)
    assert errors == []


def test_registered_routes_fail_when_page_missing(tmp_path):
    dist = tmp_path / "dist"
    write(dist, "install/web-app.html", "<html></html>")
    # changelog page intentionally not written
    errors = check_registered_routes(REGISTRY, dist)
    assert any("changelogRoute" in e for e in errors)


def test_broken_internal_link_detected(tmp_path):
    dist = tmp_path / "dist"
    write(dist, "index.html", '<a href="/nowhere">link</a>')
    pages = collect_pages(dist)
    errors = check_internal_links(pages, dist)
    assert any("broken link" in e for e in errors)


def test_valid_internal_link_passes(tmp_path):
    dist = tmp_path / "dist"
    write(dist, "index.html", '<a href="/other">link</a>')
    write(dist, "other.html", "<html>hi</html>")
    pages = collect_pages(dist)
    errors = check_internal_links(pages, dist)
    assert errors == []


def test_broken_anchor_detected(tmp_path):
    dist = tmp_path / "dist"
    write(dist, "index.html", '<a href="/other#missing">link</a>')
    write(dist, "other.html", '<h2 id="present">Present</h2>')
    pages = collect_pages(dist)
    errors = check_internal_links(pages, dist)
    assert any("broken anchor" in e for e in errors)


def test_valid_anchor_passes(tmp_path):
    dist = tmp_path / "dist"
    write(dist, "index.html", '<a href="/other#present">link</a>')
    write(dist, "other.html", '<h2 id="present">Present</h2>')
    pages = collect_pages(dist)
    errors = check_internal_links(pages, dist)
    assert errors == []


def test_external_and_mailto_links_skipped(tmp_path):
    dist = tmp_path / "dist"
    write(dist, "index.html", '<a href="https://example.com/nope">ext</a><a href="mailto:a@b.com">mail</a>')
    pages = collect_pages(dist)
    errors = check_internal_links(pages, dist)
    assert errors == []


def test_ignored_dead_link_patterns():
    assert is_ignored_dead_link("./docs/reference/changelog/")
    assert is_ignored_dead_link("./.changes/README")
    assert is_ignored_dead_link("./docs/adr/0002-desktop-backend-mode")
    assert not is_ignored_dead_link("/install/web-app")


def test_broken_image_src_detected(tmp_path):
    dist = tmp_path / "dist"
    write(dist, "index.html", '<img src="/media/missing.webp">')
    pages = collect_pages(dist)
    errors = check_internal_links(pages, dist)
    assert any("broken image" in e for e in errors)


def test_readme_broken_relative_link_detected(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("See [guide](docs/does-not-exist.md).", encoding="utf-8")
    errors = check_readme_links(repo / "README.md", repo)
    assert any("broken link" in e for e in errors)


def test_readme_valid_relative_link_passes(tmp_path):
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    (repo / "docs" / "real.md").write_text("x", encoding="utf-8")
    (repo / "README.md").write_text("See [guide](docs/real.md).", encoding="utf-8")
    errors = check_readme_links(repo / "README.md", repo)
    assert errors == []


def test_readme_external_link_skipped(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("See [site](https://example.com/x).", encoding="utf-8")
    errors = check_readme_links(repo / "README.md", repo)
    assert errors == []


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
