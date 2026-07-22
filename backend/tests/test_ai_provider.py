import ast
import inspect
from pathlib import Path

from app.domain.services.ai_provider import AIProvider

_ALLOWED_MODULES = ("app.domain", "typing", "__future__")


def _imported_module_names(source_path: Path) -> list[str]:
    tree = ast.parse(source_path.read_text())
    modules = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules


def _is_allowed(module: str) -> bool:
    """Exact match or dotted-segment prefix — 'typing' must not match
    'typing_extensions', only 'typing' itself or 'typing.something'."""
    return any(module == allowed or module.startswith(allowed + ".") for allowed in _ALLOWED_MODULES)


def test_import_matcher_rejects_lookalike_third_party_module():
    assert not _is_allowed("typing_extensions")
    assert _is_allowed("typing")
    assert _is_allowed("app.domain.entities")


def test_ai_provider_module_has_zero_third_party_or_framework_imports():
    source_path = Path(inspect.getfile(AIProvider))
    modules = _imported_module_names(source_path)

    assert modules, "expected at least one import to check"
    for module in modules:
        assert _is_allowed(module), f"disallowed import: {module}"


def test_ai_provider_protocol_signature_is_word_and_context():
    sig = inspect.signature(AIProvider.suggest_mnemonic)
    assert list(sig.parameters) == ["self", "word", "context"]


class _FakeAIProvider:
    def suggest_mnemonic(self, word: str, context: str) -> str:
        return f"mnemonic for {word} ({context})"


def test_fake_provider_satisfies_the_port():
    provider: AIProvider = _FakeAIProvider()

    result = provider.suggest_mnemonic("perro", "dog in Spanish")

    assert result == "mnemonic for perro (dog in Spanish)"
