"""Offline developer-context CLI (issue #188).

The command is intentionally preview-only.  It reads a bounded local input,
passes it through the same secret-redacting extractor used by the MCP tests,
and prints candidates with provenance.  It never contacts the backend and
never writes cards; a later persistence command must require an explicit
confirmation boundary of its own.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import TextIO, Sequence

from .context_import import ContextImportPolicy, ContextImportRejected, preview_context


EXIT_OK = 0
EXIT_USAGE = 2
EXIT_REJECTED = 3
EXIT_CANCELLED = 130


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lensword", description="Bounded offline LensWord workflows")
    commands = parser.add_subparsers(dest="command", required=True)

    import_context = commands.add_parser(
        "import-context",
        help="preview vocabulary candidates from a local file or stdin",
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
        "--json",
        action="store_true",
        dest="json_output",
        help="emit machine-readable JSON",
    )
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


def _run_import_context(args: argparse.Namespace, input_stream: TextIO, output_stream: TextIO) -> int:
    if args.max_characters < 1 or args.max_candidates < 1 or args.max_term_length < 2:
        raise ContextImportRejected("context limits must be positive")
    text, source_kind, source_ref = _read_input(args, input_stream)
    oversized = len(text) > args.max_characters
    if oversized and not args.allow_truncate:
        raise ContextImportRejected(
            f"context exceeds --max-characters ({args.max_characters}); pass --allow-truncate to continue"
        )
    preview = preview_context(
        text,
        source_kind=source_kind,
        source_ref=source_ref,
        policy=ContextImportPolicy(
            max_characters=args.max_characters,
            max_candidates=args.max_candidates,
            max_term_length=args.max_term_length,
        ),
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
            output_stream.write(f"- {candidate.term} ({candidate.occurrences})\n")
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
