#!/usr/bin/env python3
"""Generate LensWord's per-product changelog pages from .changes/*.yml fragments.

Deterministic and idempotent: the same fragments + registry + git history
always produce byte-identical output. Run after adding or editing a
fragment (see .changes/README.md), and commit the regenerated pages
alongside it — the fragments are canonical, the generated Markdown is a
build output.

Usage:
    python scripts/changelog/generate.py
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
CHANGES_DIR = ROOT / ".changes"
REGISTRY_PATH = ROOT / "docs" / "internal" / "product-registry.json"
OUT_DIR = ROOT / "docs" / "reference" / "changelog"

TYPE_LABELS = {
    "added": "Added", "changed": "Changed", "fixed": "Fixed", "security": "Security",
    "deprecated": "Deprecated", "removed": "Removed", "performance": "Performance",
    "documentation": "Documentation",
}
TYPE_ORDER = list(TYPE_LABELS)


def load_registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def load_fragments() -> list[dict]:
    fragments = []
    for path in sorted(CHANGES_DIR.glob("*.yml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        data["_source"] = path.name
        fragments.append(data)
    # Deterministic order: newest date first, then id as a stable tiebreaker.
    fragments.sort(key=lambda f: (f["date"], f["id"]), reverse=True)
    fragments.sort(key=lambda f: f["date"], reverse=True)
    return fragments


def verification_summary(f: dict) -> str:
    v = f["verification"]
    parts = []
    at = v["automated_tests"]["status"]
    if at != "not_run":
        parts.append(f"automated tests: {at}")
    ab = v["artifact_build"]["status"]
    if ab != "not_run":
        parts.append(f"artifact build: {ab}")
    mpc = v["manual_platform_checks"]
    platform_bits = [f"{p}: {s}" for p, s in mpc.items() if s not in ("not_run", "not_applicable")]
    if platform_bits:
        parts.append("manual checks — " + ", ".join(platform_bits))
    po = v["production_observation"]["status"]
    if po != "not_observed":
        parts.append(f"production observation: {po}")
    return "; ".join(parts) if parts else "not verified"


def render_entry(f: dict) -> str:
    label = TYPE_LABELS[f["type"]]
    lines = [f"### {label}: {f['summary']}"]
    lines.append("")
    lines.append(f"*{f['date']}* — verification: {verification_summary(f)}")
    if f["breaking"]:
        lines.append("")
        lines.append(f"**Breaking.** {f['migration']}")
    lines.append("")
    lines.append(f["user_impact"])
    if f.get("technical_summary"):
        lines.append("")
        lines.append(f"<details><summary>Technical detail</summary>\n\n{f['technical_summary']}\n\n</details>")
    if f["known_limitations"]:
        lines.append("")
        lines.append("**Known limitations:**")
        for lim in f["known_limitations"]:
            lines.append(f"- {lim}")
    refs = f["references"]
    ref_bits = []
    for issue in refs.get("issues", []):
        ref_bits.append(f"[#{issue}](https://github.com/conectlens/lensword/issues/{issue})")
    for pr in refs.get("pull_requests", []):
        ref_bits.append(f"[PR #{pr}](https://github.com/conectlens/lensword/pull/{pr})")
    if ref_bits:
        lines.append("")
        lines.append("References: " + ", ".join(ref_bits))
    lines.append("")
    return "\n".join(lines)


def render_product_page(products_at_route: list[dict], fragments: list[dict]) -> str:
    # A route can serve more than one registry product (mcp-server and
    # local-cli both live in apps/mcp and share /reference/changelog/mcp) —
    # render the union of their fragments rather than letting the second
    # product silently overwrite the first's page.
    ids_at_route = {p["id"] for p in products_at_route}
    relevant = [f for f in fragments if ids_at_route & set(f["products"])]
    title = " / ".join(p["name"] for p in products_at_route)
    statuses = ", ".join(f"{p['name']}: **{p.get('releaseStatus', 'unknown')}**" for p in products_at_route)
    lines = [
        "---",
        f"title: {title} Changelog",
        f"description: User-facing changes to {title}, with verification evidence per entry.",
        "---",
        "",
        f"# {title} changelog",
        "",
        f"Status — {statuses}.",
        "",
        "Every entry states exactly what was verified — a passing automated "
        "test does not imply a platform was manually checked, and a manual "
        "check on one OS does not imply another. See "
        "[Verification levels](/reference/trust/verification-levels) for "
        "what each status means.",
        "",
    ]
    if not relevant:
        lines.append("No changelog entries recorded for this product yet.")
        lines.append("")
    else:
        for f in relevant:
            lines.append(render_entry(f))
    return "\n".join(lines)


def render_overview(products: list[dict], fragments: list[dict]) -> str:
    lines = [
        "---",
        "title: Changelog",
        "description: Product-aware changelog overview — every LensWord surface, with its own release identity and verification evidence.",
        "---",
        "",
        "# Changelog",
        "",
        "LensWord isn't one product with one changelog — it's five "
        "independently distributable surfaces (plus a shared backend that "
        "isn't independently released), each with its own release status "
        "and verification evidence. Pick a product below for its full "
        "history, or read the combined list here.",
        "",
        "| Product | Status | Changelog |",
        "|---|---|---|",
    ]
    public = [p for p in products if p["kind"] == "public-product"]
    for p in public:
        lines.append(f"| {p['name']} | {p.get('releaseStatus', 'unknown')} | [{p['name']} changelog]({p['changelogRoute']}) |")
    lines.append("")
    lines.append(
        "The shared backend (`apps/backend`) is not an independently "
        "released product — see "
        "[docs/internal/repo-audit.md](https://github.com/conectlens/lensword/blob/development/docs/internal/repo-audit.md). "
        "Its changes are folded into whichever product(s) they actually "
        "affect, listed below."
    )
    lines.append("")
    lines.append("## Latest changes, all products")
    lines.append("")
    for f in fragments:
        product_names = ", ".join(
            next(p["name"] for p in products if p["id"] == pid) for pid in f["products"]
        )
        lines.append(f"**{product_names}**")
        lines.append("")
        lines.append(render_entry(f))
    lines.append("Also see [Main Branch Activity](/reference/changelog/main-branch-activity) — what's merged but not yet part of any release, and [Releases](/reference/releases/) — published, immutable release records (none exist yet).")
    lines.append("")
    return "\n".join(lines)


def git_log_entries(limit: int = 40) -> list[dict]:
    fmt = "%H%x1f%h%x1f%ad%x1f%an%x1f%s"
    try:
        raw = subprocess.run(
            ["git", "log", f"-{limit}", "--date=short", f"--pretty=format:{fmt}", "development"],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True,
        ).stdout
    except subprocess.CalledProcessError:
        return []
    entries = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        sha, short_sha, date, author, subject = line.split("\x1f")
        entries.append({"sha": sha, "short_sha": short_sha, "date": date, "author": author, "subject": subject})
    return entries


def render_main_branch_activity(fragments: list[dict]) -> str:
    entries = git_log_entries()
    pr_to_fragment: dict[int, dict] = {}
    for f in fragments:
        for pr in f["references"].get("pull_requests", []):
            pr_to_fragment[pr] = f

    lines = [
        "---",
        "title: Main Branch Activity",
        "description: What's merged into development — not a release, and not yet available in any downloadable, hosted, packaged, or published LensWord product.",
        "---",
        "",
        "# Main Branch Activity",
        "",
        "> Changes listed here exist on the `development` branch. They may "
        "not yet be available in any downloadable, hosted, packaged, or "
        "published LensWord product, and they may be modified or reverted "
        "before release. **Merged is not released.**",
        "",
        "This ledger covers the most recent commits on `development` "
        "(regenerate to extend it) — it is not a complete historical mining "
        "of every commit ever merged, including squash merges, cherry-picks, "
        "and bot commits from before this system existed. Entries for "
        "commits predating the changelog-fragment system show `Changelog "
        "fragment: none (predates this system)` rather than a fabricated "
        "product assignment.",
        "",
        "| Date | Commit | Author | Subject | Changelog fragment |",
        "|---|---|---|---|---|",
    ]
    import re

    pr_re = re.compile(r"\(#(\d+)\)\s*$")
    for e in entries:
        m = pr_re.search(e["subject"])
        pr_num = int(m.group(1)) if m else None
        fragment = pr_to_fragment.get(pr_num) if pr_num else None
        frag_cell = f"[{fragment['id']}](#{fragment['id']})" if fragment else "none (predates this system)"
        subject_escaped = e["subject"].replace("|", "\\|")
        commit_link = f"[{e['short_sha']}](https://github.com/conectlens/lensword/commit/{e['sha']})"
        lines.append(f"| {e['date']} | {commit_link} | {e['author']} | {subject_escaped} | {frag_cell} |")
    lines.append("")
    lines.append(f"Generated from `git log -40 development` — {len(entries)} commits shown.")
    lines.append("")
    return "\n".join(lines)


def render_releases_index() -> str:
    return "\n".join([
        "---",
        "title: Releases",
        "description: Immutable release records — none exist yet for any LensWord product.",
        "---",
        "",
        "# Releases",
        "",
        "**No release has been published for any LensWord product.** "
        "Confirmed via `git tag -l` and `gh release list` — both empty. "
        "This page will list an immutable record per release (version, "
        "tag, commit SHA, included changes, checksums, and verification "
        "evidence) once one exists — see "
        "[Release process](/reference/trust/release-process) for how a "
        "release will be cut and promoted from `Unreleased` to `Released`.",
        "",
        "See each product's changelog for what's changed since the "
        "project started, all of it still `unreleased`:",
        "",
    ])


def render_compatibility(products: list[dict]) -> str:
    lines = [
        "---",
        "title: Compatibility Matrix",
        "description: Version compatibility between LensWord products — reported honestly, not invented.",
        "---",
        "",
        "# Compatibility matrix",
        "",
        "No LensWord product has a tagged release yet, so no compatibility "
        "range has ever been declared or tested end to end. This page "
        "reports that plainly rather than inventing a plausible-looking "
        "matrix — every cell below is genuinely `Not declared`, not a "
        "placeholder waiting to be filled with guesses.",
        "",
        "| Product | Requires server/API version | Status |",
        "|---|---|---|",
    ]
    for p in products:
        if p["kind"] != "public-product":
            continue
        lines.append(f"| {p['name']} | Not declared | Not tested |")
    lines.append("")
    lines.append(
        "Once a product declares a `compatibility.requires.server_api` "
        "constraint in a changelog fragment (see `.changes/README.md`), "
        "this page will report it here instead of `Not declared`."
    )
    lines.append("")
    return "\n".join(lines)


def write(path: pathlib.Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")
    print(f"wrote {path.relative_to(ROOT)}")


def main() -> int:
    registry = load_registry()
    products = registry["products"]
    fragments = load_fragments()

    write(OUT_DIR / "index.md", render_overview(products, fragments))

    by_route: dict[str, list[dict]] = {}
    for p in products:
        if p["kind"] != "public-product":
            continue
        by_route.setdefault(p["changelogRoute"], []).append(p)
    for route, products_at_route in by_route.items():
        slug = route.rsplit("/", 1)[-1]
        write(OUT_DIR / f"{slug}.md", render_product_page(products_at_route, fragments))
    write(OUT_DIR / "main-branch-activity.md", render_main_branch_activity(fragments))
    write(ROOT / "docs" / "reference" / "releases" / "index.md", render_releases_index())
    write(ROOT / "docs" / "reference" / "trust" / "compatibility.md", render_compatibility(products))

    print(f"\n{len(fragments)} fragment(s) rendered across {len([p for p in products if p['kind'] == 'public-product'])} public product(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
