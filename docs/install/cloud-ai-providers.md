---
title: Cloud AI providers (Gemini, Vertex AI, OpenAI)
description: Enable AI features on a hosted deploy without running your own Ollama daemon — setup, admin-side configuration, and what has and hasn't been verified.
---

# Cloud AI providers: Gemini, Vertex AI, OpenAI

[Local AI / Ollama](local-ai-ollama.md) needs a daemon running somewhere
`OLLAMA_BASE_URL` can reach it — fine for local development or a
self-hosted server you control, but not an option on a typical hosted
platform (Render's own deploy guide defaults to `AI_PROVIDER=none` for
exactly this reason — see
[docs/internal/render-deployment.md](https://github.com/conectlens/lensword/blob/development/docs/internal/render-deployment.md)).
`AI_PROVIDER` also accepts `gemini`, `vertex`, and `openai` (issue #315) for
a deploy that needs real AI features without operating its own model host.

All three implement the same `AIProvider` port Ollama does — mnemonic
suggestions, vocabulary extraction/enrichment, the conversation tutor,
learning paths, and the companion coach all work identically regardless of
which one is configured, and the companion coach's evidence/forbidden-claim
validation (`validate_generated_content`) applies to every provider's output
the same way, not just Ollama's.

## Verification status — read this before choosing one for production

**Every adapter's request construction, JSON-mode handling, and
error-to-`AIProviderUnavailableError` mapping is covered by unit tests
against a mocked transport** (`tests/test_google_ai_providers.py`,
`tests/test_openai_provider.py`) — no test in this codebase has made a real
network call to Gemini, Vertex AI, or OpenAI, because no credentials for any
of the three were available in the environment this was built in.

This is a materially different verification level than Ollama's own
integration tests in `tests/test_ollama_provider.py`, which run for real
against a local daemon whenever one happens to be reachable (see
[docs/reference/ai-model-verification.md](../reference/ai-model-verification.md)
for a dated log of an actual such run). No equivalent live-model pass exists
yet for Gemini, Vertex AI, or OpenAI. Concretely, unverified against a real
account:

- that the request shape this adapter sends is accepted end-to-end by the
  real API (only the SDK's own request construction was inspected, not a
  live response from Google/OpenAI's servers);
- real-world latency, JSON-mode compliance rate, and output quality for the
  prompts this codebase uses (the same category of finding
  `docs/reference/ai-model-verification.md` recorded for Ollama);
- that `GOOGLE_APPLICATION_CREDENTIALS`/workload identity resolves the way
  this doc describes in an actual Render/Docker deployment.

Treat a first production rollout of any of these three as needing its own
verification pass, the same way Ollama's did, before relying on it for real
learners.

## Gemini

The Gemini Developer API, authenticated with a single API key.

```bash
AI_PROVIDER=gemini
GEMINI_API_KEY=your-key-from-aistudio.google.com
GEMINI_MODEL=gemini-2.5-flash
```

Get a key at [aistudio.google.com/apikey](https://aistudio.google.com/apikey).
`GEMINI_MODEL` defaults to `gemini-2.5-flash` — Google's fast/economical
tier, a deliberate choice for a feature that runs on every learner action
rather than the top-of-line reasoning model.

## Vertex AI

The same underlying Gemini models, reached through Google Cloud's Vertex AI
API instead — for a deployment that already lives inside a GCP project and
wants billing/quota/IAM to go through that project rather than a standalone
API key.

```bash
AI_PROVIDER=vertex
VERTEX_PROJECT_ID=your-gcp-project-id
VERTEX_LOCATION=us-central1
VERTEX_MODEL=gemini-2.5-flash
```

Vertex authenticates differently from Gemini: **there is no `VERTEX_API_KEY`
field.** The `google-genai` SDK resolves
[Application Default Credentials](https://cloud.google.com/docs/authentication/application-default-credentials)
on its own — a service-account key file referenced by the
`GOOGLE_APPLICATION_CREDENTIALS` environment variable, or workload identity
when running on GCP compute. That resolution happens entirely inside the
SDK; this backend does not read, parse, or validate a credentials file
itself. Set `GOOGLE_APPLICATION_CREDENTIALS` (and mount the key file it
points at) in the deploy environment alongside `VERTEX_PROJECT_ID` —
neither Docker Compose nor `apps/backend/.env.example` does this for you
automatically, since where the key file lives is deployment-specific.

## OpenAI

```bash
AI_PROVIDER=openai
OPENAI_API_KEY=your-key-from-platform.openai.com
OPENAI_MODEL=gpt-5.6-luna
```

Get a key at
[platform.openai.com/api-keys](https://platform.openai.com/api-keys).
`OPENAI_MODEL` defaults to the current general-purpose model as confirmed
against OpenAI's own API documentation while this adapter was built —
model names churn faster than most dependencies, so re-check the live
model list before trusting this indefinitely on a new deploy.

## Startup validation

Same "fail at startup, not at generation" posture Ollama's own
`AI_PROVIDER` validation already has (see
[local-ai-ollama.md](local-ai-ollama.md)): setting `AI_PROVIDER` to a cloud
provider without its one required field —
`GEMINI_API_KEY`/`VERTEX_PROJECT_ID`/`OPENAI_API_KEY` — stops the app at
startup with a message naming exactly what's missing, rather than a
confusing failure on someone's first suggestion request. The admin
AI-settings API (`PUT /api/v1/ai-settings`) enforces the same check
immediately on save, before the new configuration is even persisted.

## Admin AI-settings API

`GET`/`PUT /api/v1/ai-settings` (admin-only, same as Ollama's) carry every
provider's fields at once, not just the currently selected one — so
switching providers through the API doesn't require a separate schema.
`GET` never echoes a configured `gemini_api_key`/`openai_api_key` back;
instead it reports `gemini_api_key_set`/`openai_api_key_set` booleans, the
same "is this credential configured" shape many admin APIs use for a stored
secret. Submitting a blank key on `PUT` leaves the previously stored one
alone rather than clearing it, so updating just a model name or the
selected provider doesn't require resending the secret.

`GET /api/v1/ai-settings/probe` behaves differently depending on the
configured provider. For Ollama (or AI switched off), it is the original
reachability + model-list check against the local daemon. For a cloud
provider, it deliberately does **not** make a real generation call —
that would be a paid API request fired on every admin page load — and
instead reports whether the required credential looks configured
(`live_check_performed: false` on the response marks this explicitly, so a
caller does not mistake it for a verified live connection the way Ollama's
own `reachable: true` is).

## Bring Your Own Key (BYOK)

Everything above is deployment-wide: one `AI_PROVIDER` an administrator
configures, used for every learner's requests. A hosted deployment with no
billing/credits system cannot pay for everyone's usage that way forever —
so a signed-in user can instead supply their **own** Gemini, OpenAI, or
Vertex AI credential, on the Settings page, used automatically for their
own requests. No admin opt-in is required to enable this per user.

**Precedence.** A user with no stored credential of their own is
unaffected — every request still goes through the deployment's own
`AI_PROVIDER` exactly as described above. A user with exactly one stored
credential has it used regardless of what the deployment is configured
with. A user who has stored credentials for more than one provider gets
whichever one matches the deployment's own `AI_PROVIDER`, if any; if none
matches, there is no principled way to guess which of two personal keys
they meant, so it falls back to the deployment default rather than
guessing. See `resolve_ai_provider_for_user` in `app/api/deps.py` for the
exact policy and its own worked-through reasoning.

**A broken personal credential is reported, not silently absorbed.** If a
user's own key stops working — revoked at the provider, or the
deployment's master encryption key was rotated — their requests fail with
the same "AI provider is not reachable" response any other provider
failure produces. They deliberately do **not** fall back to the
deployment's own key: the entire point of BYOK is that a deployment with
no billing system does not pay for a user's usage, and silently spending
its budget because a user's own key broke would undermine that.

**Storage and encryption.** Each credential is encrypted at rest with
application-level authenticated encryption
(`cryptography.fernet.Fernet`) under one master key,
`AI_CREDENTIAL_ENCRYPTION_KEY` — not a cloud KMS or HashiCorp Vault, to
avoid adding a second service to run and back up on top of this project's
self-hosted-first Docker/Render/SQLite posture. Generate one with:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Leaving it unset does not silently disable BYOK insecurely — every write
to a credential fails with a clear `503` until it is configured, the same
"fail loudly, not by degrading to something worse" posture the rest of
this codebase's AI configuration already has.

**API**: `GET`/`PUT`/`DELETE /api/v1/me/ai-credentials[/{provider}]`,
user-scoped (any signed-in account, not admin-only). `GET` never returns a
stored secret — only which providers are configured and each one's
non-secret fields (Vertex's `project_id`/`location`; nothing for
Gemini/OpenAI, whose only field is the key itself). `PUT` validates the
payload against that provider's own schema
(`app/domain/services/ai_credentials.py` — the extensibility point for a
future provider: one new schema class, nothing else in this stack
changes) before encrypting and storing it. Writes are rate-limited
separately from AI generation itself (`RATE_LIMIT_AI_CREDENTIAL_WRITES`).

**Verification status.** Schema validation, the encrypt/decrypt round
trip, the API's never-leak-a-secret contract, cross-user isolation, and
every branch of the precedence/fallback policy above are covered by unit
tests against a mocked transport — the same offline-only standard the
deployment-wide adapters above are held to, and for the same reason: no
real Gemini/OpenAI/Vertex AI credentials were available while building
this. This is genuinely new territory for this codebase — the first
reversibly-encrypted secret it has ever stored (every other credential
here, a password or an OAuth token, is one-way hashed) — and handles real
financial-risk credentials if it is wrong. Treat it as needing a human
security review before it is relied on for real users' keys, not as
self-certified safe by these tests passing.
