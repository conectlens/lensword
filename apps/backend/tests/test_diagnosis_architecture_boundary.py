"""ADR 0007 / issue #181 TODO 0: the domain package stays framework-free.

Statically parsed rather than imported, so this catches a forbidden import
even in a module nothing else happens to import yet, and never triggers the
side effects (network clients, DB engines) importing the modules for real
would risk.
"""
import ast
from pathlib import Path

import pytest

DOMAIN_ROOT = Path(__file__).resolve().parents[1] / "app" / "domain"

# Top-level module names a domain file must never import. Not "sqlalchemy"
# alone: its submodules (sqlalchemy.orm, sqlalchemy.ext...) share the prefix
# and are just as much an infrastructure leak.
FORBIDDEN_TOP_LEVEL = {
    "fastapi",
    "starlette",
    "sqlalchemy",
    "httpx",
    "requests",
    "aiohttp",
    "ollama",
}
# Specific submodules rather than a whole stdlib package: urllib.parse (URL
# validation, used legitimately in url_safety.py) is not the HTTP client;
# urllib.request is.
FORBIDDEN_DOTTED = {"urllib.request"}


def _domain_files() -> list[Path]:
    return sorted(p for p in DOMAIN_ROOT.rglob("*.py") if "__pycache__" not in p.parts)


def _imported_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


@pytest.mark.parametrize("path", _domain_files(), ids=lambda p: str(p.relative_to(DOMAIN_ROOT)))
def test_domain_module_has_no_framework_or_infrastructure_imports(path: Path):
    tree = ast.parse(path.read_text(), filename=str(path))
    imported = _imported_names(tree)

    top_level_violations = {name for name in imported if name.split(".")[0] in FORBIDDEN_TOP_LEVEL}
    dotted_violations = {name for name in imported if name in FORBIDDEN_DOTTED}

    violations = top_level_violations | dotted_violations
    assert not violations, (
        f"{path.relative_to(DOMAIN_ROOT)} imports {sorted(violations)} — "
        "the domain layer must have zero framework/infrastructure dependencies "
        "(ADR 0007). Move this code to app.application or app.infrastructure."
    )


def test_the_domain_package_is_not_accidentally_empty():
    # A passing parametrized test with zero cases would be silent, not green
    # — this catches DOMAIN_ROOT resolving to the wrong path.
    assert len(_domain_files()) > 10
