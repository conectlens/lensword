import io
import json

import pytest

import lensword_mcp.cli as cli
from lensword_mcp.cli import EXIT_BACKEND_ERROR, EXIT_CANCELLED, EXIT_OK, EXIT_REJECTED, main
from lensword_mcp.server import BackendError


def test_import_context_cli_is_offline_preview_only_and_supports_json():
    output = io.StringIO()
    code = main(
        ["import-context", "--stdin", "--source-ref", "terminal-1", "--json"],
        input_stream=io.StringIO("FastAPI FastAPI password=do-not-store asyncio"),
        output_stream=output,
    )

    payload = json.loads(output.getvalue())
    assert code == EXIT_OK
    assert payload["source_ref"] == "terminal-1"
    assert payload["writes_performed"] is False
    assert {item["term"] for item in payload["candidates"]} >= {"fastapi", "asyncio"}
    assert "do-not-store" not in {item["term"] for item in payload["candidates"]}


def test_import_context_cli_preserves_unicode_and_quoted_provenance():
    output = io.StringIO()
    code = main(
        ["import-context", "--stdin", "--source-ref", "terminal session 1", "--json"],
        input_stream=io.StringIO("café café naïve"),
        output_stream=output,
    )

    payload = json.loads(output.getvalue())
    assert code == EXIT_OK
    assert payload["source_ref"] == "terminal session 1"
    assert {item["term"] for item in payload["candidates"]} >= {"café", "naïve"}


def test_import_context_cli_refuses_huge_input_without_explicit_truncation():
    error = io.StringIO()
    code = main(
        ["import-context", "--stdin", "--max-characters", "4"],
        input_stream=io.StringIO("abcdef"),
        error_stream=error,
    )

    assert code == EXIT_REJECTED
    assert "allow-truncate" in error.getvalue()


def test_import_context_cli_can_explicitly_truncate_and_print_human_preview():
    output = io.StringIO()
    code = main(
        ["import-context", "--stdin", "--max-characters", "7", "--allow-truncate"],
        input_stream=io.StringIO("FastAPI FastAPI"),
        output_stream=output,
    )

    assert code == EXIT_OK
    assert "No writes performed" in output.getvalue()
    assert "fastapi" in output.getvalue()


def test_import_context_cli_returns_cancellation_exit_code():
    class CancelledInput:
        def read(self, _limit):
            raise KeyboardInterrupt

    error = io.StringIO()
    assert main(["import-context", "--stdin"], input_stream=CancelledInput(), error_stream=error) == EXIT_CANCELLED
    assert "cancelled" in error.getvalue()


def test_import_context_cli_rejects_a_symlinked_file(tmp_path):
    target = tmp_path / "real.txt"
    target.write_text("FastAPI asyncio", encoding="utf-8")
    link = tmp_path / "link.txt"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlinks are not permitted in this environment")

    error = io.StringIO()
    code = main(["import-context", "--file", str(link)], error_stream=error)
    assert code == EXIT_REJECTED
    assert "symlink" in error.getvalue()


def test_import_context_cli_rejects_a_directory_passed_as_a_file(tmp_path):
    error = io.StringIO()
    code = main(["import-context", "--file", str(tmp_path)], error_stream=error)
    assert code == EXIT_REJECTED


def test_import_context_cli_rejects_a_binary_non_utf8_file(tmp_path):
    path = tmp_path / "binary.bin"
    path.write_bytes(bytes(range(256)))

    error = io.StringIO()
    code = main(["import-context", "--file", str(path)], error_stream=error)
    assert code == EXIT_REJECTED
    assert "cannot read input" in error.getvalue()


def test_import_context_cli_supports_a_relative_path_with_traversal_components(tmp_path, monkeypatch):
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    target = tmp_path / "a" / "target.txt"
    target.write_text("FastAPI", encoding="utf-8")

    monkeypatch.chdir(nested)
    output = io.StringIO()
    code = main(["import-context", "--file", "../target.txt", "--json"], output_stream=output)
    assert code == EXIT_OK
    payload = json.loads(output.getvalue())
    assert {c["term"] for c in payload["candidates"]} == {"fastapi"}


def test_import_context_cli_ranks_with_known_terms_file(tmp_path):
    known = tmp_path / "known.txt"
    known.write_text("asyncio\n", encoding="utf-8")

    output = io.StringIO()
    code = main(
        ["import-context", "--stdin", "--source-ref", "t", "--known-terms-file", str(known), "--json"],
        input_stream=io.StringIO("asyncio asyncio fastapi fastapi"),
        output_stream=output,
    )
    assert code == EXIT_OK
    payload = json.loads(output.getvalue())
    by_term = {c["term"]: c for c in payload["candidates"]}
    assert by_term["asyncio"]["novel"] is False
    assert by_term["fastapi"]["novel"] is True


# --- add / explain / diagnose / review: backend-facing commands ------------


class FakeBackendClient:
    """Records every call so tests can assert on exactly what was sent,
    without any real network I/O."""

    instances: list["FakeBackendClient"] = []

    def __init__(self, api_url, token, requester, workspace, timeout=30.0):
        self.api_url, self.token, self.requester, self.workspace = api_url, token, requester, workspace
        self.invoke_calls: list[tuple[str, dict]] = []
        self.resource_calls: list[str] = []
        self.invoke_result: dict = {}
        self.resource_result = None
        self.raise_error: BackendError | None = None
        FakeBackendClient.instances.append(self)

    def invoke(self, name, arguments):
        self.invoke_calls.append((name, dict(arguments)))
        if self.raise_error is not None:
            raise self.raise_error
        return self.invoke_result

    def resource(self, uri):
        self.resource_calls.append(uri)
        if self.raise_error is not None:
            raise self.raise_error
        return self.resource_result


@pytest.fixture()
def fake_backend(monkeypatch):
    FakeBackendClient.instances = []
    monkeypatch.setattr(cli, "BackendClient", FakeBackendClient)
    monkeypatch.setenv("LENSWORD_API_URL", "http://localhost:9")
    monkeypatch.setenv("LENSWORD_TOKEN", "test-token")
    monkeypatch.setenv("LENSWORD_MCP_REQUESTER", "cli-test")
    monkeypatch.setenv("LENSWORD_MCP_WORKSPACE", "/workspace")
    yield FakeBackendClient
    FakeBackendClient.instances = []


def test_add_previews_and_requires_confirmation_before_calling_the_backend(fake_backend):
    output = io.StringIO()
    error = io.StringIO()
    code = main(
        ["add", "--group-id", "1", "--term", "correr", "--target-language", "Spanish"],
        input_stream=io.StringIO("n\n"),
        output_stream=output,
        error_stream=error,
    )
    assert code == EXIT_REJECTED
    assert "not confirmed" in error.getvalue()
    assert FakeBackendClient.instances == []  # backend never even constructed
    assert "About to add" in error.getvalue()
    assert output.getvalue() == ""  # stdout stays clean; preview/prompt chrome goes to stderr


def test_add_with_yes_flag_skips_the_prompt_and_persists(fake_backend, monkeypatch):
    # Pre-seed the response the fake backend will return once constructed.
    original_init = FakeBackendClient.__init__

    def seeded_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self.invoke_result = {"id": 42, "term": "correr", "mnemonic": "a private note"}

    monkeypatch.setattr(FakeBackendClient, "__init__", seeded_init)

    output = io.StringIO()
    code = main(
        ["add", "--group-id", "1", "--term", "correr", "--target-language", "Spanish",
         "--translation", "to run", "--yes", "--json"],
        output_stream=output,
    )
    assert code == EXIT_OK
    payload = json.loads(output.getvalue())
    assert payload == {"id": 42, "term": "correr"}  # mnemonic redacted
    assert "mnemonic" not in output.getvalue()
    name, sent = FakeBackendClient.instances[0].invoke_calls[0]
    assert name == "lensword_add_word"
    assert sent["term"] == "correr" and sent["translations"] == ["to run"]
    assert "request_id" in sent


def test_add_refuses_an_oversized_term_before_any_backend_contact(fake_backend):
    huge_term = "x" * 10_000
    error = io.StringIO()
    code = main(["add", "--group-id", "1", "--term", huge_term, "--target-language", "Spanish", "--yes"], error_stream=error)
    assert code == EXIT_REJECTED
    assert FakeBackendClient.instances == []


def test_add_reads_the_term_from_stdin_when_not_given_as_a_flag(fake_backend, monkeypatch):
    original_init = FakeBackendClient.__init__

    def seeded_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self.invoke_result = {"id": 1, "term": "café"}

    monkeypatch.setattr(FakeBackendClient, "__init__", seeded_init)

    output = io.StringIO()
    code = main(
        ["add", "--group-id", "1", "--target-language", "Spanish", "--yes", "--json"],
        input_stream=io.StringIO("café\n"),
        output_stream=output,
    )
    assert code == EXIT_OK
    assert json.loads(output.getvalue())["term"] == "café"


def test_add_without_backend_env_vars_fails_cleanly(monkeypatch):
    for name in ("LENSWORD_API_URL", "LENSWORD_TOKEN", "LENSWORD_MCP_REQUESTER", "LENSWORD_MCP_WORKSPACE"):
        monkeypatch.delenv(name, raising=False)
    error = io.StringIO()
    code = main(["add", "--group-id", "1", "--term", "correr", "--target-language", "Spanish", "--yes"], error_stream=error)
    assert code == EXIT_BACKEND_ERROR
    assert "LENSWORD_API_URL" in error.getvalue()


def test_add_surfaces_a_backend_error_with_the_dedicated_exit_code(fake_backend, monkeypatch):
    original_init = FakeBackendClient.__init__

    def seeded_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self.raise_error = BackendError(422, "term already exists")

    monkeypatch.setattr(FakeBackendClient, "__init__", seeded_init)
    error = io.StringIO()
    code = main(["add", "--group-id", "1", "--term", "correr", "--target-language", "Spanish", "--yes"], error_stream=error)
    assert code == EXIT_BACKEND_ERROR
    assert "term already exists" in error.getvalue()


def test_explain_calls_the_learner_aware_tool_and_prints_the_explanation(fake_backend, monkeypatch):
    original_init = FakeBackendClient.__init__

    def seeded_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self.invoke_result = {"word_id": 7, "term": "hogar", "explanation": "hogar is currently unstudied.", "mnemonic": "secret"}

    monkeypatch.setattr(FakeBackendClient, "__init__", seeded_init)
    output = io.StringIO()
    code = main(["explain", "--word-id", "7"], output_stream=output)
    assert code == EXIT_OK
    assert "hogar is currently unstudied." in output.getvalue()
    assert "secret" not in output.getvalue()
    assert FakeBackendClient.instances[0].invoke_calls[0] == ("lensword_explain_for_user", {"word_id": 7})


def test_diagnose_never_calls_a_write_tool_and_shows_no_diagnosis_gracefully(fake_backend, monkeypatch):
    original_init = FakeBackendClient.__init__

    def seeded_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self.resource_result = None

    monkeypatch.setattr(FakeBackendClient, "__init__", seeded_init)
    output = io.StringIO()
    code = main(["diagnose", "--word-id", "9"], output_stream=output)
    assert code == EXIT_OK
    assert "No diagnosis" in output.getvalue()
    assert FakeBackendClient.instances[0].resource_calls == ["lensword://words/9/diagnosis"]
    assert FakeBackendClient.instances[0].invoke_calls == []  # read-only: never invokes a tool


def test_diagnose_prints_an_existing_diagnosis(fake_backend, monkeypatch):
    original_init = FakeBackendClient.__init__

    def seeded_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self.resource_result = {"word_id": 9, "outcome": "exact_confusion", "confidence": 0.7, "sample_size": 4}

    monkeypatch.setattr(FakeBackendClient, "__init__", seeded_init)
    output = io.StringIO()
    code = main(["diagnose", "--word-id", "9", "--json"], output_stream=output)
    assert code == EXIT_OK
    assert json.loads(output.getvalue())["outcome"] == "exact_confusion"


def test_review_requires_confirmation_and_then_starts_a_session(fake_backend, monkeypatch):
    original_init = FakeBackendClient.__init__

    def seeded_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self.invoke_result = {"session_id": 3, "words": [{"term": "hogar", "mnemonic": "private"}]}

    monkeypatch.setattr(FakeBackendClient, "__init__", seeded_init)

    output = io.StringIO()
    code = main(["review", "--group-id", "1"], input_stream=io.StringIO("y\n"), output_stream=output)
    assert code == EXIT_OK
    assert "Session 3" in output.getvalue()
    assert "private" not in output.getvalue()
    name, sent = FakeBackendClient.instances[0].invoke_calls[0]
    assert name == "lensword_create_study_session" and sent["group_id"] == 1


def test_review_declined_never_contacts_the_backend(fake_backend):
    error = io.StringIO()
    code = main(["review"], input_stream=io.StringIO("no\n"), error_stream=error)
    assert code == EXIT_REJECTED
    assert FakeBackendClient.instances == []


def test_add_confirmation_prompt_can_be_cancelled(fake_backend):
    class CancelledInput:
        def readline(self):
            raise KeyboardInterrupt

    error = io.StringIO()
    code = main(
        ["add", "--group-id", "1", "--term", "correr", "--target-language", "Spanish"],
        input_stream=CancelledInput(),
        error_stream=error,
    )
    assert code == EXIT_CANCELLED
    assert "cancelled" in error.getvalue()
    assert FakeBackendClient.instances == []


def test_unknown_command_returns_usage_exit_code():
    error = io.StringIO()
    with pytest.raises(SystemExit):
        main(["not-a-real-command"], error_stream=error)


def test_add_handles_unicode_and_embedded_whitespace_in_the_term(fake_backend, monkeypatch):
    original_init = FakeBackendClient.__init__

    def seeded_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self.invoke_result = {"id": 5, "term": "café con leche"}

    monkeypatch.setattr(FakeBackendClient, "__init__", seeded_init)
    output = io.StringIO()
    code = main(
        ["add", "--group-id", "1", "--term", "café con leche", "--target-language", "Spanish", "--yes", "--json"],
        output_stream=output,
    )
    assert code == EXIT_OK
    assert json.loads(output.getvalue())["term"] == "café con leche"
    _, sent = FakeBackendClient.instances[0].invoke_calls[0]
    assert sent["term"] == "café con leche"
