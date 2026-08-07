---
title: Local AI / Ollama
description: Opt-in, local mnemonic suggestions via a self-hosted Ollama model — setup, verification, and Docker networking.
---

# Local AI: Ollama-powered mnemonic suggestions

MnemoLab can ask a locally hosted model for a mnemonic. Everything runs on your
machine — no API key, no account, and nothing leaves the host. The feature is
**off by default**: an install that sets none of these settings builds no
provider at all and behaves exactly as it did before.

**1. Install Ollama** — download it from [ollama.com/download](https://ollama.com/download),
or on macOS with Homebrew:

```bash
brew install ollama
ollama serve            # leave running; listens on http://localhost:11434
```

**2. Pull a model** (a few GB — this is the slow step, and it is a one-off):

```bash
ollama pull llama3.2
```

**3. Turn the provider on** in `apps/backend/.env`:

```bash
AI_PROVIDER=ollama
OLLAMA_MODEL=llama3.2
OLLAMA_BASE_URL=http://localhost:11434
```

| Setting | Default | What it does |
|---|---|---|
| `AI_PROVIDER` | `none` | `none` disables AI entirely; `ollama` enables local suggestions. Any other value is rejected at startup with a message listing the supported values. |
| `OLLAMA_MODEL` | `llama3.2` | The model name passed to Ollama. Must be one you have pulled. |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Where the Ollama daemon is listening. |
| `AI_MAX_OUTPUT_TOKENS` | `200` | Upper bound on the length of a generated suggestion. Must be greater than zero — Ollama reads a non-positive value as "no limit", so a zero or negative bound is rejected at startup rather than silently disabling itself. |
| `AI_CONTEXT_MAX_CHARS` | `500` | How much of a word's context is sent to the model. Longer context is truncated. Must be greater than zero. |

Restart the backend, open **MnemoLab**, pick a word and use **Suggest with AI**.

The endpoint (`POST /api/v1/words/{word_id}/mnemonics/suggest`) always answers
HTTP 200 and reports what happened in a `status` field, because a provider
being switched off or temporarily down is a normal state of a healthy install
rather than a server error:

| `status` | When | What MnemoLab shows |
|---|---|---|
| `disabled` | `AI_PROVIDER` is `none` | A calm "AI suggestions unavailable" notice, with no retry — retrying cannot change a setting. |
| `unavailable` | Provider configured but unreachable, timed out, or the model isn't pulled | The reason, plus a retry. |
| `ok` | Success | The suggestion, which you can drop straight into your draft. |

Setting names above match the `Settings` fields `ai_provider`, `ollama_model`
and `ollama_base_url` in `apps/backend/app/config.py`.

## Checking your setup

An administrator can call `GET /api/v1/ai-settings/probe`. It reports the three
failure modes separately, because they need different fixes and a single "AI
unavailable" tells you nothing about which one you have:

| What it says | What it means | What to do |
|---|---|---|
| `reachable: false`, mentions `OLLAMA_BASE_URL` | Nothing is listening there | Start Ollama, or point `OLLAMA_BASE_URL` at the machine running it |
| `reachable: false`, "did not answer like Ollama" | Something is listening, but it is not Ollama | Check the port — you are probably hitting a proxy |
| `reachable: true`, `ready: false` | Ollama is running, the configured model is not installed | `ollama pull <model>`, or pick one of the models the response lists |
| `ready: true` | Configured model is installed and usable | Nothing |

The route is admin-only: it names the deployment's base URL and every model
installed on that host, which is infrastructure detail rather than something a
learner needs.

## Running the backend in Docker with Ollama on the host

`http://localhost:11434` means *inside the container*, where nothing is
listening — so the default fails in Docker even when Ollama is running fine on
your machine. This is the single most common way the setup appears broken.

**macOS and Windows** (Docker Desktop) — use the host alias:

```bash
OLLAMA_BASE_URL=http://host.docker.internal:11434
```

**Linux** — `host.docker.internal` is not provided by default. Either map it
explicitly, which the Compose file can do:

```yaml
services:
  backend:
    extra_hosts:
      - "host.docker.internal:host-gateway"
    environment:
      OLLAMA_BASE_URL: http://host.docker.internal:11434
```

or point at the Docker bridge address directly (`http://172.17.0.1:11434`),
which is stable for the default bridge network but not for user-defined ones.

Whichever you choose, Ollama must be listening on more than loopback. By
default it binds `127.0.0.1`, which a container cannot reach even with the
right hostname:

```bash
OLLAMA_HOST=0.0.0.0 ollama serve
```

Binding `0.0.0.0` exposes the daemon to your whole network. On a laptop on an
untrusted network, bind it to the Docker bridge interface instead, or leave the
backend outside Docker.

**This has been verified with the backend run directly on the host.** Reaching
a host-installed Ollama daemon from inside the Docker containers has not been
tested end to end, and `http://localhost:11434` will not resolve to the host
from within a container without the configuration above — see
[docs/internal/evidence-gaps.md](https://github.com/conectlens/lensword/blob/development/docs/internal/evidence-gaps.md).

## Repeated questions are not re-generated

A local model takes seconds per generation, so identical requests within a
short window are answered from an in-process cache rather than asked again.
Entries are keyed by account, provider and model — a response from one model is
never served for another, and one account's response is never served to
another. Failures are not cached, so a model that was starting up a minute ago
is retried rather than remembered as broken. Changing the AI settings clears
the cache.
