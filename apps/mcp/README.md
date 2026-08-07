# LensWord MCP Server

This package exposes LensWord as a Model Context Protocol server over stdio
(the default) or, opt-in only, remote Streamable HTTP. It proxies tool
discovery and invocation to the authenticated LensWord HTTP API, so contract
validation, tenant isolation, grants, audit events and idempotency remain
owned by the backend.

For the full setup walkthrough (local stdio, remote OAuth, permissions and
scopes, daily session examples, privacy/export/deletion behavior, what "AI
Companion" claims are actually verified vs. not), see
[`docs/mcp-companion-guide.md`](../../docs/reference/mcp-companion-guide.md) in the
repository root. This README only covers running the process itself.

## Run (local stdio — the default and only transport most installs need)

```bash
export LENSWORD_API_URL=http://localhost:18420
export LENSWORD_TOKEN='your LensWord access token'
export LENSWORD_MCP_WORKSPACE='/approved'
python3 -m lensword_mcp
```

Configure the command and environment in an MCP client that supports stdio.
The server writes protocol messages only to stdout; diagnostics go to stderr.

Caller identity is derived by the backend from `LENSWORD_TOKEN` itself
(`app/api/mcp_auth.py`, issue #196) — there is no `LENSWORD_MCP_REQUESTER`
variable to set; an earlier version of this document described one, but the
backend stopped trusting a client-supplied requester string once issue #196
closed that spoofing gap, and this process was updated to match at the same
time. If a runbook or client config you're following still sets that
variable, it is harmless (the server simply never reads it) but does nothing.

## Run (remote Streamable HTTP — opt-in, off by default)

See [`docs/mcp-remote-transport.md`](../../docs/reference/mcp-remote-transport.md) for
the full remote OAuth + Streamable HTTP setup, TLS requirements, and an
honest list of what is and is not implemented for that transport.

## Preview local developer context

The offline CLI previews bounded vocabulary candidates from a file or stdin.
It redacts credentials, private keys, and JWTs through the shared extractor,
preserves source provenance, and performs no writes or network requests.

```bash
lensword import-context --file README.md --json
cat terminal-output.txt | lensword import-context --stdin --source-ref terminal-session
```

Inputs larger than 50,000 characters are refused by default. Use
`--allow-truncate` only when truncating the preview is acceptable. Candidates
are ranked by recurrence, then by a bounded, offline technical-relevance
heuristic (does the term look like an identifier — CamelCase, snake_case,
carries a digit, or a dotted/hyphenated path — rather than plain prose), then
by novelty if you supply `--known-terms-file` (one already-known term per
line). This command never writes anything and never contacts the backend.

## Other CLI workflows

`add`, `explain`, `diagnose`, and `review` do contact the backend (they read
or write your real account), through the same policy-gated
`/api/v1/mcp/invoke` boundary the stdio server above uses. Set the same four
`LENSWORD_*` environment variables first.

```bash
# Preview, then confirm interactively (or pass --yes to skip the prompt).
lensword add --group-id 3 --term asyncio --target-language English --translation "async I/O"

# Read-only: a deterministic, offline-computed explanation of one owned word.
lensword explain --word-id 42 --json

# Read-only: shows the most recent diagnosis already on record. Never
# triggers a new one — diagnosis is only ever produced by a real review
# answer, never on demand from this command.
lensword diagnose --word-id 42

# Preview, then confirm, then start a review session.
lensword review --group-id 3 --limit 10
```

Every write-shaped command previews what it is about to do and requires an
explicit confirmation (interactive `y`/`yes`, or `--yes`) before persisting —
nothing is written silently. Word-shaped responses never print `mnemonic` or
other private fields, even if the backend response includes them.
