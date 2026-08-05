"""Finding out whether Ollama is there, and what it has (issue #139).

Onboarding needs to answer three questions in order, and they fail differently:
is anything listening, does it speak Ollama's API, and does it have a model we
can use. Collapsing them into "AI unavailable" would leave someone with Ollama
running and no model pulled staring at a message that tells them nothing about
what to do next.

So the result names which step failed and what would fix it. That is the whole
value of a detection step — a check that only says yes or no is a check the
user could have done themselves.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)

# Short: this runs while someone is looking at an onboarding screen, and a
# daemon that is not there fails fast rather than making them wait.
PROBE_TIMEOUT_SECONDS = 3.0

# Suggested when nothing suitable is installed. Small enough to run on a laptop
# without a discrete GPU, which is the machine most people are actually on —
# recommending a model that needs 40GB of VRAM is advice nobody can take.
RECOMMENDED_MODEL = "llama3.2"


@dataclass
class OllamaStatus:
    """What was found, and what to do about it."""

    reachable: bool
    models: list[str] = field(default_factory=list)
    # Which model, if any, the deployment is configured to use.
    configured_model: str | None = None
    # True when the configured model is actually installed. Distinguished from
    # "no models at all", because the fixes differ: pull one specific model, or
    # pull anything.
    configured_model_installed: bool = False
    recommended_model: str = RECOMMENDED_MODEL
    # A sentence the onboarding screen can show verbatim. Written here rather
    # than in the UI so the reason and the advice cannot drift apart.
    detail: str = ""

    @property
    def ready(self) -> bool:
        return self.reachable and self.configured_model_installed


def probe_ollama(
    base_url: str, configured_model: str | None = None, *, client: httpx.Client | None = None
) -> OllamaStatus:
    """Ask an Ollama daemon what it has.

    Never raises. A detection step that can fail the request it runs in would
    make onboarding worse than not having one.
    """
    owns_client = client is None
    client = client or httpx.Client(timeout=PROBE_TIMEOUT_SECONDS)
    try:
        response = client.get(f"{base_url.rstrip('/')}/api/tags")
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPError as exc:
        logger.info("Ollama probe failed for %s: %s", base_url, exc)
        return OllamaStatus(
            reachable=False,
            configured_model=configured_model,
            detail=(
                f"Nothing is answering at {base_url}. Start Ollama, or point "
                "OLLAMA_BASE_URL at the machine running it."
            ),
        )
    except ValueError:
        # Something is listening but it is not Ollama — a proxy, or the wrong
        # port. Worth saying, because "unreachable" would send the user looking
        # for a daemon that is in fact running.
        return OllamaStatus(
            reachable=False,
            configured_model=configured_model,
            detail=(
                f"Something is listening at {base_url} but it did not answer like "
                "Ollama. Check the port."
            ),
        )

    models = sorted(
        {
            str(entry.get("name") or "").strip()
            for entry in (payload.get("models") or [])
            if entry.get("name")
        }
    )

    installed = _matches(models, configured_model) if configured_model else False

    if not models:
        detail = (
            f"Ollama is running, but no models are installed. "
            f"Run `ollama pull {RECOMMENDED_MODEL}` to get started."
        )
    elif configured_model and not installed:
        detail = (
            f"Ollama is running, but `{configured_model}` is not installed. "
            f"Run `ollama pull {configured_model}`, or choose one of: {', '.join(models)}."
        )
    else:
        detail = f"Ollama is running with {len(models)} model(s) installed."

    return OllamaStatus(
        reachable=True,
        models=models,
        configured_model=configured_model,
        configured_model_installed=installed,
        detail=detail,
    )


def _matches(models: list[str], configured: str) -> bool:
    """Whether the configured model is among those installed.

    Ollama reports tags (`llama3.2:latest`) while the setting is usually the
    bare name (`llama3.2`). Treating those as different would tell someone to
    pull a model they already have.
    """
    wanted = configured.strip().lower()
    if not wanted:
        return False
    bare = wanted.split(":", 1)[0]
    return any(
        name.lower() == wanted or name.lower().split(":", 1)[0] == bare for name in models
    )
