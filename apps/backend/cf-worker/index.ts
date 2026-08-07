// Minimal Worker fronting the backend Container (see ../wrangler.toml).
// Cloudflare Containers are addressed through a Durable Object binding —
// this is the whole Worker: get the (singleton, per max_instances = 1)
// container instance and forward the request to it unchanged.
//
// Verified against @cloudflare/containers@0.3.7's actual type
// definitions, not just its README (which still documents an `env`
// property — the real, current one is `envVars`; see package/dist/lib/container.d.ts).
import { Container, getContainer } from "@cloudflare/containers";

interface Env {
  BACKEND_CONTAINER: DurableObjectNamespace<BackendContainer>;
  // Secrets — set with `wrangler secret put <NAME>`, never committed.
  // See docs/internal/cloudflare-deployment.md.
  DATABASE_URL: string;
  SECRET_KEY: string;
  // Plain (non-secret) vars — set in [vars] below or via `wrangler secret put`
  // if you'd rather not have them in wrangler.toml at all.
  CORS_ORIGINS?: string;
}

export class BackendContainer extends Container<Env> {
  defaultPort = 8000; // matches EXPOSE 8000 in ../Dockerfile
  sleepAfter = "10m"; // scale-to-zero when idle; first request after sleep pays cold-start

  constructor(ctx: DurableObjectState<Env>, env: Env) {
    super(ctx, env);
    // Everything ../.env.example documents beyond its committed defaults —
    // DB_POOL_SIZE etc. are fine as Dockerfile-level defaults; these two
    // are the ones that must come from real deployment secrets.
    this.envVars = {
      DATABASE_URL: env.DATABASE_URL,
      SECRET_KEY: env.SECRET_KEY,
      CORS_ORIGINS: env.CORS_ORIGINS ?? '["https://lensword-frontend.pages.dev"]',
    };
  }
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const container = getContainer(env.BACKEND_CONTAINER);
    return container.fetch(request);
  },
};
