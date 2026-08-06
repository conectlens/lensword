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
