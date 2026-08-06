# LensWord MCP Server

This package exposes LensWord as a Model Context Protocol server over stdio.
It proxies tool discovery and invocation to the authenticated LensWord HTTP
API, so contract validation, tenant isolation, grants, audit events and
idempotency remain owned by the backend.

## Run

```bash
export LENSWORD_API_URL=http://localhost:18420
export LENSWORD_TOKEN='your LensWord access token'
export LENSWORD_MCP_REQUESTER='claude-desktop'
export LENSWORD_MCP_WORKSPACE='/approved'
python3 -m lensword_mcp
```

Configure the command and environment in an MCP client that supports stdio.
The server writes protocol messages only to stdout; diagnostics go to stderr.

## Preview local developer context

The offline CLI previews bounded vocabulary candidates from a file or stdin.
It redacts credentials, private keys, and JWTs through the shared extractor,
preserves source provenance, and performs no writes or network requests.

```bash
lensword import-context --file README.md --json
cat terminal-output.txt | lensword import-context --stdin --source-ref terminal-session
```

Inputs larger than 50,000 characters are refused by default. Use
`--allow-truncate` only when truncating the preview is acceptable. A future
persistence command must add an explicit confirmation step; this command does
not create cards.
