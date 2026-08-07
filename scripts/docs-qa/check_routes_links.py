#!/usr/bin/env python3
"""Verify VitePress route coverage and internal link/anchor integrity.

Implements #283 TODO 1 (route coverage from the product registry, fail on
internal 404s/broken anchors) and part of TODO 2 (README relative links,
VitePress internal links, image references). Runs against an already-built
site (`npm run docs:build` in docs/) — this script does not build it.

No third-party dependencies: html.parser is stdlib, and this repo already
avoids adding a jsonschema/bs4-class dependency for the same class of
problem (see scripts/changelog/schema.py's docstring).

Usage:
    cd docs && npm run docs:build && cd ..
    python scripts/docs-qa/check_routes_links.py
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
from html.parser import HTMLParser
from urllib.parse import urlsplit

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
DIST_DIR = ROOT / "docs" / ".vitepress" / "dist"
REGISTRY_PATH = ROOT / "docs" / "internal" / "product-registry.json"
README_PATH = ROOT / "README.md"

EXTERNAL_SCHEMES = {"http", "https", "mailto", "tel"}

# Mirrors docs/.vitepress/config.mts's own ignoreDeadLinks — CHANGELOG.md is
# @include'd verbatim into legacy.md and its links are deliberately correct
# for viewing the file at the repo root on GitHub, not as site routes (see
# that file's comment). Keep these two lists in sync by hand; config.mts is
# TypeScript, not something this stdlib-only script parses.
IGNORE_DEAD_LINK_PATTERNS = [
    re.compile(r"^\.?/?docs/(adr/|ai-model-verification|reference/changelog/)"),
    re.compile(r"^\.?/?\.changes/"),
]


def is_ignored_dead_link(href: str) -> bool:
    path_part = href.split("#", 1)[0].split("?", 1)[0]
    return any(p.match(path_part) for p in IGNORE_DEAD_LINK_PATTERNS)


class PageLinks(HTMLParser):
    """Collects internal hrefs/img srcs and element ids from one rendered page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: list[str] = []
        self.srcs: list[str] = []
        self.ids: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_dict = dict(attrs)
        if tag == "a" and attr_dict.get("href"):
            self.hrefs.append(attr_dict["href"])
        if tag == "img" and attr_dict.get("src"):
            self.srcs.append(attr_dict["src"])
        if attr_dict.get("id"):
            self.ids.add(attr_dict["id"])

    handle_startendtag = handle_starttag


def load_registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def expected_routes(registry: dict) -> list[tuple[str, str, str]]:
    """Returns (product_id, route_kind, route) for every public product's guide + changelog route."""
    out = []
    for p in registry["products"]:
        if p["kind"] != "public-product":
            continue
        if not p.get("installRoute"):
            out.append((p["id"], "installRoute", "<missing>"))
        else:
            out.append((p["id"], "installRoute", p["installRoute"]))
        if not p.get("changelogRoute"):
            out.append((p["id"], "changelogRoute", "<missing>"))
        else:
            out.append((p["id"], "changelogRoute", p["changelogRoute"]))
    return out


def route_to_dist_file(route: str, dist_dir: pathlib.Path) -> pathlib.Path:
    """cleanUrls: true means '/foo/bar' on disk is dist/foo/bar.html, '/' is dist/index.html."""
    route = route.split("#", 1)[0].split("?", 1)[0]
    route = route.strip("/")
    if route == "":
        return dist_dir / "index.html"
    direct = dist_dir / f"{route}.html"
    if direct.exists():
        return direct
    return dist_dir / route / "index.html"


def check_registered_routes(registry: dict, dist_dir: pathlib.Path) -> list[str]:
    errors = []
    for product_id, kind, route in expected_routes(registry):
        if route == "<missing>":
            errors.append(f"product {product_id!r}: no {kind} declared in the registry")
            continue
        target = route_to_dist_file(route, dist_dir)
        if not target.exists():
            errors.append(f"product {product_id!r}: {kind} {route!r} has no built page ({target} missing)")
    return errors


def collect_pages(dist_dir: pathlib.Path) -> dict[pathlib.Path, PageLinks]:
    pages = {}
    for html_file in dist_dir.rglob("*.html"):
        parser = PageLinks()
        parser.feed(html_file.read_text(encoding="utf-8", errors="replace"))
        pages[html_file] = parser
    return pages


def resolve_href(href: str, from_file: pathlib.Path, dist_dir: pathlib.Path) -> pathlib.Path | None:
    """Resolve an href from a page to a dist file path, or None if not a checkable internal link."""
    scheme = urlsplit(href).scheme
    if scheme in EXTERNAL_SCHEMES:
        return None
    if href.startswith("#"):
        return from_file  # same-page anchor
    path_part = href.split("#", 1)[0].split("?", 1)[0]
    if not path_part:
        return from_file
    if href.startswith("/"):
        base = dist_dir
        rel = path_part.lstrip("/")
    else:
        base = from_file.parent
        rel = path_part
    candidate = (base / rel).resolve()
    if candidate.is_dir():
        candidate = candidate / "index.html"
    elif not candidate.suffix:
        html_candidate = candidate.with_suffix(".html")
        if html_candidate.exists():
            candidate = html_candidate
        else:
            candidate = candidate / "index.html"
    return candidate


def check_internal_links(pages: dict[pathlib.Path, PageLinks], dist_dir: pathlib.Path) -> list[str]:
    errors = []
    for from_file, parser in pages.items():
        rel_from = from_file.relative_to(dist_dir)
        for href in parser.hrefs:
            if is_ignored_dead_link(href):
                continue
            target = resolve_href(href, from_file, dist_dir)
            if target is None:
                continue
            if not target.exists():
                errors.append(f"{rel_from}: broken link {href!r} -> {target.relative_to(dist_dir) if _under(target, dist_dir) else target} does not exist")
                continue
            fragment = href.split("#", 1)[1] if "#" in href else None
            if fragment and target in pages and fragment not in pages[target].ids:
                errors.append(f"{rel_from}: broken anchor '#{fragment}' in link {href!r} (target page has no matching id)")
        for src in parser.srcs:
            target = resolve_href(src, from_file, dist_dir)
            if target is not None and not target.exists():
                errors.append(f"{rel_from}: broken image src {src!r} -> file does not exist")
    return errors


def _under(path: pathlib.Path, base: pathlib.Path) -> bool:
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


MD_LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")


def check_readme_links(readme_path: pathlib.Path, repo_root: pathlib.Path) -> list[str]:
    errors = []
    if not readme_path.exists():
        return [f"{readme_path} does not exist"]
    text = readme_path.read_text(encoding="utf-8")
    for match in MD_LINK_RE.finditer(text):
        target = match.group(1)
        scheme = urlsplit(target).scheme
        if scheme in EXTERNAL_SCHEMES:
            continue
        if target.startswith("#"):
            continue  # in-page anchor; VitePress/GitHub both slugify headings differently, not checked here
        path_part = target.split("#", 1)[0]
        if not path_part:
            continue
        candidate = (repo_root / path_part.lstrip("/")).resolve() if target.startswith("/") else (repo_root / path_part).resolve()
        if not candidate.exists():
            errors.append(f"README.md: broken link/image {target!r} -> {path_part} does not exist")
    return errors


def main(argv: list[str]) -> int:
    if not DIST_DIR.exists():
        print(f"error: {DIST_DIR.relative_to(ROOT)} does not exist — run 'npm run docs:build' in docs/ first", file=sys.stderr)
        return 2

    registry = load_registry()
    errors: list[str] = []
    errors += check_registered_routes(registry, DIST_DIR)

    pages = collect_pages(DIST_DIR)
    errors += check_internal_links(pages, DIST_DIR)
    errors += check_readme_links(README_PATH, ROOT)

    if errors:
        print(f"{len(errors)} problem(s) found:\n", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    print(f"routes/links valid: {len(pages)} built page(s) checked, every registered product has a working guide + changelog route.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
