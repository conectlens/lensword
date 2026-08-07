# Runs the MCP server's remote Streamable HTTP transport (issue #196
# TODO 0) for deployment as a Cloudflare Container — the stdio transport
# (this package's default, and the only transport most installs ever use)
# has no meaning outside a local process pair, so this image only makes
# sense with LENSWORD_MCP_TRANSPORT=http set at runtime.
FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml ./
COPY lensword_mcp ./lensword_mcp
RUN pip install --no-cache-dir .

# 0.0.0.0, not the package's own 127.0.0.1 default — a container's loopback
# interface isn't reachable from outside it. Every other runtime variable
# (LENSWORD_MCP_TRANSPORT, LENSWORD_MCP_REMOTE_ENABLED, LENSWORD_API_URL,
# LENSWORD_MCP_WORKSPACE, LENSWORD_MCP_ALLOWED_ORIGINS) is deliberately not
# set here — see server.py's main(): both LENSWORD_MCP_TRANSPORT=http and
# LENSWORD_MCP_REMOTE_ENABLED=1 must be set explicitly by whatever deploys
# this image, so a copy of this Dockerfile built and run without that
# deployment's env config fails closed (exit 2) instead of silently
# listening.
ENV LENSWORD_MCP_HTTP_HOST=0.0.0.0
ENV LENSWORD_MCP_HTTP_PORT=8765

EXPOSE 8765
CMD ["lensword-mcp"]
