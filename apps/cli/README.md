# LensWord Local CLI

`lensword` is LensWord's local developer-workflow CLI: an offline context
preview command plus a small set of account workflows that go through the
same authenticated, policy-gated HTTP boundary the MCP server uses.

Split out of `apps/mcp` into its own package (issue #311) because the two
were always independent surfaces sharing one piece of code
(`BackendClient`) rather than one product with two entry points.
`apps/mcp`'s `lensword-mcp` server now depends on this package for that
shared client rather than defining its own copy.

For the full setup walkthrough (permissions, scopes, privacy/export/deletion
behavior), see
[`docs/mcp-companion-guide.md`](../../docs/reference/mcp-companion-guide.md)
in the repository root. This README only covers running the CLI itself.

## Install (source, for now)

```bash
pip install -e apps/cli
```

Not yet published to PyPI — see `docs/internal/pypi-publishing.md` for the
publish workflow that exists but has not been triggered yet.

## Preview local developer context

`import-context` is offline-only: it never contacts the backend, never
writes anything, and redacts credentials, private keys, and JWTs before any
candidate is shown.

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
line).

## Other CLI workflows

`add`, `explain`, `diagnose`, and `review` do contact the backend (they read
or write your real account), through the same policy-gated
`/api/v1/mcp/invoke` boundary the MCP server uses. Set the same four
`LENSWORD_*` environment variables first (`LENSWORD_API_URL`,
`LENSWORD_TOKEN`, `LENSWORD_MCP_REQUESTER`, `LENSWORD_MCP_WORKSPACE`).

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
