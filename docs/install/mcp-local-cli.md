---
title: MCP Server & Local CLI
description: Connect an MCP-capable AI client, or preview/import developer context locally and offline.
---

The `apps/mcp` package is two things: an MCP server (`lensword-mcp`, stdio by
default) for AI clients like Claude, Codex, or Cursor, and a local CLI
(`lensword`) with a bounded, offline context-preview command plus a few
commands that act on your account through the same policy-gated boundary.
Neither is published to PyPI yet — install is source-only, and there's no CI
coverage for this package. The content below is included directly from the
package's own README (`apps/mcp/README.md`), so it can't drift from the
source of truth.

<!--@include: ../../apps/mcp/README.md-->

## Remote transport

The MCP server also supports Streamable HTTP, off by default and gated on
both the server and the backend. See [MCP remote transport](/reference/mcp-remote-transport)
for what's on by default, what TLS requirements apply, and what has and
hasn't been tested end to end.

## Related

- [Choose your surface](/learn/choose-a-surface) for how this compares to the other ways to use LensWord.
- [docs/internal/repo-audit.md](https://github.com/conectlens/lensword/blob/development/docs/internal/repo-audit.md) for the evidence behind this surface's release status.
