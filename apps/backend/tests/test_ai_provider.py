import ast
import asyncio
import inspect
import re
from pathlib import Path

from app.domain.services.ai_provider import AIProvider, ExtractedVocabulary
from app.infrastructure.ai import OllamaProvider

_ALLOWED_MODULES = ("app.domain", "dataclasses", "typing", "__future__")


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


def test_ai_provider_extraction_signature_is_typed_and_awaitable():
    sig = inspect.signature(AIProvider.extract_vocabulary)
    assert list(sig.parameters) == ["self", "text", "source_language", "target_language", "max_items"]
    assert inspect.iscoroutinefunction(AIProvider.extract_vocabulary)


class _FakeAIProvider:
    async def suggest_mnemonic(self, word: str, context: str) -> str:
        return f"mnemonic for {word} ({context})"

    async def extract_vocabulary(
        self, text: str, source_language: str | None, target_language: str, max_items: int
    ) -> list[ExtractedVocabulary]:
        return [ExtractedVocabulary(term="perro")]


def test_fake_provider_satisfies_the_port():
    provider: AIProvider = _FakeAIProvider()

    result = asyncio.run(provider.suggest_mnemonic("perro", "dog in Spanish"))

    assert result == "mnemonic for perro (dog in Spanish)"
    assert asyncio.run(provider.extract_vocabulary("dog", "English", "Spanish", 1))[0].term == "perro"


def test_the_port_is_awaitable():
    """Generation takes seconds. A synchronous port would put every caller on
    an OS thread for the duration, which is what made unrelated endpoints
    stall under load — so 'awaitable' is part of the contract, not an
    implementation detail of one adapter."""
    assert inspect.iscoroutinefunction(AIProvider.suggest_mnemonic)


def _protocol_method_names() -> set[str]:
    return {name for name, value in vars(AIProvider).items() if not name.startswith("_") and callable(value)}


def test_every_protocol_method_is_implemented_by_ollama_provider():
    """Issue #169: nothing previously checked that the only real provider
    actually implements every AIProvider method. `converse` and
    `evaluate_scenario` were called directly with no existence check and no
    Protocol declaration either — every real call raised AttributeError, and
    it stayed invisible because the test suite's fake provider happened to
    implement both. A provider missing a method now fails here instead of at
    request time."""
    missing = [name for name in _protocol_method_names() if not callable(getattr(OllamaProvider, name, None))]
    assert not missing, f"OllamaProvider is missing protocol methods: {missing}"


def test_every_implemented_method_matches_its_protocol_parameter_names():
    for name in _protocol_method_names():
        protocol_params = list(inspect.signature(getattr(AIProvider, name)).parameters)
        provider_params = list(inspect.signature(getattr(OllamaProvider, name)).parameters)
        assert provider_params == protocol_params, name


_PROVIDER_CALL = re.compile(r"\bprovider\.(\w+)\(")


def test_every_provider_method_called_by_a_router_is_declared_on_the_protocol():
    """The actual failure mode in issue #169, and what the two checks above
    would *not* have caught on their own: `converse` and `evaluate_scenario`
    were called directly on the injected provider from two routers with no
    Protocol declaration at all, so a cross-check against the Protocol's own
    (incomplete) member list stayed green throughout. This scans the routers
    for `provider.<name>(` call sites instead, and asserts every one is part
    of the Protocol contract — so a router calling an undeclared method fails
    here rather than at request time."""
    routers_dir = Path(__file__).resolve().parents[1] / "app" / "api" / "routers"
    protocol_methods = _protocol_method_names()

    called: set[str] = set()
    for path in routers_dir.glob("*.py"):
        called.update(_PROVIDER_CALL.findall(path.read_text()))

    assert called, "expected at least one provider.<method>() call site to check"
    missing = called - protocol_methods
    assert not missing, f"routers call provider methods not declared on AIProvider: {missing}"
