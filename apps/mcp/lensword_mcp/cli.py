"""LensWord developer-workflow CLI (issue #188).

`import-context` is the original, fully offline preview command: it never
contacts the backend. The four commands added here — `add`, `explain`,
`diagnose`, `review` — necessarily do contact it (they read or write a
learner's real account), through the same `/api/v1/mcp/invoke` boundary
`lensword-mcp`'s stdio server already uses (`BackendClient` in `server.py`),
so every one of them is still policy-gated, grant-checked, and audited by
the backend exactly as an AI agent's MCP call would be — this CLI is not a
side door around that boundary.

Every command that would write something (`add`, `review`) previews what it
is about to do and requires an explicit confirmation — either interactively
or via `--yes` — before persisting, the same "preview, then confirm" shape
`import-context` already established. `explain` and `diagnose` are
read-only and need no confirmation. `diagnose` deliberately only *shows*
the most recent diagnosis already on record; it never triggers a new one —
issue #188 TODO 3's "an agent cannot mark a word mastered or create a
diagnosis directly" applies equally here, and no backend endpoint exists to
force one outside of a real review answer, so this command does not invent
one.

Word-shaped responses are redacted before they are ever written to stdout:
`mnemonic` never appears here, even though the backend's own
`word_to_response` mapper currently includes it (issue #192's separate,
already-tracked gap) — this CLI is part of the same least-privilege
boundary issue #188 TODO 0 describes and must not re-expose that field just
because the transport happens to be a terminal instead of an MCP tool call.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any, TextIO, Sequence

from .context_import import ContextImportPolicy, ContextImportRejected, preview_context
from .server import BackendClient, BackendError


EXIT_OK = 0
EXIT_USAGE = 2
EXIT_REJECTED = 3
EXIT_BACKEND_ERROR = 4
EXIT_CANCELLED = 130

MAX_TERM_LENGTH = 255
MAX_TRANSLATIONS = 20
MAX_TRANSLATION_LENGTH = 255

# Fields this CLI never prints, regardless of what the backend response
# contains (see module docstring). Kept as a set so it is trivial to widen
# without hunting through every print site.
_PRIVATE_RESPONSE_FIELDS = frozenset({"mnemonic"})

_ENV_VARS = ("LENSWORD_API_URL", "LENSWORD_TOKEN", "LENSWORD_MCP_REQUESTER", "LENSWORD_MCP_WORKSPACE")


def _redact(value: Any) -> Any:
    """Recursively drop private fields from a backend response before it is
    ever written to stdout/stderr."""
    if isinstance(value, dict):
        return {key: _redact(item) for key, item in value.items() if key not in _PRIVATE_RESPONSE_FIELDS}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lensword", description="Bounded offline/online LensWord workflows")
    commands = parser.add_subparsers(dest="command", required=True)

    import_context = commands.add_parser(
        "import-context",
        help="preview vocabulary candidates from a local file or stdin (offline, never contacts the backend)",
    )
    source = import_context.add_mutually_exclusive_group(required=True)
    source.add_argument("--file", type=Path, help="read one local UTF-8 text file")
    source.add_argument("--stdin", action="store_true", help="read UTF-8 text from stdin")
    import_context.add_argument(
        "--source-kind",
        default=None,
        help="provenance kind (defaults to file or stdin)",
    )
    import_context.add_argument(
        "--source-ref",
        default=None,
        help="bounded provenance reference (defaults to the file path or stdin)",
    )
    import_context.add_argument("--max-characters", type=int, default=50_000)
    import_context.add_argument("--max-candidates", type=int, default=50)
    import_context.add_argument("--max-term-length", type=int, default=64)
    import_context.add_argument(
        "--allow-truncate",
        action="store_true",
        help="allow input beyond --max-characters to be previewed after truncation",
    )
    import_context.add_argument(
        "--known-terms-file",
        type=Path,
        default=None,
        help="optional local file of already-known terms, one per line, used for the novelty ranking signal",
    )
    import_context.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="emit machine-readable JSON",
    )

    add = commands.add_parser("add", help="preview and, once confirmed, add one word to a group")
    add.add_argument("--group-id", type=int, required=True)
    add.add_argument("--term", default=None, help="the word to add; read from stdin's first line if omitted")
    add.add_argument("--target-language", required=True)
    add.add_argument("--translation", dest="translations", action="append", default=[])
    add.add_argument("--yes", action="store_true", help="skip the interactive confirmation prompt")
    add.add_argument("--json", action="store_true", dest="json_output")

    explain = commands.add_parser("explain", help="show a deterministic explanation for one owned word")
    explain.add_argument("--word-id", type=int, required=True)
    explain.add_argument("--json", action="store_true", dest="json_output")

    diagnose = commands.add_parser(
        "diagnose", help="show the most recent diagnosis already on record for one owned word (never creates one)"
    )
    diagnose.add_argument("--word-id", type=int, required=True)
    diagnose.add_argument("--json", action="store_true", dest="json_output")

    review = commands.add_parser("review", help="preview and, once confirmed, start a review session")
    review.add_argument("--group-id", type=int, default=None)
    review.add_argument("--limit", type=int, default=20)
    review.add_argument("--yes", action="store_true", help="skip the interactive confirmation prompt")
    review.add_argument("--json", action="store_true", dest="json_output")

    return parser


def _read_input(args: argparse.Namespace, input_stream: TextIO) -> tuple[str, str, str]:
    if args.file is not None:
        path: Path = args.file
        if path.is_symlink() or not path.is_file():
            raise ContextImportRejected("--file must name a regular, non-symlink file")
        source_kind = args.source_kind or "file"
        source_ref = args.source_ref or str(path)
        # Read only one character beyond the policy bound. This detects an
        # oversized file without loading an unbounded repository or log.
        with path.open("r", encoding="utf-8") as handle:
            text = handle.read(args.max_characters + 1)
        return text, source_kind, source_ref

    source_kind = args.source_kind or "stdin"
    source_ref = args.source_ref or "stdin"
    text = input_stream.read(args.max_characters + 1)
    return text, source_kind, source_ref


def _read_known_terms(path: Path | None) -> frozenset[str] | None:
    if path is None:
        return None
    if path.is_symlink() or not path.is_file():
        raise ContextImportRejected("--known-terms-file must name a regular, non-symlink file")
    # Bounded the same way --file is: one file, read up to a fixed cap
    # rather than an unbounded vocabulary dump.
    with path.open("r", encoding="utf-8") as handle:
        lines = handle.read(1_000_000).splitlines()
    return frozenset(line.strip().casefold() for line in lines if line.strip())


def _run_import_context(args: argparse.Namespace, input_stream: TextIO, output_stream: TextIO) -> int:
    if args.max_characters < 1 or args.max_candidates < 1 or args.max_term_length < 2:
        raise ContextImportRejected("context limits must be positive")
    text, source_kind, source_ref = _read_input(args, input_stream)
    oversized = len(text) > args.max_characters
    if oversized and not args.allow_truncate:
        raise ContextImportRejected(
            f"context exceeds --max-characters ({args.max_characters}); pass --allow-truncate to continue"
        )
    known_terms = _read_known_terms(args.known_terms_file)
    preview = preview_context(
        text,
        source_kind=source_kind,
        source_ref=source_ref,
        policy=ContextImportPolicy(
            max_characters=args.max_characters,
            max_candidates=args.max_candidates,
            max_term_length=args.max_term_length,
        ),
        known_terms=known_terms,
    )
    if args.json_output:
        output_stream.write(
            json.dumps(asdict(preview), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        )
    else:
        output_stream.write(f"Preview from {preview.source_kind}:{preview.source_ref}\n")
        output_stream.write("No writes performed; explicit confirmation is required before persistence.\n")
        if not preview.candidates:
            output_stream.write("No candidates found.\n")
        for candidate in preview.candidates:
            flags = []
            if candidate.technical_relevance:
                flags.append("technical")
            if candidate.novel:
                flags.append("novel")
            suffix = f" [{', '.join(flags)}]" if flags else ""
            output_stream.write(f"- {candidate.term} ({candidate.occurrences}){suffix}\n")
    return EXIT_OK


def _backend_from_env(error_stream: TextIO) -> BackendClient | None:
    values = {name: os.environ.get(name) for name in _ENV_VARS}
    missing = [name for name, value in values.items() if not value]
    if missing:
        error_stream.write(
            f"lensword: missing environment variables: {', '.join(missing)}\n"
            "lensword: set them to connect this command to your LensWord backend "
            "(see apps/mcp/README.md)\n"
        )
        return None
    return BackendClient(values["LENSWORD_API_URL"], values["LENSWORD_TOKEN"], values["LENSWORD_MCP_REQUESTER"], values["LENSWORD_MCP_WORKSPACE"])


def _confirm(prompt: str, *, assume_yes: bool, input_stream: TextIO, prompt_stream: TextIO) -> bool:
    if assume_yes:
        return True
    # The prompt is interactive chrome, not the command's result — it goes
    # to stderr so a caller piping/parsing stdout (especially with --json)
    # never has to see or skip past it.
    prompt_stream.write(f"{prompt} [y/N]: ")
    prompt_stream.flush()
    answer = input_stream.readline()
    return answer.strip().casefold() in {"y", "yes"}


def _print_result(result: dict, *, json_output: bool, output_stream: TextIO, human_lines: list[str]) -> None:
    redacted = _redact(result)
    if json_output:
        output_stream.write(json.dumps(redacted, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
        return
    for line in human_lines:
        output_stream.write(line + "\n")


def _run_add(args: argparse.Namespace, input_stream: TextIO, output_stream: TextIO, error_stream: TextIO) -> int:
    term = args.term
    if term is None:
        term = input_stream.readline().rstrip("\n")
    term = term.strip()
    if not term:
        raise ContextImportRejected("a non-empty --term (or stdin line) is required")
    if len(term) > MAX_TERM_LENGTH:
        raise ContextImportRejected(f"--term exceeds the maximum length of {MAX_TERM_LENGTH} characters")
    translations = [value.strip() for value in args.translations if value.strip()]
    if len(translations) > MAX_TRANSLATIONS:
        raise ContextImportRejected(f"at most {MAX_TRANSLATIONS} --translation values are allowed")
    for value in translations:
        if len(value) > MAX_TRANSLATION_LENGTH:
            raise ContextImportRejected(f"a --translation value exceeds {MAX_TRANSLATION_LENGTH} characters")

    # Preview and confirmation prompt go to stderr, never stdout — stdout is
    # reserved for this command's eventual result (see _confirm's docstring
    # comment above for why, especially with --json).
    error_stream.write(f"About to add '{term}' ({args.target_language}) to group {args.group_id}.\n")
    if translations:
        error_stream.write(f"Translations: {', '.join(translations)}\n")
    error_stream.write("No writes performed yet; explicit confirmation is required before persistence.\n")
    if not _confirm("Add this word?", assume_yes=args.yes, input_stream=input_stream, prompt_stream=error_stream):
        error_stream.write("lensword: not confirmed; nothing was added\n")
        return EXIT_REJECTED

    backend = _backend_from_env(error_stream)
    if backend is None:
        return EXIT_BACKEND_ERROR
    try:
        result = backend.invoke(
            "lensword.add_word",
            {
                "group_id": args.group_id,
                "term": term,
                "target_language": args.target_language,
                "translations": translations,
                "request_id": str(uuid.uuid4()),
            },
        )
    except BackendError as exc:
        error_stream.write(f"lensword: {exc.detail}\n")
        return EXIT_BACKEND_ERROR
    _print_result(
        result, json_output=args.json_output, output_stream=output_stream,
        human_lines=[f"Added word {result.get('id')}: {result.get('term')}"],
    )
    return EXIT_OK


def _run_explain(args: argparse.Namespace, output_stream: TextIO, error_stream: TextIO) -> int:
    backend = _backend_from_env(error_stream)
    if backend is None:
        return EXIT_BACKEND_ERROR
    try:
        result = backend.invoke("lensword.explain_for_user", {"word_id": args.word_id})
    except BackendError as exc:
        error_stream.write(f"lensword: {exc.detail}\n")
        return EXIT_BACKEND_ERROR
    _print_result(
        result, json_output=args.json_output, output_stream=output_stream,
        human_lines=[str(result.get("explanation", ""))],
    )
    return EXIT_OK


def _run_diagnose(args: argparse.Namespace, output_stream: TextIO, error_stream: TextIO) -> int:
    backend = _backend_from_env(error_stream)
    if backend is None:
        return EXIT_BACKEND_ERROR
    try:
        result = backend.resource(f"lensword://words/{args.word_id}/diagnosis")
    except BackendError as exc:
        error_stream.write(f"lensword: {exc.detail}\n")
        return EXIT_BACKEND_ERROR
    if result is None:
        human_lines = [f"No diagnosis has been recorded yet for word {args.word_id}."]
    else:
        human_lines = [
            f"Word {args.word_id}: outcome={result.get('outcome')} "
            f"confidence={result.get('confidence')} sample_size={result.get('sample_size')}"
        ]
    _print_result(result or {}, json_output=args.json_output, output_stream=output_stream, human_lines=human_lines)
    return EXIT_OK


def _run_review(args: argparse.Namespace, input_stream: TextIO, output_stream: TextIO, error_stream: TextIO) -> int:
    scope = f"group {args.group_id}" if args.group_id is not None else "all due words"
    error_stream.write(f"About to start a review session for {scope} (limit {args.limit}).\n")
    error_stream.write("No writes performed yet; explicit confirmation is required before persistence.\n")
    if not _confirm("Start this session?", assume_yes=args.yes, input_stream=input_stream, prompt_stream=error_stream):
        error_stream.write("lensword: not confirmed; no session was started\n")
        return EXIT_REJECTED

    backend = _backend_from_env(error_stream)
    if backend is None:
        return EXIT_BACKEND_ERROR
    payload: dict[str, Any] = {"limit": args.limit, "request_id": str(uuid.uuid4())}
    if args.group_id is not None:
        payload["group_id"] = args.group_id
    try:
        result = backend.invoke("lensword.create_study_session", payload)
    except BackendError as exc:
        error_stream.write(f"lensword: {exc.detail}\n")
        return EXIT_BACKEND_ERROR
    words = result.get("words", []) if isinstance(result, dict) else []
    _print_result(
        result, json_output=args.json_output, output_stream=output_stream,
        human_lines=[f"Session {result.get('session_id')}: {len(words)} word(s) due"]
        + [f"- {word.get('term')}" for word in words],
    )
    return EXIT_OK


def main(
    argv: Sequence[str] | None = None,
    *,
    input_stream: TextIO | None = None,
    output_stream: TextIO | None = None,
    error_stream: TextIO | None = None,
) -> int:
    input_stream = input_stream or sys.stdin
    output_stream = output_stream or sys.stdout
    error_stream = error_stream or sys.stderr
    parser = _parser()
    try:
        args = parser.parse_args(argv)
        if args.command == "import-context":
            return _run_import_context(args, input_stream, output_stream)
        if args.command == "add":
            return _run_add(args, input_stream, output_stream, error_stream)
        if args.command == "explain":
            return _run_explain(args, output_stream, error_stream)
        if args.command == "diagnose":
            return _run_diagnose(args, output_stream, error_stream)
        if args.command == "review":
            return _run_review(args, input_stream, output_stream, error_stream)
    except ContextImportRejected as exc:
        error_stream.write(f"lensword: {exc}\n")
        return EXIT_REJECTED
    except (OSError, UnicodeError) as exc:
        error_stream.write(f"lensword: cannot read input: {exc}\n")
        return EXIT_REJECTED
    except KeyboardInterrupt:
        error_stream.write("lensword: cancelled\n")
        return EXIT_CANCELLED
    return EXIT_USAGE


if __name__ == "__main__":
    raise SystemExit(main())
