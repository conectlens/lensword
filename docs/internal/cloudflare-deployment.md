# Cloudflare deployment setup (frontend only)

Maintainer/ops reference, not part of the published docs site (`srcExclude:
['internal/**']` in `config.mts`).

**Backend and MCP are no longer deployed to Cloudflare** — Cloudflare
Containers requires the Workers Paid plan ($5/mo minimum), confirmed by a
real "Unauthorized" failure attempting to deploy against a Free-plan
account. Both now deploy to Render.com instead — see
[render-deployment.md](./render-deployment.md). The `apps/backend` and
`apps/mcp` Cloudflare Worker/Container configs (`wrangler.toml`,
`cf-worker/`) were removed entirely, not just disabled, once Render was
confirmed working — check git history before this point if any of that is
ever needed again (e.g. the account is upgraded to Workers Paid and
Containers becomes preferred).

## What's still deployed here

| Service | Cloudflare product | Config | Workflow |
|---|---|---|---|
| `apps/frontend` | Pages (static assets) | `apps/frontend/wrangler.toml` | `.github/workflows/deploy-frontend.yml` |

Pages has no paid-plan gate — this path is live and working.

## Creating the Cloudflare API token

Dashboard → **My Profile → API Tokens → Create Token → Create Custom Token**.

- **Account** → `Cloudflare Pages` → **Edit**
- **Account** → `Account Settings` → **Read**
- **User** → `User Details` → **Read**

Restrict **Account Resources** to this one account.

## Finding the Account ID

Dashboard → any domain/Workers & Pages overview page → **Account ID** in
the right sidebar. Or: `npx wrangler whoami` after `npx wrangler login`
locally.

## GitHub secrets this workflow needs

```bash
gh secret set CLOUDFLARE_API_TOKEN --repo conectlens/lensword
gh secret set CLOUDFLARE_ACCOUNT_ID --repo conectlens/lensword
gh secret set PRODUCTION_API_URL --repo conectlens/lensword
```

`PRODUCTION_API_URL` **must include the `https://` scheme** — a bare
hostname (`lensword-api.conectlens.com` instead of
`https://lensword-api.conectlens.com`) is silently treated as a relative
path by the frontend's `fetch()` calls, not an API origin, and every
request goes to the frontend's own domain instead. This exact mistake
happened once already in this project — see
`apps/frontend/src/lib/runtimeConfig.ts`'s `assertAbsoluteHttpUrl`, added
specifically because of it; a build with the wrong scheme now fails
loudly instead of silently misrouting.

Set it to wherever the backend actually lives once Render deployment is
confirmed (see render-deployment.md) — either the Render-generated
`https://lensword-backend.onrender.com`-style URL, or the custom domain
`https://lensword-api.conectlens.com` once that's pointed at it via DNS.

## Custom domain for the frontend

`wrangler pages domain` is not a real command — Pages custom domains are
dashboard-only (Pages project → Custom domains tab), not
wrangler/config-driven the way a Worker's `[[routes]]` block is.

## Verifying locally before relying on CI

```bash
cd apps/frontend && npm ci && npm run build && npx wrangler pages deploy dist --project-name=lensword-frontend
```

Fails on auth without a token — confirms syntax, not a real deploy.
