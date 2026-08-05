"""Detecting Ollama during onboarding (issue #139).

The point of a detection step is that it says what to do next. A check that
only reports yes or no is one the user could have run themselves, so most of
these tests are about whether the right *advice* comes back.
"""
from __future__ import annotations

import httpx

from app.infrastructure.ollama_probe import (
    RECOMMENDED_MODEL,
    probe_ollama,
)


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _tags(*names):
    return lambda request: httpx.Response(200, json={"models": [{"name": n} for n in names]})


# --- Not there --------------------------------------------------------------


def test_an_unreachable_daemon_is_reported_with_what_to_do():
    def handler(request):
        raise httpx.ConnectError("refused")

    status = probe_ollama("http://localhost:11434", "llama3.2", client=_client(handler))

    assert status.reachable is False
    assert status.ready is False
    assert "OLLAMA_BASE_URL" in status.detail


def test_something_that_is_not_ollama_is_distinguished_from_nothing():
    """"Unreachable" would send the user looking for a daemon that is in fact
    running."""
    def handler(request):
        return httpx.Response(200, text="<html>hello</html>")

    status = probe_ollama("http://localhost:11434", "llama3.2", client=_client(handler))

    assert status.reachable is False
    assert "did not answer like" in status.detail


def test_a_probe_never_raises():
    def handler(request):
        raise httpx.ReadTimeout("slow")

    # A detection step that can fail the request it runs in would make
    # onboarding worse than not having one.
    assert probe_ollama("http://x", "m", client=_client(handler)).reachable is False


# --- Running, but nothing pulled -------------------------------------------


def test_a_running_daemon_with_no_models_says_what_to_pull():
    """Someone with Ollama running and no model pulled must not be told "AI
    unavailable" — it tells them nothing about what to do next."""
    def handler(request):
        return httpx.Response(200, json={"models": []})

    status = probe_ollama("http://localhost:11434", "llama3.2", client=_client(handler))

    assert status.reachable is True
    assert status.ready is False
    assert f"ollama pull {RECOMMENDED_MODEL}" in status.detail


def test_the_recommended_model_is_one_a_laptop_can_run():
    """Recommending a model that needs 40GB of VRAM is advice nobody can
    take."""
    def handler(request):
        return httpx.Response(200, json={"models": []})

    status = probe_ollama("http://x", None, client=_client(handler))

    assert status.recommended_model == RECOMMENDED_MODEL


# --- Running, wrong model ---------------------------------------------------


def test_a_missing_configured_model_is_distinguished_from_no_models():
    """The fixes differ: pull one specific model, or pull anything."""
    status = probe_ollama("http://x", "mistral", client=_client(_tags("llama3.2:latest")))

    assert status.reachable is True
    assert status.configured_model_installed is False
    assert "ollama pull mistral" in status.detail


def test_the_installed_models_are_offered_as_alternatives():
    status = probe_ollama("http://x", "mistral", client=_client(_tags("llama3.2:latest", "qwen2")))

    assert "llama3.2:latest" in status.detail
    assert "qwen2" in status.detail


# --- Running and ready ------------------------------------------------------


def test_a_configured_model_that_is_installed_is_ready():
    status = probe_ollama("http://x", "llama3.2", client=_client(_tags("llama3.2:latest")))

    assert status.ready is True
    assert status.configured_model_installed is True


def test_a_tagged_model_matches_the_bare_configured_name():
    """Ollama reports `llama3.2:latest` while the setting is usually
    `llama3.2`. Treating those as different would tell someone to pull a model
    they already have."""
    status = probe_ollama("http://x", "llama3.2", client=_client(_tags("llama3.2:latest")))

    assert status.configured_model_installed is True


def test_an_exact_tag_also_matches():
    status = probe_ollama("http://x", "llama3.2:latest", client=_client(_tags("llama3.2:latest")))

    assert status.configured_model_installed is True


def test_matching_ignores_case():
    status = probe_ollama("http://x", "LLaMA3.2", client=_client(_tags("llama3.2:latest")))

    assert status.configured_model_installed is True


def test_models_come_back_sorted_and_deduplicated():
    status = probe_ollama("http://x", None, client=_client(_tags("qwen2", "llama3.2", "qwen2")))

    assert status.models == ["llama3.2", "qwen2"]


def test_a_malformed_entry_is_skipped_rather_than_crashing():
    def handler(request):
        return httpx.Response(200, json={"models": [{"name": ""}, {"size": 1}, {"name": "ok"}]})

    assert probe_ollama("http://x", None, client=_client(handler)).models == ["ok"]


def test_a_deployment_with_no_configured_model_is_not_ready():
    """Reachable is not the same as usable."""
    status = probe_ollama("http://x", None, client=_client(_tags("llama3.2")))

    assert status.reachable is True
    assert status.ready is False


def test_a_trailing_slash_in_the_base_url_does_not_break_the_probe():
    status = probe_ollama("http://x/", "llama3.2", client=_client(_tags("llama3.2")))

    assert status.reachable is True
