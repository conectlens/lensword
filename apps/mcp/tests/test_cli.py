import io
import json

from lensword_mcp.cli import EXIT_CANCELLED, EXIT_OK, EXIT_REJECTED, main


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
