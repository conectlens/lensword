# LensWord MCP Server

This package exposes LensWord as a Model Context Protocol server over stdio
(the default) or, opt-in only, remote Streamable HTTP. It proxies tool
discovery and invocation to the authenticated LensWord HTTP API, so contract
validation, tenant isolation, grants, audit events and idempotency remain
owned by the backend.

The Local CLI (`lensword` — `import-context`, `add`, `explain`, `diagnose`,
`review`) used to be a second entry point of this same package. It now lives
in its own package, [`apps/cli`](../cli/README.md) (issue #311) — this
package depends on it for the shared `BackendClient`/`BackendError` HTTP
client, but no longer ships the CLI itself.

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

## Installing from source

Neither package is on PyPI yet, and this package now depends on
`lensword-cli` for its shared `BackendClient`/`BackendError` HTTP client, so
install both from source together:

```bash
pip install -e apps/cli -e apps/mcp
```

## The Local CLI

`import-context`, `add`, `explain`, `diagnose`, and `review` — the `lensword`
command — live in [`apps/cli`](../cli/README.md), a separate package. See
that package's README for usage.
