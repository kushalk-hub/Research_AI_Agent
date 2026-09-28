"""Per-provider base_url overrides (LiteLLM path only).

The routing map has to be per-provider rather than a single global URL: two
providers are live at once during cross-provider failover, and a shared endpoint
would silently break the primary. These tests pin that, plus the resolution of a
bare (unprefixed) model id, which is how this project writes its defaults.
"""

from __future__ import annotations

import json
import sys
import types

from pydantic import BaseModel, Field

from rla.config import Settings
from rla.llm.litellm_backend import LiteLLMBackend, route_model


class Ping(BaseModel):
    ok: str = Field(default="yes")


def settings_with(urls: str | None, **kw) -> Settings:
    # Pinned defaults, not inherited ones: Settings reads the developer's real
    # .env, so an unpinned field would make these tests assert against whatever
    # the local machine happens to have configured.
    base = {
        "llm_provider": "gemini",
        "fast_model": "gemini-2.5-flash-lite",
        "strong_model": "gemini-2.5-flash",
        "structured_model": "",
        "answer_model": "",
        "fallback_models": "gemini-2.5-flash",
        "llm_base_urls": "",
    }
    base.update({k: v for k, v in kw.items() if v is not None})
    base["llm_base_urls"] = urls or ""
    return Settings(gemini_api_key="k", **base)


def install_fake_litellm(calls: list[dict]) -> None:
    """Fake litellm module that records the kwargs of every call."""

    class Usage:
        prompt_tokens, completion_tokens, total_tokens = 5, 3, 8

    class Msg:
        def __init__(self, c):
            self.content = c

    class Choice:
        def __init__(self, c):
            self.message = Msg(c)

    class Resp:
        def __init__(self, c):
            self.choices = [Choice(c)]
            self.usage = Usage()

    def completion(**kwargs):
        calls.append(kwargs)
        if kwargs.get("stream"):
            return iter(
                [
                    types.SimpleNamespace(
                        choices=[types.SimpleNamespace(delta=types.SimpleNamespace(content="a "))],
                        usage=None,
                    ),
                    types.SimpleNamespace(choices=[], usage=Usage()),
                ]
            )
        if "response_format" in kwargs:
            return Resp('{"ok": "yes"}')
        return Resp("hello")

    m = types.ModuleType("litellm")
    m.completion = completion
    m.supports_response_schema = lambda model, custom_llm_provider=None: True
    m.drop_params = False
    sys.modules["litellm"] = m


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def test_no_override_means_provider_default():
    s = settings_with(None)
    assert s.parsed_base_urls() == {}
    assert s.base_url_for("gemini-2.5-flash") is None
    assert s.base_url_for("openai/gpt-4o-mini") is None


def test_an_override_is_keyed_by_provider_prefix():
    s = settings_with(json.dumps({"openrouter": "https://openrouter.ai/api/v1"}))
    assert s.base_url_for("openrouter/meta/llama-3") == "https://openrouter.ai/api/v1"
    assert s.base_url_for("openai/gpt-4o-mini") is None


def test_two_providers_get_different_endpoints():
    """The reason this is a map: a shared URL would break the primary."""
    s = settings_with(
        json.dumps(
            {
                "gemini": "https://gateway.corp/google/v1",
                "openai": "https://gateway.corp/openai/v1",
            }
        )
    )
    assert s.base_url_for("gemini/gemini-2.5-flash") == "https://gateway.corp/google/v1"
    assert s.base_url_for("openai/gpt-4o-mini") == "https://gateway.corp/openai/v1"


def test_a_bare_model_id_resolves_to_the_primary_provider():
    """The project's defaults are bare ids, so `gemini/...` keys must still apply.

    Otherwise an override would work for every model except the ones actually
    configured by default, which is the worst possible failure mode: it looks set.
    """
    s = settings_with(json.dumps({"gemini": "https://proxy.corp/v1"}))
    assert s.base_url_for("gemini-2.5-flash") == "https://proxy.corp/v1"
    assert s.base_url_for("gemini/gemini-2.5-flash") == "https://proxy.corp/v1"


def test_malformed_json_is_ignored_rather_than_fatal():
    """A typo in an optional convenience setting must not stop the pipeline."""
    s = settings_with("{not json")
    assert s.parsed_base_urls() == {}
    assert s.base_url_for("gemini-2.5-flash") is None


def test_a_json_list_is_ignored():
    s = settings_with("[1, 2, 3]")
    assert s.parsed_base_urls() == {}


def test_an_empty_value_is_dropped():
    s = settings_with(json.dumps({"gemini": ""}))
    assert s.parsed_base_urls() == {}
    assert s.base_url_for("gemini-2.5-flash") is None


def test_the_primary_prefix_follows_a_reconfigured_primary_model():
    """Pointing the primary at another provider re-keys the bare-id lookup."""
    s = settings_with(
        json.dumps({"openai": "https://o.corp/v1"}), fast_model="openai/gpt-4o-mini"
    )
    assert s.primary_provider_prefix == "openai"
    assert s.base_url_for("gpt-4o-mini") == "https://o.corp/v1"


# ---------------------------------------------------------------------------
# Plumbing into the backend
# ---------------------------------------------------------------------------


async def test_no_base_url_is_sent_when_unconfigured():
    calls: list[dict] = []
    install_fake_litellm(calls)
    s = settings_with(None)
    await LiteLLMBackend(s, None, None).generate_text(
        "hi", model=s.model_for_structured, temperature=0.0, stage="x"
    )
    assert "base_url" not in calls[0], "provider default must be left alone"


async def test_text_generation_carries_the_override():
    calls: list[dict] = []
    install_fake_litellm(calls)
    s = settings_with(json.dumps({"gemini": "https://proxy.corp/v1"}))
    await LiteLLMBackend(s, None, None).generate_text(
        "hi", model=s.model_for_structured, temperature=0.0, stage="x"
    )
    assert calls[0]["base_url"] == "https://proxy.corp/v1"
    assert calls[0]["num_retries"] == 0  # RLA still owns retry


async def test_structured_generation_carries_the_override():
    calls: list[dict] = []
    install_fake_litellm(calls)
    s = settings_with(json.dumps({"openai": "https://o.corp/v1"}))
    await LiteLLMBackend(s, None, None).generate_structured(
        "p", Ping, model="openai/gpt-4o-mini", temperature=0.0, stage="x"
    )
    call = next(c for c in calls if "response_format" in c)
    assert call["base_url"] == "https://o.corp/v1"


async def test_streaming_carries_the_override():
    calls: list[dict] = []
    install_fake_litellm(calls)
    s = settings_with(json.dumps({"openai": "https://o.corp/v1"}))
    backend = LiteLLMBackend(s, None, None)
    [c async for c in backend.stream_text("p", model="openai/gpt-4o-mini",
                                          temperature=0.0, stage="x")]
    assert calls[0]["base_url"] == "https://o.corp/v1"
    assert calls[0]["stream"] is True


async def test_a_second_provider_uses_its_own_endpoint():
    """The failover case: primary and fallback must not share an endpoint."""
    calls: list[dict] = []
    install_fake_litellm(calls)
    s = settings_with(
        json.dumps({"gemini": "https://g.corp/v1", "openai": "https://o.corp/v1"})
    )
    backend = LiteLLMBackend(s, None, None)
    await backend.generate_text("hi", model="gemini-2.5-flash", temperature=0.0, stage="a")
    await backend.generate_text("hi", model="openai/gpt-4o-mini", temperature=0.0, stage="b")
    assert calls[0]["base_url"] == "https://g.corp/v1"
    assert calls[1]["base_url"] == "https://o.corp/v1"


# ---------------------------------------------------------------------------
# Scope
# ---------------------------------------------------------------------------


def test_the_native_backend_has_no_endpoint_override():
    """Deliberate scope: the native Gemini path talks directly to Google.

    Adding an override there would need google-genai's http_options plumbing and is
    not needed to reach an arbitrary provider, which is what this setting is for.
    """
    from rla.llm.gemini import GeminiClient

    s = settings_with(json.dumps({"gemini": "https://proxy.corp/v1"}))
    assert not hasattr(GeminiClient(s), "base_url")


def test_route_model_passes_an_unrecognised_prefix_through_untouched():
    """`route_model` does not invent providers, and must not.

    LiteLLM itself rejects an unknown prefix with "LLM Provider NOT provided", so
    mapping `local/x` onto `openai/x` here would be a silent opinion about which
    provider the operator meant. Our job is to pass the string through and let
    LiteLLM be the authority on what it supports.
    """
    assert route_model("local/my-model") == "local/my-model"
    assert route_model("mycorp/some-model") == "mycorp/some-model"


def test_an_unrecognised_prefix_is_still_accepted_by_the_base_url_map():
    """Resolution is independent of whether LiteLLM knows the provider.

    Storing an entry for an unknown prefix is harmless and lets an operator
    pre-configure an endpoint ahead of LiteLLM adding support for it.
    """
    s = settings_with(json.dumps({"local": "http://localhost:8000/v1"}))
    assert s.base_url_for("local/my-model") == "http://localhost:8000/v1"
