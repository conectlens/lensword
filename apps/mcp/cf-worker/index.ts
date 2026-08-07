// Minimal Worker fronting the MCP Container (see ../wrangler.toml). Same
// pattern as apps/backend/cf-worker/index.ts — see that file's comment on
// envVars vs the README's stale `env` property name.
import { Container, getContainer } from "@cloudflare/containers";

interface Env {
  MCP_CONTAINER: DurableObjectNamespace<MCPContainer>;
  // The MCP server's own double opt-in for the remote transport (server.py's
  // main()) — LENSWORD_API_URL and LENSWORD_MCP_WORKSPACE are not secret
  // (a base URL and a workspace label), set as [vars] in wrangler.toml.
  // LENSWORD_TOKEN, if this deployment needs one, is a real secret — set
  // with `wrangler secret put LENSWORD_TOKEN` and add it below if used.
  LENSWORD_API_URL: string;
  LENSWORD_MCP_WORKSPACE: string;
  LENSWORD_MCP_ALLOWED_ORIGINS?: string;
}

export class MCPContainer extends Container<Env> {
  defaultPort = 8765; // matches EXPOSE 8765 in ../Dockerfile
  sleepAfter = "10m";

  constructor(ctx: DurableObjectState<Env>, env: Env) {
    super(ctx, env);
    this.envVars = {
      LENSWORD_MCP_TRANSPORT: "http",
      LENSWORD_MCP_REMOTE_ENABLED: "1",
      LENSWORD_API_URL: env.LENSWORD_API_URL,
      LENSWORD_MCP_WORKSPACE: env.LENSWORD_MCP_WORKSPACE,
      LENSWORD_MCP_ALLOWED_ORIGINS: env.LENSWORD_MCP_ALLOWED_ORIGINS ?? "",
    };
  }
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const container = getContainer(env.MCP_CONTAINER);
    return container.fetch(request);
  },
};
