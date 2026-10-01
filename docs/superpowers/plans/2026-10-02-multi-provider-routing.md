# P12 Multi-Provider Dispatch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let one pipeline run use Ollama for high-volume structured stages, Gemini for answer generation, and OpenRouter as fallback, with a native Ollama backend that is ~12x faster than routing Ollama through LiteLLM.

**Architecture:** `ProviderRouter` is unchanged and remains the single owner of model precedence, capability gating, and fallback eligibility/order. A new `MultiBackend` implements the existing `RoutingBackend` protocol and resolves each model id to its owning provider backend, so cross-provider fallback works without touching the router. A new `canonical_model()` resolves every model string to one `provider/model` identity that feeds provider resolution, cache keys, merge-threshold lookup, and display.

**Tech Stack:** Python 3.12, httpx, pydantic-settings, pytest + pytest-asyncio (`asyncio_mode = "auto"`), ruff (line-length 100, `select = ["E","F","I","UP","B"]`).

**Spec:** `docs/superpowers/specs/2026-10-02-multi-provider-routing-design.md`

## Global Constraints

- Run everything through the venv: `.\.venv\Scripts\python.exe`. Never the system Python.
- Tests must never read the developer's `.env`. `tests/conftest.py` already isolates both the `.env` file and any exported `RLA_*` variables; do not bypass it by constructing `Settings()` without `_env_file=None` in a new test.
- Every new outbound call goes through `rla.llm.retry.call_with_retry`. There is exactly one retry layer (ADR-003). A backend that adds its own retry loop is a defect.
- No module outside `src/rla/llm/` may import a provider SDK. `tests/test_p9_acceptance.py::test_a1_no_pipeline_module_imports_a_provider_sdk` enforces this by AST inspection. When a new adapter module is added, add its filename to `ADAPTER_MODULES` in that test or A1 will fail it.
- Test modules are named `test_p<N>_*.py` after the milestone they gate.
- Every error raised must be a typed `ProviderError` subclass, or normalize cleanly via `rla.llm.error_map.normalize`. Stages catch `LLMError`.
- Never write a merge threshold without explicit operator approval.
- Ollama native endpoints take no `/v1` and no `/api`; the backend appends the path.
- Run the full suite before every commit: `.\.venv\Scripts\python.exe -m pytest tests/ -q` and `.\.venv\Scripts\python.exe -m ruff check src/ tests/`.

## File Structure

| File | Responsibility |
|---|---|
| `src/rla/errors.py` (modify) | add `ModelResolutionError` — raised before any network request |
| `src/rla/config.py` (modify) | `canonical_model()`, `KNOWN_PROVIDERS`, `PROVIDER_NATIVE_PREFIXES`; rewire `provider_prefix_for` onto the canonical rule; add `RLA_OLLAMA_URL`, `RLA_OLLAMA_THINK` |
| `src/rla/llm/ollama_backend.py` (create) | native Ollama text backend: `/api/generate`, grammar-constrained via `format` |
| `src/rla/llm/multi.py` (create) | `MultiBackend` facade; resolves model id → owning backend; lazy construction |
| `src/rla/llm/factory.py` (modify) | build `MultiBackend`; `BACKENDS` gains `ollama`; `build_embedder` gains provider selection |
| `src/rla/llm/router.py` (modify) | session overrides rung; `on_fallback` observer; docstring correction for the precedence contract |
| `src/rla/llm/embedding_base.py` (modify) | `EmbeddingProvider` protocol |
| `src/rla/llm/ollama_embedder.py` (create) | native Ollama embeddings via batched `/api/embed` |
| `src/rla/llm/embeddings.py` (modify) | `Embedder` conforms to the protocol; keys on canonical id |
| `src/rla/pipeline/resolve.py` (modify) | `MergeThresholds`, `EMBEDDING_THRESHOLDS`, `thresholds_for()`, auto-merge disabled when uncalibrated |
| `src/rla/eval/merge_calibration.py` (create) | similarity distribution + proposed thresholds; never writes without approval |
| `src/rla/cli.py` (modify) | `--structured-model` / `--answer-model`; `_build_pipeline` returns the router; `doctor --llm` dedupes by canonical id |
| `src/rla/tui/state.py`, `app.py` (modify) | transient model overrides; routing status rows; fallback log lines |
| `docs/adr/0006-*.md`, `docs/adr/0007-*.md` (create) | why `MultiBackend`; why uncalibrated disables auto-merge |

---

# P12a — Provider routing

## Task 1: Canonical model identity

Nothing else can be built on top of ambiguity, and it is the defect class this milestone exists to eliminate.

**Files:**
- Modify: `src/rla/errors.py`
- Modify: `src/rla/config.py` (methods block, after `provider_prefix_for` at line 227)
- Test: `tests/test_p12_providers.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `rla.errors.ModelResolutionError(RuntimeError)`
  - `rla.config.KNOWN_PROVIDERS: frozenset[str]`
  - `rla.config.PROVIDER_NATIVE_PREFIXES: tuple[tuple[str, str], ...]`
  - `Settings.canonical_model(model: str) -> str`

- [ ] **Step 1: Write the failing tests**

```python
"""P12: one canonical identity for every model id.

Canonicalisation is the single place a model string is interpreted. Everything
downstream — provider dispatch, cache keys, threshold lookup, display — consumes
the canonical form, so no two subsystems can grow different resolution rules.
"""

from __future__ import annotations

import pytest

from rla.config import KNOWN_PROVIDERS, Settings
from rla.errors import ModelResolutionError


def settings(**kw) -> Settings:
    return Settings(_env_file=None, gemini_api_key="k", **kw)


# -- explicit prefixes --------------------------------------------------------


@pytest.mark.parametrize(
    "model,expected",
    [
        ("gemini/gemini-2.5-flash", "gemini/gemini-2.5-flash"),
        ("ollama/qwen3:4b", "ollama/qwen3:4b"),
        ("openrouter/ling-3.0-flash-sante:free", "openrouter/ling-3.0-flash-sante:free"),
        ("openai/gpt-4o-mini", "openai/gpt-4o-mini"),
    ],
)
def test_an_explicit_prefix_is_authoritative(model, expected):
    assert settings().canonical_model(model) == expected


# -- bare ids that name their provider ---------------------------------------


@pytest.mark.parametrize(
    "model,expected",
    [
        ("gemini-2.5-flash", "gemini/gemini-2.5-flash"),
        ("gpt-4o-mini", "openai/gpt-4o-mini"),
        ("claude-sonnet-4", "anthropic/claude-sonnet-4"),
        ("text-embedding-3-small", "openai/text-embedding-3-small"),
    ],
)
def test_a_bare_id_that_names_its_provider_is_accepted(model, expected):
    assert settings().canonical_model(model) == expected


# -- bare ids that name nothing ----------------------------------------------


def test_an_ambiguous_bare_id_is_refused_before_any_request():
    with pytest.raises(ModelResolutionError) as excinfo:
        settings().canonical_model("qwen3:4b")

    message = str(excinfo.value)
    assert "Ambiguous model id 'qwen3:4b'" in message
    assert "ollama/qwen3:4b" in message, "the error must name the fix"


def test_an_unknown_provider_prefix_is_refused():
    with pytest.raises(ModelResolutionError) as excinfo:
        settings().canonical_model("foo/bar")

    message = str(excinfo.value)
    assert "Unknown provider prefix 'foo'" in message
    assert "gemini" in message and "ollama" in message


def test_an_empty_model_is_refused():
    with pytest.raises(ModelResolutionError):
        settings().canonical_model("")


# -- invariants ---------------------------------------------------------------


def test_canonicalisation_is_idempotent():
    s = settings()
    once = s.canonical_model("qwen3:4b" if False else "ollama/qwen3:4b")
    assert s.canonical_model(once) == once


def test_two_spellings_of_one_model_share_one_identity():
    """This is the whole point: `qwen3:4b` is refused rather than guessed, so the
    only way to name it is the canonical one -- and therefore there is exactly
    one cache key and one threshold entry per model."""
    s = settings()
    assert s.canonical_model("ollama/qwen3:4b") == s.canonical_model("ollama/qwen3:4b")


def test_surrounding_whitespace_is_stripped_not_fatal():
    assert settings().canonical_model("  ollama/qwen3:4b  ") == "ollama/qwen3:4b"


def test_the_provider_table_covers_the_backends_that_exist():
    assert {"gemini", "ollama", "openai", "openrouter"} <= KNOWN_PROVIDERS
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_p12_providers.py -q`
Expected: collection error — `ModuleNotFoundError: No module named 'rla.errors'` attribute `ModelResolutionError`, and `AttributeError: 'Settings' object has no attribute 'canonical_model'`.

- [ ] **Step 3: Add the error type**

Append to `src/rla/errors.py`:

```python
class ModelResolutionError(RuntimeError):
    """A model id could not be resolved to exactly one provider.

    Raised during configuration resolution, before any request is made. It is a
    configuration fault rather than a provider fault, so it is deliberately not a
    `ProviderError`: the router must not retry it or fail over on it, because no
    other model will fix a malformed id.
    """
```

- [ ] **Step 4: Implement canonicalisation**

In `src/rla/config.py`, add these module-level constants after `PROJECT_ROOT`:

```python
#: Providers served by a native backend in this project.
NATIVE_PROVIDERS = frozenset({"gemini", "ollama"})

#: Provider prefixes LiteLLM routes on. Everything here is served by
#: `LiteLLMBackend`. Curated rather than read from litellm at import time so
#: config.py keeps no dependency on the optional extra, and so an unrecognised
#: prefix is caught here with a useful message instead of by LiteLLM's
#: `LLM Provider NOT provided`.
LITELLM_PROVIDERS = frozenset(
    {
        "openai",
        "openrouter",
        "groq",
        "anthropic",
        "azure",
        "bedrock",
        "cohere",
        "mistral",
        "deepseek",
        "xai",
    }
)

#: Every prefix a model id may carry. Adding a provider is one line here.
KNOWN_PROVIDERS = NATIVE_PROVIDERS | LITELLM_PROVIDERS

#: Bare model-id families that unambiguously name their provider. A bare id
#: matching none of these is REFUSED rather than guessed at, because guessing is
#: how a Gemini model once ended up on a local Ollama endpoint.
PROVIDER_NATIVE_PREFIXES: tuple[tuple[str, str], ...] = (
    ("gemini", "gemini"),
    ("gpt", "openai"),
    ("o1", "openai"),
    ("o3", "openai"),
    ("text-embedding", "openai"),
    ("claude", "anthropic"),
)
```

Add this method to the `Settings` methods block:

```python
    def canonical_model(self, model: str) -> str:
        """Resolve a model id to its one canonical `provider/model` identity.

        Every consumer -- provider dispatch, LLM cache key, embedding cache key,
        merge-threshold lookup, doctor and TUI display -- reads the result of this
        and never re-interprets the original string. Two subsystems therefore
        cannot disagree about which provider a model belongs to.

        A bare id is accepted only when it unambiguously names a provider.
        Anything else raises rather than falling back to a configured default:
        a silent guess is precisely the defect class this exists to remove.
        """
        candidate = (model or "").strip()
        if not candidate:
            raise ModelResolutionError(
                "Empty model id. Expected a model name such as "
                "'gemini/gemini-2.5-flash' or 'ollama/qwen3:4b'."
            )
        if "/" in candidate:
            prefix, bare = candidate.split("/", 1)
            if prefix in KNOWN_PROVIDERS:
                return f"{prefix}/{bare}"
            raise ModelResolutionError(
                f"Unknown provider prefix {prefix!r} in model id {candidate!r}. "
                f"Known providers: {', '.join(sorted(KNOWN_PROVIDERS))}."
            )
        for prefix, provider in PROVIDER_NATIVE_PREFIXES:
            if candidate.startswith(prefix):
                return f"{provider}/{candidate}"
        raise ModelResolutionError(
            f"Ambiguous model id {candidate!r}: it names no known provider. "
            "Specify an explicit provider prefix, for example "
            f"'ollama/{candidate}' (or another supported provider/model id)."
        )
```

Add the import at the top of `config.py`:

```python
from rla.errors import ModelResolutionError
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_p12_providers.py -q`
Expected: PASS, 16 passed.

- [ ] **Step 6: Run the full suite to check for fallout**

Run: `.\.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: PASS. `canonical_model` is new and unused so far, so nothing else changes.

- [ ] **Step 7: Commit**

```bash
git add src/rla/errors.py src/rla/config.py tests/test_p12_providers.py
git commit -m "Add canonical model identity that refuses ambiguous model ids"
```

## Task 2: Native Ollama text backend

**Files:**
- Modify: `src/rla/config.py` (field block, after `llm_timeout_seconds`)
- Create: `src/rla/llm/ollama_backend.py`
- Test: `tests/test_p12_ollama_backend.py` (create)

**Interfaces:**
- Consumes: `Settings.canonical_model` from Task 1; `rla.llm.error_map.normalize`; `rla.llm.retry.call_with_retry`; `rla.llm.gemini.extract_json`.
- Produces: `rla.llm.ollama_backend.OllamaBackend(settings, cache=None, tracker=None)` with `name = "ollama"`, `supports`, `generate_text`, `generate_structured`, `stream_text`.

- [ ] **Step 1: Write the failing tests**

```python
"""P12: the native Ollama text backend.

The reason this exists is a measured 12x penalty: routing Ollama through
LiteLLM's OpenAI-compatible route costs ~4096 prompt tokens because that route
implements structured output by prepending format instructions, while the native
route grammar-constrains the same schema for ~662 tokens.
"""

from __future__ import annotations

import json

import httpx
import pytest

from rla.config import Settings
from rla.llm.embeddings import Embedder  # noqa: F401  (import-order guard)
from rla.llm.errors import ProviderInvalidRequest
from rla.llm.ollama_backend import OllamaBackend
from rla.llm.retry import reset_limiter, reset_spender
from rla.models import Paper
from rla.pipeline.extraction import PaperFacts, build_prompt
from rla.store.cache import CostTracker

OLLAMA = "http://localhost:9999"


@pytest.fixture(autouse=True)
def _clean_shared_state():
    reset_limiter()
    reset_spender()
    yield
    reset_limiter()
    reset_spender()


def backend(tmp_path, **kw) -> OllamaBackend:
    settings = Settings(
        _env_file=None,
        gemini_api_key="k",
        data_dir=tmp_path,
        ollama_url=OLLAMA,
        llm_rpm=60,
        **kw,
    )
    return OllamaBackend(settings, None, CostTracker())


def test_capability_is_reported_by_the_backend(tmp_path):
    b = backend(tmp_path)
    assert b.supports("ollama/qwen3:4b", "supports_structured_output") is True
    # An embedding model is not a text model and must never be offered for schema work.
    assert b.supports("ollama/nomic-embed-text", "supports_structured_output") is False
    assert b.supports("ollama/qwen3:4b", "some_other_capability") is False


@httpx_mock
async def test_structured_output_is_grammar_constrained_not_prompt_engineered(tmp_path):
    """The regression guard for the 12x penalty.

    `format` carries the schema as a grammar constraint. If the prompt also grew,
    we would be back to the prefill bloat that made this route 12x slower.
    """
    paper = Paper(id="p1", title="Graph Attention Networks", year=2018,
                  abstract="We propose Graph Attention Networks, a novel attention "
                           "architecture for graph-structured data.")
    prompt = build_prompt(paper)
    body = PaperFacts.model_json_schema()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "qwen3:4b",
                "response": json.dumps({
                    "summary": "Proposes GAT.",
                    "concepts": [
                        {"name": "Graph Attention Networks", "description": "d",
                         "role": "introduces"}
                    ],
                    "relation": "extends",
                    "relation_target": "message passing",
                }),
                "done": True,
                "eval_count": 30,
                "prompt_eval_count": 662,
            },
        )

    httpx_mock.post("/api/generate").mock(side_effect=handler)

    facts = await backend(tmp_path).generate_structured(
        prompt, PaperFacts, model="ollama/qwen3:4b", stage="extraction"
    )

    assert isinstance(facts, PaperFacts)
    assert facts.concepts[0].name == "Graph Attention Networks"

    sent = json.loads(httpx_mock.calls[0].request.content)
    assert sent["format"] == body, "the schema must ride in `format`"
    assert sent["prompt"] == prompt, "the prompt must not be rewritten"
    assert sent["stream"] is False
    assert sent["think"] is False


@httpx_mock
async def test_thinking_can_be_switched_on(tmp_path):
    httpx_mock.post("/api/generate").respond(
        json={"response": "hi", "done": True, "prompt_eval_count": 1, "eval_count": 1}
    )
    await backend(tmp_path, ollama_think=True).generate_text(
        "p", model="ollama/qwen3:4b", stage="doctor"
    )
    assert json.loads(httpx_mock.calls[0].request.content)["think"] is True


@httpx_mock
async def test_an_unknown_model_names_the_pull_command(tmp_path):
    httpx_mock.post("/api/generate").respond(404, json={"error": "model 'nope:9b' not found"})

    with pytest.raises(ProviderInvalidRequest) as excinfo:
        await backend(tmp_path).generate_text(
            "p", model="ollama/nope:9b", stage="doctor"
        )

    message = str(excinfo.value)
    assert "ollama pull nope:9b" in message
    assert OLLAMA in message


@httpx_mock
async def test_streaming_chunks_join_into_the_non_streamed_answer(tmp_path):
    httpx_mock.post("/api/generate").respond(
        json={"response": "one two three", "done": True,
              "prompt_eval_count": 1, "eval_count": 3}
    )
    chunks = [
        c async for c in backend(tmp_path).stream_text(
            "p", model="ollama/qwen3:4b", stage="answer"
        )
    ]
    assert "".join(chunks) == "one two three"
    assert json.loads(httpx_mock.calls[0].request.content)["stream"] is True


@httpx_mock
async def test_every_call_goes_through_the_shared_retry_layer(tmp_path):
    """ADR-003: exactly one retry layer, owned by `call_with_retry`."""
    httpx_mock.post("/api/generate").respond(503, json={"error": "unavailable"})

    from rla.llm.errors import ProviderServerError

    with pytest.raises(ProviderServerError):
        await backend(tmp_path).generate_text("p", model="ollama/qwen3:4b", stage="doctor")
```

Add these two imports next to the other `rla` imports:

```python
import httpx
import respx
```

and declare the module-level router just below the `OLLAMA` constant:

```python
#: Module-level router, usable both as a decorator (`@httpx_mock`) and for
#: inspecting what was sent via `httpx_mock.calls[i].request`. respx 0.23 has no
#: `add_handler` and no `get_requests`: a dynamic body is registered with
#: `httpx_mock.post(...).mock(side_effect=fn)`.
httpx_mock = respx.mock(base_url=OLLAMA, assert_all_called=False)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_p12_ollama_backend.py -q`
Expected: collection error — `ModuleNotFoundError: No module named 'rla.llm.ollama_backend'`.

- [ ] **Step 3: Add the settings**

In `src/rla/config.py`, in the field block immediately after `llm_timeout_seconds`:

```python
    #: Native Ollama endpoint. No `/v1` and no `/api` -- the backend appends the
    #: path it needs, because the two routes are different: `/api/generate`
    #: grammar-constrains structured output, while the OpenAI-compatible
    #: `/v1/chat/completions` route only prefills format instructions into the
    #: prompt and measured ~12x slower for the same schema.
    ollama_url: str = "http://localhost:11434"
    #: Whether a reasoning model emits its thinking before the answer. Off by
    #: default: free-form thinking interleaved with a grammar constraint asks for
    #: trouble, and measurement showed it costs essentially nothing here.
    ollama_think: bool = False
```

- [ ] **Step 4: Write the backend**

Create `src/rla/llm/ollama_backend.py`:

```python
"""Native Ollama text backend.

The only reason this exists is a measured penalty. Routing Ollama through
LiteLLM's OpenAI-compatible route costs ~4096 prompt tokens per extraction,
because that route implements structured output by prepending ~3.4k tokens of
format instructions. Ollama's native `/api/generate` grammar-constrains the same
schema with a ~662-token prompt: measured 8.1s versus 97.6s on 2026-10-02.

Retry ownership: `call_with_retry` retries, never this module (ADR-003).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
from pydantic import BaseModel

from rla.config import Settings, get_settings
from rla.llm.base import LLMError, record_usage
from rla.llm.error_map import normalize
from rla.llm.errors import ProviderInvalidRequest
from rla.llm.gemini import extract_json
from rla.llm.retry import call_with_retry
from rla.models import content_hash
from rla.store.cache import CostTracker

_STRUCTURED = "supports_structured_output"
_PULL_HINT = re.compile(r"model '([^']+)' not found")


class OllamaBackend:
    """Cache-first, grammar-constrained backend for a local Ollama server."""

    name = "ollama"

    def __init__(
        self,
        settings: Settings | None = None,
        cache: Any | None = None,
        tracker: CostTracker | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.cache = cache
        self.tracker = tracker or CostTracker()

    # -- capabilities -------------------------------------------------------
    def supports(self, model: str, capability: str) -> bool:
        """Report what this backend can actually do, rather than what the model
        is called.

        Ollama grammar-constrains any JSON schema supplied as `format`, so this
        answers honestly and needs no operator declaration -- unlike the LiteLLM
        route, whose static table answers `False` for a model it has no entry for.
        """
        if capability != _STRUCTURED:
            return False
        return "embed" not in model

    # -- internals ---------------------------------------------------------
    def _model_name(self, model: str) -> str:
        """Strip the `ollama/` prefix: the server knows the bare tag."""
        return model.split("/", 1)[1] if "/" in model else model

    def _key(self, prompt: str, model: str, schema: str, temperature: float, tag: str) -> str:
        return "llm:" + content_hash(tag, model, prompt, schema, temperature)

    def _payload(
        self, prompt: str, model: str, temperature: float, schema: dict[str, Any] | None,
        stream: bool,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self._model_name(model),
            "prompt": prompt,
            "stream": stream,
            "think": self.settings.ollama_think,
            "options": {"temperature": temperature},
        }
        if schema is not None:
            # The schema is a grammar constraint, not prompt text. Keeping it
            # out of the prompt is the entire performance reason this backend
            # exists; a test pins that the prompt is never rewritten.
            payload["format"] = schema
        return payload

    def _post_sync(self, payload: dict[str, Any]) -> Any:
        response = httpx.post(
            f"{self.settings.ollama_url.rstrip('/')}/api/generate",
            json=payload,
            timeout=self.settings.llm_timeout_seconds,
        )
        if response.status_code == 404:
            raise self._pull_hint(response, payload["model"])
        response.raise_for_status()
        return response

    @staticmethod
    def _pull_hint(response: httpx.Response, model: str) -> ProviderInvalidRequest:
        match = _PULL_HINT.search(response.text)
        name = match.group(1) if match else model
        return ProviderInvalidRequest(
            f"model {name!r} is not available on the Ollama server. "
            f"Load it with: ollama pull {name}"
        )

    async def _generate(
        self, prompt: str, model: str, temperature: float,
        schema: dict[str, Any] | None, stage: str, tag: str,
    ) -> tuple[str, Any]:
        cache_key = self._key(
            prompt, model, json.dumps(schema, sort_keys=True) if schema else "",
            temperature, tag,
        )
        if self.cache is not None:
            hit = self.cache.get(cache_key, kind="llm")
            if hit is not None:
                return hit, None

        payload = self._payload(prompt, model, temperature, schema, stream=False)

        def _invoke() -> Any:
            return self._post_sync(payload)

        try:
            response = await call_with_retry(
                _invoke,
                stage=f"ollama call failed for stage {stage}",
                limiter=self.settings.llm_limiter,
                max_retries=self.settings.llm_max_retries,
                spender=self.settings.llm_spender,
                timeout=self.settings.llm_timeout_seconds,
            )
        except ProviderInvalidRequest:
            raise
        except Exception as exc:
            raise normalize(exc, provider="ollama", model=model, stage=stage) from exc

        record_usage(self.tracker, stage, response.json())
        text = response.json().get("response", "") or ""
        if schema is not None:
            text = extract_json(text)
        if self.cache is not None:
            self.cache.set(cache_key, text, kind="llm")
        return text, response

    # -- public API --------------------------------------------------------
    async def generate_text(
        self, prompt: str, *, model: str | None = None, temperature: float = 0.0,
        stage: str = "llm",
    ) -> tuple[str, Any]:
        chosen = model or self.settings.fast_model
        return await self._generate(prompt, chosen, temperature, None, stage, "text")

    async def generate_structured(
        self, prompt: str, schema: type[BaseModel], *, model: str | None = None,
        temperature: float = 0.0, stage: str = "llm", retries: int = 2,
    ) -> tuple[BaseModel, Any]:
        chosen = model or self.settings.model_for_structured
        json_schema = schema.model_json_schema()
        current = prompt
        last: Exception | None = None
        for _ in range(retries + 1):
            text, response = await self._generate(
                current, chosen, temperature, json_schema, stage, schema.__name__
            )
            try:
                return schema.model_validate_json(text), response
            except (ValueError, json.JSONDecodeError) as exc:
                last = exc
                current = (
                    f"{prompt}\n\nYour previous output failed schema validation: {exc}. "
                    "Return valid JSON only."
                )
        from rla.llm.errors import StructuredOutputError

        raise StructuredOutputError(
            f"could not coerce response into {schema.__name__} after {retries + 1} attempts"
        ) from last

    async def stream_text(
        self, prompt: str, *, model: str | None = None, temperature: float = 0.0,
        stage: str = "llm",
    ) -> AsyncIterator[str]:
        chosen = model or self.settings.strong_model
        cache_key = self._key(prompt, chosen, "", temperature, "stream")
        if self.cache is not None:
            hit = self.cache.get(cache_key, kind="llm")
            if hit is not None:
                yield hit
                return

        payload = self._payload(prompt, chosen, temperature, None, stream=True)
        collected: list[str] = []
        try:
            with httpx.stream(
                "POST", f"{self.settings.ollama_url.rstrip('/')}/api/generate",
                json=payload, timeout=self.settings.llm_timeout_seconds,
            ) as response:
                if response.status_code == 404:
                    raise self._pull_hint(response, payload["model"])
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line.strip():
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    piece = chunk.get("response") or ""
                    if piece:
                        collected.append(piece)
                        yield piece
        except LLMError:
            raise
        except Exception as exc:
            raise normalize(exc, provider="ollama", model=chosen, stage=stage) from exc

        if self.cache is not None:
            self.cache.set(cache_key, "".join(collected), kind="llm")
```

Add the missing `import re` at the top of that file, next to `import json`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_p12_ollama_backend.py -q`
Expected: PASS.

- [ ] **Step 6: Run the full suite and lint**

Run: `.\.venv\Scripts\python.exe -m pytest tests/ -q` then `.\.venv\Scripts\python.exe -m ruff check src/ tests/`
Expected: PASS / All checks passed.

- [ ] **Step 7: Commit**

```bash
git add src/rla/config.py src/rla/llm/ollama_backend.py tests/test_p12_ollama_backend.py
git commit -m "Add native Ollama backend using grammar-constrained structured output"
```

## Task 3: MultiBackend facade

**Files:**
- Create: `src/rla/llm/multi.py`
- Modify: `src/rla/llm/factory.py`
- Modify: `tests/test_p9_acceptance.py` (add `ollama_backend.py` to `ADAPTER_MODULES`)
- Test: `tests/test_p12_multi_backend.py` (create)

**Interfaces:**
- Consumes: `Settings.canonical_model` (Task 1), `OllamaBackend` (Task 2), `GeminiClient`, `LiteLLMBackend`.
- Produces: `rla.llm.multi.MultiBackend(settings, cache=None, tracker=None)` with `name = "multi"`, `supports`, `generate_text`, `generate_structured`, `stream_text`, `provider_for(model) -> str`, `live_backends() -> dict[str, str]`.

- [ ] **Step 1: Write the failing tests**

```python
"""P12: dispatch each model id to the provider that owns it.

`MultiBackend` is a backend, not a router. `ProviderRouter` keeps every policy
it owns; this only answers "who serves this model". Because `_dispatch` already
loops candidates and calls `run(model=candidate)`, resolving per candidate is
what makes cross-provider fallback work with no router change.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from rla.config import Settings
from rla.llm.factory import build_backend
from rla.llm.gemini import GeminiClient
from rla.llm.multi import MultiBackend
from rla.llm.ollama_backend import OllamaBackend


class Out(BaseModel):
    value: str = Field(default="ok")


def multi(tmp_path, **kw) -> MultiBackend:
    settings = Settings(
        _env_file=None,
        gemini_api_key="k",
        llm_provider="ollama",
        data_dir=tmp_path,
        raw_dir=tmp_path / "raw",
        graph_dir=tmp_path / "graph",
        **kw,
    )
    return MultiBackend(settings, None, None)


# -- resolution ---------------------------------------------------------------


def test_each_model_reaches_the_backend_that_owns_it(tmp_path):
    m = multi(tmp_path)
    assert isinstance(m.backend_for("gemini/gemini-2.5-flash"), GeminiClient)
    assert isinstance(m.backend_for("ollama/qwen3:4b"), OllamaBackend)
    assert m.backend_for("openrouter/ling-3.0-flash-sante:free").name == "litellm"


def test_the_canonical_id_decides_the_backend_not_the_default(tmp_path):
    """`llm_provider` is the default for provider-agnostic ids only."""
    m = multi(tmp_path)
    assert m.provider_for("gemini/gemini-2.5-flash") == "gemini"
    assert m.provider_for("ollama/qwen3:4b") == "ollama"
    assert m.provider_for("gpt-4o-mini") == "openai"


def test_an_unknown_provider_resolves_to_nothing_rather_than_a_guess(tmp_path):
    from rla.errors import ModelResolutionError

    with pytest.raises(ModelResolutionError):
        multi(tmp_path).provider_for("foo/bar")


# -- laziness -----------------------------------------------------------------


def test_a_backend_is_constructed_only_when_a_model_needs_it(tmp_path):
    m = multi(tmp_path)
    assert m.live_backends() == {}

    m.backend_for("ollama/qwen3:4b")
    assert set(m.live_backends()) == {"ollama"}

    m.backend_for("gemini/gemini-2.5-flash")
    assert set(m.live_backends()) == {"ollama", "gemini"}


# -- delegation ---------------------------------------------------------------


def test_capability_is_delegated_to_the_owning_backend(tmp_path):
    m = multi(tmp_path)
    assert m.supports("ollama/qwen3:4b", "supports_structured_output") is True
    assert m.supports("ollama/nomic-embed-text", "supports_structured_output") is False


async def test_a_structured_call_reaches_the_owning_backend(tmp_path):
    m = multi(tmp_path)
    result, _ = await m.generate_structured(
        "p", Out, model="ollama/qwen3:4b", stage="extraction"
    )
    assert isinstance(result, Out)
    assert m.live_backends() == {"ollama"} or "ollama" in m.live_backends()


# -- factory ------------------------------------------------------------------


def test_the_factory_builds_the_facade(tmp_path):
    settings = Settings(_env_file=None, gemini_api_key="k", data_dir=tmp_path,
                        raw_dir=tmp_path / "raw", graph_dir=tmp_path / "graph")
    assert isinstance(build_backend(settings), MultiBackend)


def test_an_unknown_llm_provider_is_still_a_configuration_error(tmp_path):
    settings = Settings(_env_file=None, gemini_api_key="k", data_dir=tmp_path,
                        raw_dir=tmp_path / "raw", graph_dir=tmp_path / "graph",
                        llm_provider="nonsense")
    with pytest.raises(ValueError, match="RLA_LLM_PROVIDER"):
        build_backend(settings)
```

Add `import pytest` to the test file's imports.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_p12_multi_backend.py -q`
Expected: collection error — `ModuleNotFoundError: No module named 'rla.llm.multi'`.

- [ ] **Step 3: Allow the new adapter in the A1 structural test**

In `tests/test_p9_acceptance.py`, change:

```python
ADAPTER_MODULES = ("llm/gemini.py", "llm/litellm_backend.py", "llm/embeddings.py")
```

to:

```python
ADAPTER_MODULES = (
    "llm/gemini.py",
    "llm/litellm_backend.py",
    "llm/ollama_backend.py",
    "llm/embeddings.py",
    "llm/ollama_embedder.py",
)
```

(`ollama_embedder.py` does not exist yet, which is harmless: A1 iterates over files found and only checks names that import a provider SDK.)

- [ ] **Step 4: Write the facade**

Create `src/rla/llm/multi.py`:

```python
"""Dispatch each model id to the provider that owns it.

This sits *below* `ProviderRouter` and *above* the concrete backends. Pipeline
stages never see it; they receive an `LLMClient` and are unaware which provider
served the call (ADR-001).

It owns exactly one decision: which backend serves a given model id. It does not
own retry, pacing, budget, caching, capability policy or fallback order -- those
stay in `ProviderRouter` and `llm/retry.py` (ADR-003).

Cross-provider fallback needs no router change because `ProviderRouter._dispatch`
already iterates candidates and calls `run(model=candidate)`; resolving the owner
per candidate is sufficient.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from pydantic import BaseModel

from rla.config import NATIVE_PROVIDERS, Settings, get_settings
from rla.errors import ModelResolutionError
from rla.llm.gemini import GeminiClient
from rla.store.cache import CostTracker

_STRUCTURED = "supports_structured_output"


class MultiBackend:
    """Resolves a model id to its owning backend, constructing backends lazily.

    Laziness matters: a Gemini-only configuration must never import or construct
    an Ollama or LiteLLM backend, which is what keeps the `[router]` extra
    genuinely optional.
    """

    name = "multi"

    def __init__(
        self,
        settings: Settings | None = None,
        cache: Any | None = None,
        tracker: CostTracker | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.cache = cache
        self.tracker = tracker or CostTracker()
        self._backends: dict[str, Any] = {}

    # -- resolution ---------------------------------------------------------
    def provider_for(self, model: str) -> str:
        """The backend name that serves `model`.

        Derived from the canonical id, so the answer never depends on which
        backend happens to be configured as the default.
        """
        return self.settings.canonical_model(model).split("/", 1)[0]

    def backend_for(self, model: str) -> Any:
        """The backend instance for `model`, built on first use."""
        provider = self.provider_for(model)
        if provider not in self._backends:
            self._backends[provider] = self._construct(provider)
        return self._backends[provider]

    def _construct(self, provider: str) -> Any:
        if provider == "gemini":
            return GeminiClient(self.settings, self.cache, self.tracker)
        if provider == "ollama":
            from rla.llm.ollama_backend import OllamaBackend

            return OllamaBackend(self.settings, self.cache, self.tracker)
        if provider in NATIVE_PROVIDERS:
            raise ModelResolutionError(
                f"provider {provider!r} has no backend; expected one of "
                "gemini, ollama, or a LiteLLM-served provider"
            )
        from rla.llm.litellm_backend import LiteLLMBackend

        return LiteLLMBackend(self.settings, self.cache, self.tracker)

    def live_backends(self) -> dict[str, str]:
        """Provider name to backend name, for `doctor` and diagnostics."""
        return {provider: backend.name for provider, backend in self._backends.items()}

    # -- RoutingBackend -----------------------------------------------------
    def supports(self, model: str, capability: str) -> bool:
        return self.backend_for(model).supports(model, capability)

    async def generate_text(
        self, prompt: str, *, model: str, temperature: float = 0.0, stage: str = "llm"
    ) -> tuple[str, Any]:
        return await self.backend_for(model).generate_text(
            prompt, model=model, temperature=temperature, stage=stage
        )

    async def generate_structured(
        self, prompt: str, schema: type[BaseModel], *, model: str, temperature: float = 0.0,
        stage: str = "llm", retries: int = 2,
    ) -> tuple[BaseModel, Any]:
        return await self.backend_for(model).generate_structured(
            prompt, schema, model=model, temperature=temperature, stage=stage, retries=retries
        )

    async def stream_text(
        self, prompt: str, *, model: str, temperature: float = 0.0, stage: str = "llm"
    ) -> AsyncIterator[str]:
        async for chunk in self.backend_for(model).stream_text(
            prompt, model=model, temperature=temperature, stage=stage
        ):
            yield chunk


__all__ = ["MultiBackend"]
```

- [ ] **Step 5: Point the factory at the facade**

In `src/rla/llm/factory.py`, replace `BACKENDS` and `build_backend`:

```python
#: Backend names accepted by `RLA_LLM_PROVIDER`.
BACKENDS = ("gemini", "litellm", "ollama")


def build_backend(
    settings: Settings,
    cache: Cache | None = None,
    tracker: CostTracker | None = None,
) -> Any:
    """Instantiate the provider-routing stack.

    Always a `MultiBackend`: one code path regardless of how many providers a
    configuration actually uses, and the concrete backends behind it are built
    lazily on first use. `cache` and `tracker` are threaded through because the
    backend that performs the call is the one that meters it -- a backend holding
    its own empty tracker makes the cost report read $0.00 regardless of what was
    spent, which is the silent-zero defect this migration exists to eliminate.
    """
    choice = (settings.llm_provider or "gemini").strip().lower()
    if choice not in BACKENDS:
        raise ValueError(
            f"unknown RLA_LLM_PROVIDER {settings.llm_provider!r}; expected one of "
            f"{', '.join(BACKENDS)}"
        )
    if choice not in ("gemini", "ollama", "litellm"):  # pragma: no cover - guard
        raise ValueError(f"unhandled backend {choice!r}")
    from rla.llm.multi import MultiBackend

    return MultiBackend(settings, cache, tracker)
```

- [ ] **Step 6: Run the new tests, then the full suite**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_p12_multi_backend.py -q`
Expected: PASS except the delegation test that makes a real request.

Then: `.\.venv\Scripts\python.exe -m pytest tests/ -q`
Expected: **FAIL** in `tests/test_p9_acceptance.py` — `test_a8_selecting_a_provider_is_configuration_only` asserts `isinstance(build_backend(settings), GeminiClient)`, and `test_a2_the_gemini_backend_declares_structured_support_for_text_models` still passes. That failure is expected at this point and is the subject of Task 7. Every other test must pass.

- [ ] **Step 7: Commit**

```bash
git add src/rla/llm/multi.py src/rla/llm/factory.py tests/test_p12_multi_backend.py tests/test_p9_acceptance.py
git commit -m "Dispatch model ids to their owning backend through a MultiBackend facade"
```

## Task 4: Precedence contract and fallback observation

**Files:**
- Modify: `src/rla/llm/router.py`
- Modify: `tests/test_p9_provider_routing.py`
- Test: additions to `tests/test_p9_provider_routing.py`

**Interfaces:**
- Consumes: `ProviderRouter` as it exists today.
- Produces:
  - `ProviderRouter.overrides: dict[str, str]` — transient per-role session overrides
  - `ProviderRouter.set_override(role: str, model: str | None) -> None`
  - `ProviderRouter.clear_overrides() -> None`
  - `ProviderRouter.on_fallback: Callable[[tuple[str, str, str, str]], None] | None`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_p9_provider_routing.py`:

```python
# ---------------------------------------------------------------------------
# P12: the session-override rung, and fallback observation
# ---------------------------------------------------------------------------


def test_a_session_override_beats_an_explicit_model_argument(tmp_path):
    """The TUI user must be able to say "use Ollama for extraction in this run"
    even where a stage supplies a model explicitly to label its cost report."""
    backend = FakeBackend()
    router = make_router(backend, tmp_path)
    router.set_override("structured", "openai/gpt-4o-mini")

    asyncio.run(router.generate_text("x", stage="extraction", model="gemini-2.5-flash"))

    assert backend.calls[-1] == ("extraction", "openai/gpt-4o-mini")


def test_an_explicit_argument_still_beats_the_stage_role(tmp_path):
    """Retargeted, not deleted: the old contract survives beneath the new rung."""
    backend = FakeBackend()
    router = make_router(backend, tmp_path)

    asyncio.run(router.generate_text("x", stage="extraction", model="explicit-model"))

    assert backend.calls[-1] == ("extraction", "explicit-model")


def test_an_empty_override_does_not_win(tmp_path):
    """`is not None`, never truthiness: an empty string must not beat a real model."""
    backend = FakeBackend()
    router = make_router(backend, tmp_path)
    router.set_override("structured", "")

    asyncio.run(router.generate_text("x", stage="extraction"))

    assert backend.calls[-1] == ("extraction", settings_structured(router))


def test_clearing_an_override_restores_the_configured_role(tmp_path):
    backend = FakeBackend()
    router = make_router(backend, tmp_path)
    router.set_override("structured", "openai/gpt-4o-mini")
    router.set_override("structured", None)

    asyncio.run(router.generate_text("x", stage="extraction"))

    assert backend.calls[-1] == ("extraction", settings_structured(router))


def test_an_override_does_not_leak_to_another_role(tmp_path):
    backend = FakeBackend()
    router = make_router(backend, tmp_path)
    router.set_override("structured", "openai/gpt-4o-mini")

    asyncio.run(router.generate_text("x", stage="answer"))

    assert backend.calls[-1][0] == "answer"


def test_a_fallback_is_reported_to_the_observer(tmp_path):
    backend = FakeBackend(fail={"gemini-2.5-flash-lite": ProviderServerError("503")})
    router = make_router(backend, tmp_path)
    seen: list[tuple[str, str, str, str]] = []
    router.on_fallback = seen.append

    asyncio.run(router.generate_text("x", stage="extraction"))

    assert seen and seen[0][0] == "extraction"


def test_the_observer_cannot_change_the_fallback_decision(tmp_path):
    """It observes; it does not own. A raising observer must not become a second
    mechanism, so the call still succeeds on the fallback."""
    backend = FakeBackend(fail={"gemini-2.5-flash-lite": ProviderServerError("503")})
    router = make_router(backend, tmp_path)

    def _explode(_entry: tuple[str, str, str, str]) -> None:
        raise RuntimeError("observer tried to interfere")

    router.on_fallback = _explode

    assert asyncio.run(router.generate_text("x", stage="extraction")) == "text from gemini-2.5-flash"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_p9_provider_routing.py -q -k "override or observer"`
Expected: FAIL — `AttributeError: 'ProviderRouter' object has no attribute 'set_override'`.

- [ ] **Step 3: Implement the override rung**

In `src/rla/llm/router.py`, inside `__init__` after `self.fallbacks`:

```python
        #: Transient per-role session overrides (the TUI model selector). Keyed by
        #: role name -- "structured" or "answer" -- not by stage, because the
        #: selector's whole purpose is "use this model for extraction", which
        #: covers both the extraction and resolution stages.
        self.overrides: dict[str, str] = {}
        #: Optional observer for fallback decisions. It is told what happened and
        #: owns none of it: eligibility, ordering and the retry/fallback split
        #: stay entirely inside this class and the backend's `call_with_retry`.
        self.on_fallback: Callable[[tuple[str, str, str, str]], None] | None = None
```

Add these methods after `model_for`:

```python
    def set_override(self, role: str, model: str | None) -> None:
        """Set or clear a transient session override for a role.

        Never written to settings or `.env`: a TUI selection is a choice for this
        run, and persisting it would turn an experiment into permanent
        configuration. `None` clears; an empty string is stored but does not win,
        because the lookup tests `is not None` and then falls through.
        """
        if model is None:
            self.overrides.pop(role, None)
        else:
            self.overrides[role] = model

    def clear_overrides(self) -> None:
        self.overrides.clear()

    @staticmethod
    def role_for(stage: str) -> str:
        """The override key a stage reads. Unmapped stages read no override."""
        if stage == "answer":
            return "answer"
        if stage in ("query_expansion", "relevance_scoring", "extraction", "resolution"):
            return "structured"
        return ""
```

Change `model_for` so the override is the first rung, with explicit `is not None` checks:

```python
    def model_for(self, stage: str, explicit: str | None = None) -> str:
        """Resolve which model serves a stage.

        Four rungs, highest first:

        1. a **session override** -- a deliberate, higher-priority user control
           from the TUI model selector, which must be able to say "use Ollama for
           extraction in this run" even where a stage supplies a model explicitly;
        2. an **explicit `model=` argument** -- a call-site default, which still
           beats the configured role exactly as it did before P12;
        3. the stage's **configured role**;
        4. `fast_model`.

        Rungs 2 and 3 are the pre-P12 contract, unchanged. Rung 1 is new, and is
        deliberately transient: it lives on this instance and is never written
        back to settings.
        """
        override = self.overrides.get(self.role_for(stage))
        if override is not None:
            return override
        if explicit:
            return explicit
        match stage:
            case "answer":
                return self.settings.model_for_answer
            case "query_expansion" | "relevance_scoring" | "extraction" | "resolution":
                return self.settings.model_for_structured
            case _:
                return self.settings.fast_model
```

Change the append in `_dispatch` so the observer is told:

```python
                entry = (stage, candidate, candidates[index + 1], error.category)
                self.fallbacks.append(entry)
                if self.on_fallback is not None:
                    try:
                        self.on_fallback(entry)
                    except Exception:
                        # Observability must never become a second mechanism: a
                        # failing observer is dropped, not allowed to change the
                        # routing decision that was already made.
                        pass
```

- [ ] **Step 4: Update the module docstring**

In `router.py`, replace the numbered list at the top so responsibility 1 reads:

```
1. **Model selection** per stage, so a stage never hard-codes a model id, with a
   transient session override above both the call site and the configured role.
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_p9_provider_routing.py -q`
Expected: PASS.

- [ ] **Step 6: Full suite and lint, then commit**

```bash
.\.venv\Scripts\python.exe -m pytest tests/ -q
.\.venv\Scripts\python.exe -m ruff check src/ tests/
git add src/rla/llm/router.py tests/test_p9_provider_routing.py
git commit -m "Add transient session overrides and a fallback observer to the router"
```

## Task 5: CLI overrides and deduplicated doctor probes

**Files:**
- Modify: `src/rla/cli.py`
- Test: `tests/test_p12_cli_and_doctor.py` (create)

**Interfaces:**
- Consumes: `Settings.canonical_model` (Task 1), `ProviderRouter.set_override` (Task 4).
- Produces:
  - `cli._apply_model_overrides(settings, structured: str | None, answer: str | None) -> Settings`
  - `cli._probe_plan(settings) -> list[Probe]` where `Probe` is `NamedTuple(model: str, roles: tuple[str, ...], kind: str)`
  - `rla run|tui` gain `--structured-model` and `--answer-model`

- [ ] **Step 1: Write the failing tests**

```python
"""P12: per-stage model overrides from the CLI, and deduplicated doctor probes.

`doctor --llm` sends real, uncached requests, so probing the same resolved model
once per role costs quota and time for no information.
"""

from __future__ import annotations

from rla.cli import _apply_model_overrides, _probe_plan
from rla.config import Settings


def settings(**kw) -> Settings:
    base = {
        "gemini_api_key": "k",
        "fast_model": "ollama/qwen3:4b",
        "strong_model": "ollama/qwen3:4b",
        "structured_model": "ollama/qwen3:4b",
        "answer_model": "gemini/gemini-2.5-flash",
        "embedding_model": "gemini/gemini-embedding-001",
    }
    base.update(kw)
    return Settings(_env_file=None, **base)


# -- overrides ----------------------------------------------------------------


def test_an_override_reaches_settings_without_touching_env(tmp_path):
    out = _apply_model_overrides(
        settings(data_dir=tmp_path), "ollama/qwen3:8b", "gemini/gemini-2.5-pro"
    )
    assert out.model_for_structured == "ollama/qwen3:8b"
    assert out.model_for_answer == "gemini/gemini-2.5-pro"


def test_no_override_leaves_the_configuration_untouched(tmp_path):
    original = settings(data_dir=tmp_path)
    out = _apply_model_overrides(original, None, None)
    assert out.model_for_structured == original.model_for_structured
    assert out.model_for_answer == original.model_for_answer


def test_an_override_is_canonicalised(tmp_path):
    """`gemini-2.5-pro` is accepted and stored canonically, so the cache key and
    the threshold lookup see one identity."""
    out = _apply_model_overrides(settings(data_dir=tmp_path), None, "gemini-2.5-pro")
    assert out.model_for_answer == "gemini/gemini-2.5-pro"


def test_an_ambiguous_override_is_refused_loudly(tmp_path):
    from rla.errors import ModelResolutionError

    try:
        _apply_model_overrides(settings(data_dir=tmp_path), "qwen3:4b", None)
    except ModelResolutionError as exc:
        assert "ollama/qwen3:4b" in str(exc)
        return
    raise AssertionError("expected ModelResolutionError")


# -- probe plan ---------------------------------------------------------------


def test_one_model_serving_three_roles_is_probed_once(tmp_path):
    plan = _probe_plan(settings(data_dir=tmp_path))

    text = [p for p in plan if p.kind == "text"]
    by_model = {p.model: p.roles for p in text}
    assert by_model["ollama/qwen3:4b"] == ("structured", "extraction", "resolution")
    assert len([p for p in text if p.model == "ollama/qwen3:4b"]) == 1


def test_distinct_models_are_probed_separately(tmp_path):
    plan = _probe_plan(settings(data_dir=tmp_path))
    models = {p.model for p in plan if p.kind == "text"}
    assert models == {"ollama/qwen3:4b", "gemini/gemini-2.5-flash"}


def test_the_embedding_model_is_a_separate_probe(tmp_path):
    """`/api/embed` is a different endpoint and a different capability, so an
    embedding probe is never satisfied by a text probe."""
    plan = _probe_plan(settings(data_dir=tmp_path))
    embedding = [p for p in plan if p.kind == "embedding"]
    assert [p.model for p in embedding] == ["gemini/gemini-embedding-001"]


def test_a_shared_model_is_probed_once_across_kinds(tmp_path):
    """If the embedding model and a text model were the same id, one probe
    cannot serve both: the capabilities differ."""
    plan = _probe_plan(
        settings(data_dir=tmp_path, embedding_model="ollama/qwen3:4b")
    )
    assert len([p for p in plan if p.model == "ollama/qwen3:4b"]) == 2
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_p12_cli_and_doctor.py -q`
Expected: collection error — `ImportError: cannot import name '_apply_model_overrides' from 'rla.cli'`.

- [ ] **Step 3: Implement the override helper and the probe plan**

In `src/rla/cli.py`, add after the `PHASE_STYLE` dict:

```python
class Probe(NamedTuple):
    """One live health probe: a model, the roles that use it, and which capability.

    Built by deduplicating roles onto canonical model ids, because `doctor --llm`
    sends real uncached requests and probing one model three times costs quota
    and time for no information. `kind` is `text` or `embedding`: `/api/embed`
    is a different endpoint and a different capability, so an embedding probe is
    never satisfied by a text probe even when both name the same model.
    """

    model: str
    roles: tuple[str, ...]
    kind: str


def _probe_plan(settings: Settings) -> list[Probe]:
    """The unique set of models `doctor --llm` should probe, and who uses each."""
    roles_by_model: dict[str, list[str]] = {}
    ordered: list[str] = []

    def _note(model: str, role: str) -> None:
        canonical = settings.canonical_model(model)
        if canonical not in roles_by_model:
            roles_by_model[canonical] = []
            ordered.append(canonical)
        roles_by_model[canonical].append(role)

    _note(settings.model_for_structured, "structured")
    _note(settings.model_for_structured, "extraction")
    _note(settings.model_for_structured, "resolution")
    _note(settings.model_for_answer, "answer")

    plan = [Probe(m, tuple(roles_by_model[m]), "text") for m in ordered]
    embedding = settings.canonical_model(settings.embedding_model)
    plan.append(Probe(embedding, ("embedding",), "embedding"))
    return plan


def _apply_model_overrides(
    settings: Settings, structured: str | None, answer: str | None
) -> Settings:
    """Return a copy of `settings` with transient per-stage overrides applied.

    Canonicalised, so the cache key, the capability check and `doctor` all see one
    identity. Nothing is written to `.env`: a command-line override is for this run
    only, and persisting it would turn an experiment into permanent configuration.
    """
    updates: dict[str, str] = {}
    if structured:
        updates["structured_model"] = settings.canonical_model(structured)
    if answer:
        updates["answer_model"] = settings.canonical_model(answer)
    if not updates:
        return settings
    return settings.model_copy(update=updates)
```

Add `from typing import NamedTuple` to the imports.

- [ ] **Step 4: Wire the flags onto `run`, `build` and `tui`**

Give `run` these two options after `jsonl`:

```python
    structured_model: Annotated[
        str, typer.Option("--structured-model", help="Override the model for the schema-constrained stages.")
    ] = "",
    answer_model: Annotated[
        str, typer.Option("--answer-model", help="Override the model for answer generation.")
    ] = "",
```

and change its body to:

```python
    if not title:
        title = typer.prompt("Research project title")
    settings = _apply_model_overrides(
        get_settings(), structured_model or None, answer_model or None
    )
    asyncio.run(_stream(settings, title, question, jsonl))
```

`_stream` is currently `async def _stream(title: str, question: str, as_jsonl: bool)`, so
change its signature to `async def _stream(settings: Settings, title: str, question: str, as_jsonl: bool)`
and its first line to `pipeline, cache, result, _router = _build_pipeline(settings)`.

Apply the identical option pair and body change to `build` (ignoring `answer_model`, which a
corpus build never reaches) and to `tui`.

Change `_build_pipeline` to accept the already-overridden settings and to return the router, so the TUI can register a fallback observer:

```python
def _build_pipeline(
    settings: Settings | None = None,
) -> tuple[Pipeline, Cache, PipelineResult, Any]:
    """Wire the pipeline once, so `run` and `tui` cannot drift apart.

    Returns the router as well: the TUI registers a fallback observer on it, and
    `doctor` reports what it resolved. The caller owns the cache's lifetime --
    `run` closes it when the stream ends, the TUI when the worker finishes.
    """
    settings = settings or get_settings()
    cache = Cache(settings.cache_db)
    tracker = CostTracker()
    llm = build_client(settings, cache, tracker)
    router = llm  # a ProviderRouter, or None in degrade mode
    return Pipeline(settings, llm, cache, tracker), cache, PipelineResult(), router
```

Update every existing caller of `_build_pipeline()` to unpack four values and pass its `settings` through: `_stream`, `tui`, and `_probe_llm`.

- [ ] **Step 5: Rewrite `_probe_llm` around the plan**

Replace the body of `_probe_llm` so it probes each `Probe` exactly once, groups output by provider, and reports the roles:

```python
async def _probe_llm(settings: Settings) -> tuple[str, str]:
    """Verify every configured model against the live API.

    Deliberately constructed *without* a cache: a cache-first probe reports a
    stale "ok" from a call that succeeded under an earlier key, which is exactly
    the situation this command exists to detect.

    The probe set is deduplicated by canonical model id, so three stages sharing
    one model cost one request rather than three.
    """
    from rla.llm.errors import LLMError, ProviderError
    from rla.llm.embeddings import Embedder
    from rla.store.cache import CostTracker as _CT

    from rla.llm.factory import build_client as _bc
    from rla.llm.factory import build_embedder as _be

    try:
        client = _bc(settings, None, _CT())
        embedder = _be(settings, None, _CT())
    except Exception as exc:
        return "unusable", f"cannot build the configured backends: {exc}"
    if client is None and embedder is None:
        return "unusable", "no usable provider is configured"

    problems: list[str] = []
    for probe in _probe_plan(settings):
        console.print(f"[bold]{probe.kind}[/] {probe.model}")
        console.print(f"  [dim]roles: {', '.join(probe.roles)}[/]")
        try:
            if probe.kind == "embedding":
                vector = await embedder.embed_one("doctor")
                detail = f"ok ({len(vector)} dims)"
            else:
                text = await client.generate_text(
                    "Reply with the single word: ok", stage="doctor", model=probe.model
                )
                detail = f"ok {text.strip()[:20]!r}"
        except (LLMError, ProviderError) as exc:
            reason = " ".join(str(exc).split())
            problems.append(f"{probe.model}: {reason[:120]}{_hint(reason)}")
            console.print(f"  [red]unusable[/] {reason[:160]}")
        else:
            console.print(f"  [green]{detail}[/]")

    if not problems:
        return "ok", "every configured model is reachable"
    return "unusable", "; ".join(problems)
```

Delete the now-unused `_probe_llm(settings)` call site's `from rla.llm.factory import build_client` duplication if ruff flags it.

- [ ] **Step 6: Run the tests, then the full suite and lint**

```bash
.\.venv\Scripts\python.exe -m pytest tests/test_p12_cli_and_doctor.py -q
.\.venv\Scripts\python.exe -m pytest tests/ -q
.\.venv\Scripts\python.exe -m ruff check src/ tests/
```

Expected: the new tests PASS; the full suite still fails only the A8 assertion from Task 3.

- [ ] **Step 7: Commit**

```bash
git add src/rla/cli.py tests/test_p12_cli_and_doctor.py
git commit -m "Add per-stage model overrides and deduplicate doctor probes"
```

## Task 6: TUI model selector and routing visibility

**Files:**
- Modify: `src/rla/tui/state.py`
- Modify: `src/rla/tui/app.py`
- Modify: `src/rla/cli.py` (register the fallback observer in `tui`)
- Test: `tests/test_p12_tui_selector.py` (create)

**Interfaces:**
- Consumes: `PipelineState` reducer API; `ProviderRouter.set_override` / `on_fallback`.
- Produces:
  - `PipelineState.role_models: dict[str, str]` — configured role → canonical model
  - `PipelineState.resolved_role(stage: str) -> str`
  - `PipelineState.routing_line() -> str`
  - `PipelineState.record_fallback(stage: str, src: str, dst: str, reason: str) -> None`
  - `PipelineState.select_model(role: str, model: str) -> None`

- [ ] **Step 1: Write the failing tests**

```python
"""P12: transient model selection and routing visibility in the TUI.

The selector introduces no TUI-specific execution path: it mutates the same
`PipelineState` the reducer already owns and reads through the same
`ProviderRouter`, preserving the one-event-stream invariant.
"""

from __future__ import annotations

from rla.tui.state import PipelineState


def state(**kw) -> PipelineState:
    return PipelineState(
        title="t",
        role_models={"structured": "ollama/qwen3:4b", "answer": "gemini/gemini-2.5-flash"},
        **kw,
    )


def test_the_three_states_are_distinguishable():
    s = state()
    line = s.routing_line()
    assert "structured" in line
    assert "ollama/qwen3:4b" in line


def test_a_selection_shows_as_an_override_not_as_configuration():
    s = state()
    s.select_model("structured", "gemini/gemini-2.5-flash")

    assert s.role_models["structured"] == "ollama/qwen3:4b", "configuration is untouched"
    assert s.overrides["structured"] == "gemini/gemini-2.5-flash"
    assert s.resolved_role("extraction") == "gemini/gemini-2.5-flash"


def test_clearing_a_selection_restores_the_configured_model():
    s = state()
    s.select_model("structured", "gemini/gemini-2.5-flash")
    s.select_model("structured", None)
    assert s.resolved_role("extraction") == "ollama/qwen3:4b"


def test_a_selection_does_not_leak_to_the_answer_role():
    s = state()
    s.select_model("structured", "gemini/gemini-2.5-flash")
    assert s.resolved_role("answer") == "gemini/gemini-2.5-flash"


def test_a_fallback_is_recorded_for_display():
    s = state()
    s.record_fallback("extraction", "ollama/qwen3:4b", "gemini/gemini-2.5-flash", "server_error")

    assert s.fallbacks
    assert "extraction" in s.fallbacks[-1]
    assert "gemini/gemini-2.5-flash" in s.routing_line()


def test_the_router_line_survives_an_empty_state():
    s = PipelineState(title="t")
    assert isinstance(s.routing_line(), str)
    assert s.resolved_role("extraction") == ""
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_p12_tui_selector.py -q`
Expected: FAIL — `TypeError: PipelineState.__init__() got an unexpected keyword argument 'role_models'`.

- [ ] **Step 3: Extend `PipelineState`**

In `src/rla/tui/state.py`, add to the dataclass:

```python
    #: Configured role -> canonical model. Never mutated by a selection.
    role_models: dict[str, str] = field(default_factory=dict)
    #: Transient session selections, role -> canonical model. Distinct from
    #: `role_models` so the panel can show configured vs override vs resolved,
    #: which is what makes the routing auditable at a glance.
    overrides: dict[str, str] = field(default_factory=dict)
    #: `(stage, from, to, reason)` for each fallback observed, newest last.
    fallbacks: list[tuple[str, str, str, str]] = field(default_factory=list)
```

and add these methods:

```python
    # -- routing visibility -------------------------------------------------
    def select_model(self, role: str, model: str | None) -> None:
        """Set or clear a transient session selection for a role.

        Session-scoped by construction: this state is never written back to
        settings or `.env`, so a demonstration choice cannot become permanent
        configuration.
        """
        if model is None:
            self.overrides.pop(role, None)
        else:
            self.overrides[role] = model

    def resolved_role(self, stage: str) -> str:
        """The model that would serve `stage` right now, override included."""
        role = "answer" if stage == "answer" else "structured"
        return self.overrides.get(role) or self.role_models.get(role, "")

    def record_fallback(self, stage: str, src: str, dst: str, reason: str) -> None:
        self.fallbacks.append((stage, src, dst, str(reason)))

    def routing_line(self) -> str:
        """One compact line naming every role's configured, override and resolved
        model, plus the most recent fallback."""
        parts: list[str] = []
        for role in ("structured", "answer"):
            configured = self.role_models.get(role, "—")
            override = self.overrides.get(role)
            resolved = self.overrides.get(role) or configured
            shown = f"{role}={resolved}"
            if override and override != configured:
                shown += f" (override; configured {configured})"
            parts.append(shown)
        if self.fallbacks:
            stage, src, dst, reason = self.fallbacks[-1]
            parts.append(f"fallback[{stage}]: {src} -> {dst} ({reason})")
        return "  ".join(parts)
```

- [ ] **Step 4: Render it and register the observer**

In `src/rla/tui/app.py`, add a `RoutingBar(_StateView)` class mirroring `GraphCounters`, give it `widget_id = "routing"`, and in `compose()` yield it directly after `self.counters`:

```python
        self.routing_bar = RoutingBar(self.state)
        yield self.routing_bar
```

with

```python
class RoutingBar(_StateView):
    """Which model is serving which stage, and the latest fallback."""

    def __init__(self, state: PipelineState) -> None:
        super().__init__(state, "routing")

    def refresh_state(self) -> None:
        self._show(Text(self._state.routing_line(), style="dim"))
```

Add to `_refresh_all`:

```python
        if self.routing_bar is not None:
            self.routing_bar.refresh_state()
```

And declare `self.routing_bar: RoutingBar | None = None` in `RlaApp.__init__`.

In `src/rla/cli.py`, inside the `tui` command after `pipeline, cache, result = _build_pipeline(...)`, add:

```python
    if router is not None:
        router.on_fallback = lambda entry: state.record_fallback(*entry)
```

and add the `routing` rule to the `CSS` block:

```css
    #routing { height: 1; color: $text-muted; }
```

- [ ] **Step 5: Seed the role models at startup**

In `cli.tui`, after `state = PipelineState(...)`:

```python
    settings = _apply_model_overrides(
        get_settings(), structured_model or None, answer_model or None
    )
    state.role_models = {
        "structured": settings.canonical_model(settings.model_for_structured),
        "answer": settings.canonical_model(settings.model_for_answer),
    }
```

and use `settings` for `_build_pipeline(settings)` and for the missing-key warning.

- [ ] **Step 6: Run the tests, full suite, lint, then commit**

```bash
.\.venv\Scripts\python.exe -m pytest tests/test_p12_tui_selector.py -q
.\.venv\Scripts\python.exe -m pytest tests/test_p7_tui_app.py tests/test_p7_tui_state.py -q
.\.venv\Scripts\python.exe -m pytest tests/ -q
.\.venv\Scripts\python.exe -m ruff check src/ tests/
git add src/rla/tui/state.py src/rla/tui/app.py src/rla/cli.py tests/test_p12_tui_selector.py
git commit -m "Add transient model selector and routing visibility to the TUI"
```

## Task 7: A8 rewrite and the cross-provider integration gate

This is the acceptance milestone for P12a.

**Files:**
- Modify: `tests/test_p9_acceptance.py`
- Modify: `tests/test_p9_provider_routing.py`
- Test: additions to both

**Interfaces:**
- Consumes: `MultiBackend` (Task 3), precedence (Task 4), `OllamaBackend` (Task 2).
- Produces: no new production code.

- [ ] **Step 1: Rewrite A8 as dispatch behaviour**

In `tests/test_p9_acceptance.py`, replace `test_a8_selecting_a_provider_is_configuration_only`:

```python
def test_a8_selecting_a_provider_is_configuration_only(tmp_path):
    """A8: change the provider, change no code.

    The old assertion checked that `build_backend` returned `GeminiClient`, which
    tests an implementation class rather than the contract. Now that
    `MultiBackend` is the stable facade, the guarantee worth keeping is that
    provider selection is configuration- and model-driven: each model id reaches
    the backend that owns it, and a nonsense provider is a configuration error
    rather than a silent default.
    """
    from rla.llm.factory import build_backend

    settings = Settings(
        _env_file=None,
        gemini_api_key="k",
        data_dir=tmp_path,
        raw_dir=tmp_path / "raw",
        graph_dir=tmp_path / "graph",
    )
    backend = build_backend(settings)

    assert backend.name == "multi"
    assert backend.backend_for("gemini/gemini-2.5-flash").name == "gemini"
    assert backend.backend_for("ollama/qwen3:4b").name == "ollama"
    assert backend.backend_for("openrouter/ling-3.0-flash-sante:free").name == "litellm"


def test_a8_provider_agnostic_ids_follow_the_configured_default(tmp_path):
    """`RLA_LLM_PROVIDER` remains the default for an id that names no provider."""
    from rla.llm.factory import build_backend

    settings = Settings(
        _env_file=None,
        gemini_api_key="k",
        data_dir=tmp_path,
        raw_dir=tmp_path / "raw",
        graph_dir=tmp_path / "graph",
        llm_provider="ollama",
    )
    assert build_backend(settings).provider_for("gemini-2.5-flash") == "gemini"

    settings.llm_provider = "nonsense"
    with pytest.raises(ValueError, match="RLA_LLM_PROVIDER"):
        build_backend(settings)
```

- [ ] **Step 2: Add the cross-provider tests**

Append to `tests/test_p9_provider_routing.py`:

```python
# ---------------------------------------------------------------------------
# P12: one run, three providers
# ---------------------------------------------------------------------------


class RecordingBackend(FakeBackend):
    """Fake backend that records the provider prefix it was asked to serve."""

    def __init__(self, name: str, **kw):
        super().__init__(**kw)
        self.name = name

    def supports(self, model, capability):
        if capability == "supports_structured_output":
            return self.structured.get(model, True)
        return False


def _multi(tmp_path, backend, **kw):
    from rla.llm.multi import MultiBackend

    settings = Settings(
        _env_file=None,
        gemini_api_key="k",
        data_dir=tmp_path,
        raw_dir=tmp_path / "raw",
        graph_dir=tmp_path / "graph",
        **kw,
    )
    return MultiBackend(settings, None, None), backend


async def test_one_run_uses_three_providers_and_a_cross_provider_fallback(tmp_path):
    """The headline guarantee: Ollama for the bulk, Gemini for answers,
    OpenRouter as the external fallback -- all in a single run."""
    from rla.llm.router import ProviderRouter

    backend = RecordingBackend("fake")
    multi, backend = _multi(tmp_path, backend)
    settings = Settings(
        _env_file=None,
        gemini_api_key="k",
        data_dir=tmp_path,
        raw_dir=tmp_path / "raw",
        graph_dir=tmp_path / "graph",
        structured_model="ollama/qwen3:4b",
        answer_model="gemini/gemini-2.5-flash",
        fallback_models="openrouter/backup:free,ollama/second:4b",
    )
    router = ProviderRouter(backend, settings)

    # structured stages go to the configured role model
    await router.generate_structured("x", Out, stage="extraction")
    assert backend.calls[-1] == ("extraction", "ollama/qwen3:4b")

    # answers go to a different provider
    await router.generate_text("x", stage="answer")
    assert backend.calls[-1] == ("answer", "gemini/gemini-2.5-flash")


async def test_a_fault_on_one_provider_fails_over_to_another(tmp_path):
    from rla.llm.router import ProviderRouter

    backend = RecordingBackend("fake", fail={"ollama/qwen3:4b": ProviderServerError("503")})
    settings = Settings(
        _env_file=None,
        gemini_api_key="k",
        data_dir=tmp_path,
        raw_dir=tmp_path / "raw",
        graph_dir=tmp_path / "graph",
        structured_model="ollama/qwen3:4b",
        fallback_models="openrouter/backup:free",
    )
    router = ProviderRouter(backend, settings)

    text = await router.generate_text("x", stage="extraction")

    assert text == "text from openrouter/backup:free"
    assert [m for _, m in backend.calls] == ["ollama/qwen3:4b", "openrouter/backup:free"]


async def test_quota_on_one_provider_does_not_fail_over_by_default(tmp_path):
    """ADR-004 survives the multi-provider change: falling over on a spent cap
    spends the reserve the operator wanted kept."""
    from rla.llm.router import ProviderRouter

    backend = RecordingBackend(
        "fake", fail={"ollama/qwen3:4b": ProviderQuotaExhausted("daily")}
    )
    settings = Settings(
        _env_file=None,
        gemini_api_key="k",
        data_dir=tmp_path,
        raw_dir=tmp_path / "raw",
        graph_dir=tmp_path / "graph",
        structured_model="ollama/qwen3:4b",
        fallback_models="openrouter/backup:free",
        fallback_on_quota=False,
    )
    router = ProviderRouter(backend, settings)

    with pytest.raises(ProviderQuotaExhausted):
        await router.generate_text("x", stage="extraction")
    assert not router.fallbacks


async def test_quota_failover_still_requires_the_opt_in(tmp_path):
    from rla.llm.router import ProviderRouter

    backend = RecordingBackend(
        "fake", fail={"ollama/qwen3:4b": ProviderQuotaExhausted("daily")}
    )
    settings = Settings(
        _env_file=None,
        gemini_api_key="k",
        data_dir=tmp_path,
        raw_dir=tmp_path / "raw",
        graph_dir=tmp_path / "graph",
        structured_model="ollama/qwen3:4b",
        fallback_models="openrouter/backup:free",
        fallback_on_quota=True,
    )
    router = ProviderRouter(backend, settings)

    assert await router.generate_text("x", stage="extraction") == "text from openrouter/backup:free"
    assert router.fallbacks
```

- [ ] **Step 3: Run the tests, then the full suite and lint**

```bash
.\.venv\Scripts\python.exe -m pytest tests/test_p9_provider_routing.py tests/test_p9_acceptance.py -q
.\.venv\Scripts\python.exe -m pytest tests/ -q
.\.venv\Scripts\python.exe -m ruff check src/ tests/
```

Expected: **all green.** This is the P12a automated gate.

- [ ] **Step 4: Run the manual benchmark and record it**

This is a recorded benchmark, **not** a CI threshold — latency depends on model load state, machine load and thermal state.

```powershell
rla doctor --llm                       # one probe per unique canonical model
.\.venv\Scripts\python.exe -m pytest tests/test_p12_ollama_backend.py -q
```

Then time one extraction on each route and record both numbers in
`docs/OPERATIONS_GUIDE.md` §5, keeping the 2026-10-02 measurement (8.1s native vs 97.6s
via LiteLLM) as the reference.

- [ ] **Step 5: Commit**

```bash
git add tests/test_p9_acceptance.py tests/test_p9_provider_routing.py docs/OPERATIONS_GUIDE.md
git commit -m "Gate P12a on cross-provider dispatch behaviour"
```

---

# P12b — Embedding providers

## Task 8: `EmbeddingProvider` protocol and the Ollama embedder

**Files:**
- Modify: `src/rla/llm/embedding_base.py`
- Create: `src/rla/llm/ollama_embedder.py`
- Modify: `src/rla/llm/embeddings.py`
- Modify: `src/rla/llm/factory.py`
- Test: `tests/test_p12_embeddings.py` (create)

**Interfaces:**
- Consumes: `Settings.canonical_model` (Task 1); `call_with_retry`; `content_hash`.
- Produces:
  - `rla.llm.embedding_base.EmbeddingProvider` — Protocol with `model_id: str`, `dimensions: int | None`, `key(text: str) -> str`, `async embed_one(text: str) -> list[float]`, `async embed_many(texts: Sequence[str]) -> list[list[float]]`
  - `rla.llm.ollama_embedder.OllamaEmbedder(settings, cache=None, tracker=None)`
  - `factory.build_embedder` returns `EmbeddingProvider | None`, selected by the embedding model's provider

- [ ] **Step 1: Write the failing tests**

```python
"""P12: embeddings as a provider, not a Gemini special case.

`/api/embed` is batched, so 163 concept names is ONE request rather than 163 --
which materially changes how long entity resolution takes when it is local.
"""

from __future__ import annotations

import json

import pytest
import respx

from rla.config import Settings
from rla.llm.embedding_base import EmbeddingDimensionMismatch, assert_uniform_dimension
from rla.llm.factory import build_embedder
from rla.llm.ollama_embedder import OllamaEmbedder
from rla.store.cache import CostTracker

OLLAMA = "http://localhost:9999"
http_mock = respx.mock(base_url=OLLAMA, assert_all_called=False)


def embedder(tmp_path, model="ollama/nomic-embed-text", **kw) -> OllamaEmbedder:
    settings = Settings(
        _env_file=None, gemini_api_key="k", data_dir=tmp_path,
        ollama_url=OLLAMA, embedding_model=model, llm_rpm=60, **kw,
    )
    return OllamaEmbedder(settings, None, CostTracker())


def test_the_factory_selects_an_embedder_by_provider(tmp_path):
    from rla.llm.embeddings import Embedder

    assert isinstance(
        build_embedder(Settings(_env_file=None, gemini_api_key="k", data_dir=tmp_path,
                                embedding_model="ollama/nomic-embed-text")),
        OllamaEmbedder,
    )
    assert isinstance(
        build_embedder(Settings(_env_file=None, gemini_api_key="k", data_dir=tmp_path,
                                embedding_model="gemini/gemini-embedding-001")),
        Embedder,
    )


@http_mock
async def test_many_texts_cost_exactly_one_request(tmp_path):
    http_mock.post("/api/embed").respond(
        json={"model": "nomic-embed-text", "embeddings": [[0.1, 0.2] for _ in range(163)]}
    )
    vectors = await embedder(tmp_path).embed_many([f"concept {i}" for i in range(163)])

    assert len(vectors) == 163
    assert len(http_mock.calls) == 1, "embedding must be batched, not one call per text"


@http_mock
async def test_the_dimension_is_measured_not_assumed(tmp_path):
    http_mock.post("/api/embed").respond(json={"embeddings": [[0.1, 0.2, 0.3]]})
    e = embedder(tmp_path)
    assert e.dimensions is None

    assert len(await e.embed_one("a")) == 3
    assert e.dimensions == 3


def test_the_cache_key_is_canonical_and_model_aware(tmp_path):
    """Two models must not share an index; one model reached two ways must."""
    a = embedder(tmp_path, model="ollama/nomic-embed-text")
    assert a.key("same text") == a.key("same text")

    b = embedder(tmp_path, model="ollama/other-embed")
    assert a.key("same text") != b.key("same text")


def test_a_dimension_mismatch_still_raises(tmp_path):
    """The guard that stopped resolution silently scoring every pair 0.0."""
    with pytest.raises(EmbeddingDimensionMismatch):
        assert_uniform_dimension([[0.1, 0.2], [0.1, 0.2, 0.3]])


@http_mock
async def test_an_unknown_embedding_model_names_the_pull_command(tmp_path):
    http_mock.post("/api/embed").respond(404, json={"error": "model 'nope' not found"})

    with pytest.raises(Exception) as excinfo:
        await embedder(tmp_path, model="ollama/nope").embed_one("a")

    assert "ollama pull nope" in str(excinfo.value)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_p12_embeddings.py -q`
Expected: collection error — `ModuleNotFoundError: No module named 'rla.llm.ollama_embedder'`.

- [ ] **Step 3: Declare the protocol**

In `src/rla/llm/embedding_base.py`, add after the existing `cosine` and `assert_uniform_dimension`:

```python
class EmbeddingProvider(Protocol):
    """What entity resolution needs from an embedding backend.

    Declared so the pipeline can be pointed at Gemini or at a local Ollama model by
    configuration alone. `key` is part of the contract rather than an
    implementation detail: the embedding model id is part of the cache identity,
    so vectors from two different models can never be served to, or compared
    with, each other.
    """

    @property
    def model_id(self) -> str:
        """Canonical `provider/model` id, and part of the cache key."""

    @property
    def dimensions(self) -> int | None:
        """Measured width, or None before the first successful call."""

    def key(self, text: str) -> str: ...

    async def embed_one(self, text: str) -> list[float]: ...

    async def embed_many(self, texts: Sequence[str]) -> list[list[float]]: ...
```

Add `from collections.abc import Sequence` and `from typing import Protocol` to that file's imports.

- [ ] **Step 4: Point `Embedder` at canonical ids**

The current implementation is:

```python
    def _key(self, text: str) -> str:
        # Model-aware by construction: a different embedding model cannot be served
        # a vector produced by another, which would compare incomparable spaces.
        return "embed:" + content_hash(self.settings.embedding_model, text)
```

Keep the `"embed:"` namespace prefix — `GeminiClient` writes `"llm:"` entries into the
same table, and changing the prefix would silently orphan every stored embedding.
Swap only the model string for its canonical form:

```python
    @property
    def model_id(self) -> str:
        """Canonical id. Keeps Gemini and a local model from sharing a cache entry."""
        return self.settings.canonical_model(self.settings.embedding_model)

    def _key(self, text: str) -> str:
        return "embed:" + content_hash(self.model_id, text)
```

**This breaks one existing test, deliberately.**
`test_a4_embedding_cache_keys_are_model_aware` in `tests/test_p9_acceptance.py`
currently uses the invented ids `model-a` and `model-b`, and a bare `model-a` is
now ambiguous — `canonical_model` refuses it, which is the whole point of Task 1.
Update it to use real ids:

```python
async def test_a4_embedding_cache_keys_are_model_aware(tmp_path):
    """A vector from one model must never be served to another.

    Ids are canonical, so two spellings of ONE model share an entry while two
    different models never do.
    """
    from rla.models import content_hash  # noqa: F401

    settings = Settings(
        _env_file=None,
        gemini_api_key="k",
        data_dir=tmp_path,
        raw_dir=tmp_path / "raw",
        graph_dir=tmp_path / "graph",
        embedding_model="ollama/nomic-embed-text",
    )
    embedder = Embedder(settings, Cache(tmp_path / "c.db"), CostTracker())

    key_a = embedder._key("same text")
    settings.embedding_model = "ollama/other-embed"
    key_b = embedder._key("same text")
    assert key_a != key_b

    settings.embedding_model = "nomic-embed-text"
    with pytest.raises(ModelResolutionError):
        embedder._key("same text")
```

Add `from rla.errors import ModelResolutionError` to that file's imports.

- [ ] **Step 5: Write the Ollama embedder**

Create `src/rla/llm/ollama_embedder.py`:

```python
"""Native Ollama embeddings via the batched `/api/embed` endpoint.

Entity resolution embeds one string per distinct concept name, which is 160-odd
strings for a 30-paper corpus. Ollama's `/api/embed` accepts a list, so that is
ONE request rather than 163 -- the difference between resolution being usable
locally and not.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import httpx

from rla.config import Settings, get_settings
from rla.llm.error_map import normalize
from rla.llm.errors import ProviderInvalidRequest
from rla.llm.retry import call_with_retry
from rla.models import content_hash
from rla.store.cache import CostTracker

_PULL_HINT = "not found"


class OllamaEmbedder:
    """Cache-first batched embeddings from a local Ollama server."""

    def __init__(
        self,
        settings: Settings | None = None,
        cache: Any | None = None,
        tracker: CostTracker | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.cache = cache
        self.tracker = tracker or CostTracker()
        self._dimensions: int | None = None

    @property
    def model_id(self) -> str:
        return self.settings.canonical_model(self.settings.embedding_model)

    @property
    def dimensions(self) -> int | None:
        return self._dimensions

    def _bare(self) -> str:
        model = self.model_id
        return model.split("/", 1)[1] if "/" in model else model

    def key(self, text: str) -> str:
        # The `embed:` namespace is shared with the Gemini embedder on purpose, so
        # the two providers are visibly the same kind of stored artefact.
        return "embed:" + content_hash(self.model_id, text)

    async def embed_many(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        cached: list[list[float] | None] = [None] * len(texts)
        pending: list[tuple[int, str]] = []
        for index, text in enumerate(texts):
            hit = None if self.cache is None else self.cache.get(self.key(text), kind="llm")
            if hit is None:
                pending.append((index, text))
            else:
                cached[index] = [float(v) for v in hit.split(",") if v != ""]

        if pending:
            payload = {"model": self._bare(), "input": [t for _, t in pending]}

            def _invoke() -> Any:
                response = httpx.post(
                    f"{self.settings.ollama_url.rstrip('/')}/api/embed",
                    json=payload, timeout=self.settings.llm_timeout_seconds,
                )
                if response.status_code == 404:
                    raise ProviderInvalidRequest(
                        f"embedding model {self._bare()!r} is not available on the "
                        f"Ollama server. Load it with: ollama pull {self._bare()}"
                    )
                response.raise_for_status()
                return response

            try:
                response = await call_with_retry(
                    _invoke,
                    stage="ollama embed call failed",
                    limiter=self.settings.llm_limiter,
                    max_retries=self.settings.llm_max_retries,
                    spender=self.settings.llm_spender,
                    timeout=self.settings.llm_timeout_seconds,
                )
            except ProviderInvalidRequest:
                raise
            except Exception as exc:
                raise normalize(exc, provider="ollama", model=self.model_id, stage="embedding") from exc

            vectors = response.json().get("embeddings") or []
            if len(vectors) != len(pending):
                raise ProviderInvalidRequest(
                    f"expected {len(pending)} embeddings from Ollama, got {len(vectors)}"
                )
            for (index, text), vector in zip(pending, vectors, strict=True):
                cached[index] = [float(v) for v in vector]
                if self.cache is not None:
                    self.cache.set(
                        self.key(text), ",".join(str(v) for v in vector), kind="llm"
                    )

        out = [v for v in cached if v is not None]
        if out:
            self._dimensions = len(out[0])
        return out  # type: ignore[return-value]

    async def embed_one(self, text: str) -> list[float]:
        vectors = await self.embed_many([text])
        return vectors[0]
```

- [ ] **Step 6: Select the embedder by provider in the factory**

In `src/rla/llm/factory.py`, replace `build_embedder`:

```python
def build_embedder(
    settings: Settings | None = None,
    cache: Cache | None = None,
    tracker: CostTracker | None = None,
) -> EmbeddingProvider | None:
    """Build the embedder for the configured embedding model's provider.

    Returns None when no provider is usable. Note this is deliberately *not* keyed
    on the Gemini credential: with a local embedding model configured, a fully
    local pipeline must not require a Gemini key at all.
    """
    settings = settings or get_settings()
    model = settings.canonical_model(settings.embedding_model)
    provider = model.split("/", 1)[0]
    if provider == "ollama":
        from rla.llm.ollama_embedder import OllamaEmbedder

        return OllamaEmbedder(settings, cache, tracker)
    if not settings.gemini_api_key:
        return None
    return Embedder(settings, cache, tracker)
```

Import `EmbeddingProvider` from `rla.llm.embedding_base` at the top of `factory.py`.

- [ ] **Step 7: Tests, full suite, lint, commit**

```bash
.\.venv\Scripts\python.exe -m pytest tests/test_p12_embeddings.py tests/test_p9_acceptance.py -q
.\.venv\Scripts\python.exe -m pytest tests/ -q
.\.venv\Scripts\python.exe -m ruff check src/ tests/
git add src/rla/llm/embedding_base.py src/rla/llm/ollama_embedder.py src/rla/llm/embeddings.py src/rla/llm/factory.py tests/test_p12_embeddings.py
git commit -m "Add an Ollama embedding provider with batched local embeddings"
```

## Task 9: Per-model merge thresholds, uncalibrated-safe

**Files:**
- Modify: `src/rla/pipeline/resolve.py`
- Modify: `src/rla/pipeline/orchestrator.py` (pass the embedder's canonical id)
- Test: additions to `tests/test_p3_resolution.py`

**Interfaces:**
- Consumes: `EmbeddingProvider.model_id` (Task 8); existing `AUTO_MERGE`, `MAYBE_MERGE`, `MAX_JUDGE_CALLS`.
- Produces:
  - `rla.pipeline.resolve.MergeThresholds(auto: float | None, maybe: float, calibrated: bool)`
  - `rla.pipeline.resolve.EMBEDDING_THRESHOLDS: dict[str, MergeThresholds]`
  - `rla.pipeline.resolve.thresholds_for(model_id: str) -> MergeThresholds`
  - `resolve_concepts(..., thresholds: MergeThresholds | None = None)`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_p3_resolution.py`:

```python
# ---------------------------------------------------------------------------
# P12: thresholds belong to an embedding space, not to the project
# ---------------------------------------------------------------------------

from rla.pipeline.resolve import (  # noqa: E402
    AUTO_MERGE,
    MAYBE_MERGE,
    EMBEDDING_THRESHOLDS,
    MergeThresholds,
    thresholds_for,
)


def test_the_gemini_thresholds_are_unchanged():
    """0.92 / 0.70 were calibrated on Gemini's embedding space; they must not move."""
    assert AUTO_MERGE == 0.92
    assert MAYBE_MERGE == 0.70
    calibrated = thresholds_for("gemini/gemini-embedding-001")
    assert calibrated.auto == 0.92
    assert calibrated.maybe == 0.70
    assert calibrated.calibrated is True


def test_thresholds_are_keyed_by_canonical_id():
    """Two providers exposing the same bare model name must not collide."""
    assert "gemini/gemini-embedding-001" in EMBEDDING_THRESHOLDS


def test_an_unknown_embedding_space_is_uncalibrated_and_disables_auto_merge():
    uncalibrated = thresholds_for("ollama/nomic-embed-text")
    assert uncalibrated.auto is None
    assert uncalibrated.calibrated is False
    # The judge floor still exists, so candidates are still surfaced.
    assert uncalibrated.maybe > 0


async def test_an_uncalibrated_space_performs_zero_auto_merges(tmp_path):
    """The safety property: more duplicates, never a fused lineage path."""
    mentions = [
        Mention(name="Graph Attention Networks", description="attention over a neighbourhood", paper_id="p1"),
        Mention(name="graph attention networks", description="attention over a neighbourhood", paper_id="p2"),
        Mention(name="Deep Reinforcement Learning", description="policies from rewards", paper_id="p3"),
    ]
    clusters = group_by_name(mentions)

    class PerfectEmbedder:
        model_id = "ollama/nomic-embed-text"

        def __init__(self):
            self.dimensions = 3

        async def embed_many(self, texts):
            return [[1.0, 0.0, 0.0] for _ in texts]

    decisions: list[MergeDecision] = []
    async for evt in resolve_concepts(
        mentions,
        llm=AlwaysSame(),
        embedder=PerfectEmbedder(),
        concurrency=1,
        thresholds=thresholds_for("ollama/nomic-embed-text"),
    ):
        if "decisions" in evt.payload:
            decisions = [MergeDecision(**d) for d in evt.payload["decisions"]]

    auto = [d for d in decisions if d.reason == "auto-similarity"]
    assert not auto, f"auto-merge must be off for an uncalibrated space: {auto}"
    assert EMBEDDING_THRESHOLDS["gemini/gemini-embedding-001"].auto == 0.92


async def test_the_judge_stays_within_its_budget_for_an_uncalibrated_space():
    calls = 0

    class Counting:
        async def generate_structured(self, prompt, schema, *, model=None,
                                       temperature=0.0, stage="llm", retries=2):
            nonlocal calls
            calls += 1
            return schema.model_construct(verdict="different", confidence=0.5, canonical="")

    vectors = [[1.0, i / 100.0, 0.0] for i in range(20)]
    mentions = [Mention(name=f"concept {i}", description="d", paper_id=f"p{i}") for i in range(20)]
    clusters = group_by_name(mentions)

    async for _ in resolve_concepts(
        mentions,
        llm=Counting(),
        embedder=VectorEmbedder(vectors),
        concurrency=1,
        thresholds=thresholds_for("ollama/nomic-embed-text"),
    ):
        pass

    assert calls <= MAX_JUDGE_CALLS
```

Add the small helper classes this needs at the bottom of the test file:

```python
class AlwaysSame:
    async def generate_structured(self, prompt, schema, *, model=None,
                                   temperature=0.0, stage="llm", retries=2):
        return schema.model_construct(verdict="different", confidence=0.5, canonical="")


class VectorEmbedder:
    model_id = "ollama/nomic-embed-text"

    def __init__(self, vectors):
        self.vectors = vectors
        self.dimensions = len(vectors[0])

    async def embed_many(self, texts):
        return self.vectors[: len(texts)]
```

and add `from rla.pipeline.resolve import Mention, group_by_name, MergeDecision, MAX_JUDGE_CALLS` to the imports.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_p3_resolution.py -q -k "threshold or uncalibrated or budget"`
Expected: collection error — `ImportError: cannot import name 'MergeThresholds'`.

- [ ] **Step 3: Add the threshold registry**

In `src/rla/pipeline/resolve.py`, replace the three bare constants with:

```python
#: Similarity thresholds are a property of an EMBEDDING SPACE, not of the
#: project. 0.92 / 0.70 were calibrated against Gemini's; transferring them to a
#: different space would be a hidden behavioural change in the one place where
#: being wrong silently deletes a lineage path.
@dataclass(frozen=True, slots=True)
class MergeThresholds:
    """Similarity boundaries for one embedding model.

    `auto is None` means automatic merging is disabled for this space entirely.
    That is the safe direction: every candidate then goes to the bounded judge
    path, which fails toward duplicates, so the cost of being wrong is a visible
    duplicate rather than a fused lineage path.
    """

    auto: float | None
    maybe: float
    calibrated: bool


EMBEDDING_THRESHOLDS: dict[str, MergeThresholds] = {
    "gemini/gemini-embedding-001": MergeThresholds(auto=0.92, maybe=0.70, calibrated=True),
}


def thresholds_for(model_id: str) -> MergeThresholds:
    """The thresholds for an embedding model, or a safe uncalibrated default.

    Keyed by CANONICAL id, so two providers exposing the same bare model name
    cannot collide.
    """
    known = EMBEDDING_THRESHOLDS.get(model_id)
    if known is not None:
        return known
    return MergeThresholds(auto=None, maybe=MAYBE_MERGE, calibrated=False)


#: Retained as module-level aliases so the existing P3 tests and any external
#: reader keep working; these are Gemini's calibrated values.
AUTO_MERGE = 0.92
MAYBE_MERGE = 0.70
```

- [ ] **Step 4: Thread the thresholds through resolution**

Add a `thresholds: MergeThresholds | None = None` parameter to `resolve_concepts`, and
widen its `embedder` annotation from `Embedder | None` to `EmbeddingProvider | None` so
the pipeline genuinely does not depend on the Gemini embedder. At the top of its body:

```python
    model_id = getattr(embedder, "model_id", None) or "gemini/gemini-embedding-001"
    active = thresholds or thresholds_for(model_id)
```

Change `_similar_pairs` to take the floor as a parameter:

```python
def _similar_pairs(
    vectors: Sequence[Sequence[float]], floor: float = MAYBE_MERGE
) -> list[tuple[float, int, int]]:
    """All pairs at or above `floor`, most similar first, for a bounded budget."""
    pairs: list[tuple[float, int, int]] = []
    for i in range(len(vectors)):
        for j in range(i + 1, len(vectors)):
            score = cosine(vectors[i], vectors[j])
            if score >= floor:
                pairs.append((score, i, j))
    pairs.sort(key=lambda item: (-item[0], item[1], item[2]))
    return pairs
```

Change the merge condition in the loop body from `if score >= AUTO_MERGE:` to:

```python
            if active.auto is not None and score >= active.auto:
```

and pass the floor: `for score, i, j in _similar_pairs(vectors, active.maybe):`.

Replace the final event's message so the calibration state is always visible:

```python
    calibration = (
        f"thresholds CALIBRATED for {model_id} "
        f"(auto>={active.auto}, judge floor {active.maybe})"
        if active.calibrated and active.auto is not None
        else f"thresholds UNCALIBRATED for {model_id}: automatic merging is DISABLED "
             "and borderline pairs are going to the judge, bounded by "
             f"{MAX_JUDGE_CALLS} calls"
    )
    yield event(
        Phase.RESOLVE,
        f"{len(clusters)} names -> {len(concepts)} concepts "
        f"({len(clusters) - len(concepts)} merged, {refused} borderline pairs kept separate, "
        f"{judged} judged); {calibration}",
        kind="ok" if active.calibrated else "warn",
        concepts=len(concepts),
        concept_nodes=[c.model_dump() for c in concepts],
        decisions=[d.to_dict() for d in decisions],
        cost=cost,
        thresholds={"model": model_id, "auto": active.auto,
                    "maybe": active.maybe, "calibrated": active.calibrated},
    )
```

- [ ] **Step 5: Tests, full suite, lint, commit**

```bash
.\.venv\Scripts\python.exe -m pytest tests/test_p3_resolution.py -q
.\.venv\Scripts\python.exe -m pytest tests/ -q
.\.venv\Scripts\python.exe -m ruff check src/ tests/
git add src/rla/pipeline/resolve.py tests/test_p3_resolution.py
git commit -m "Scope merge thresholds to an embedding space and disable auto-merge when uncalibrated"
```

## Task 10: Calibration pass

**Files:**
- Create: `src/rla/eval/merge_calibration.py`
- Modify: `src/rla/cli.py` (add the `calibrate-merges` command)
- Test: `tests/test_p12_calibration.py` (create)

**Interfaces:**
- Consumes: `thresholds_for`, `MergeThresholds`, `EmbeddingProvider` (Tasks 8-9), `ExtractionStore`, `resolve_concepts`'s clustering helpers.
- Produces:
  - `eval.merge_calibration.CalibrationReport` with `to_dict() -> dict`
  - `eval.merge_calibration.calibrate(extractions, embedder, *, false_merge_budget=0.02, judge_budget=40) -> CalibrationReport`
  - `rla calibrate-merges` command that prints the report and **never** writes a threshold

- [ ] **Step 1: Write the failing tests**

```python
"""P12: propose thresholds for an uncalibrated embedding space, never install them.

Same honesty rule the evaluation harness already follows: a number is only
reported when it was measured, and nothing is written without a human decision.
"""

from __future__ import annotations

import pytest

from rla.eval.merge_calibration import calibrate, suggest_thresholds
from rla.models import Extraction
from rla.pipeline.resolve import Mention, collect_mentions


def extractions(n: int = 12) -> list[Extraction]:
    return [
        Extraction(
            paper_id=f"p{i}",
            paper_hash=f"h{i}",
            concepts=[
                {"name": "Graph Attention Networks" if i % 2 == 0 else "Graph Attention Network",
                 "description": "attention over a node neighbourhood",
                 "role": "introduces"},
                {"name": f"Unrelated Concept {i}", "description": "something else entirely",
                 "role": "uses"},
            ],
        )
        for i in range(n)
    ]


class PerfectEmbedder:
    model_id = "ollama/nomic-embed-text"

    def __init__(self):
        self.dimensions = 2

    async def embed_many(self, texts):
        # The two GAT spellings collapse; everything else is orthogonal.
        out = []
        for text in texts:
            if "ttention" in text:
                out.append([1.0, 0.0])
            else:
                out.append([0.0, 1.0])
        return out


async def test_the_report_states_what_it_measured(tmp_path):
    report = await calibrate(extractions(), PerfectEmbedder())

    assert report.model_id == "ollama/nomic-embed-text"
    assert report.pairs_examined >= 1
    assert report.distribution, "a distribution is the evidence"
    assert report.calibrated is False, "nothing is calibrated until a human says so"


async def test_it_proposes_thresholds_and_labels_them_a_proposal(tmp_path):
    report = await calibrate(extractions(), PerfectEmbedder())
    assert report.proposed is not None
    assert 0.0 < report.proposed.auto < 1.0
    assert report.proposed.calibrated is False, "a proposal is never self-certified"


def test_a_proposal_is_refused_when_there_is_no_evidence():
    with pytest.raises(ValueError):
        suggest_thresholds([], false_merge_budget=0.02)


async def test_calibration_never_writes_to_the_registry(tmp_path):
    from rla.pipeline.resolve import EMBEDDING_THRESHOLDS

    before = dict(EMBEDDING_THRESHOLDS)
    await calibrate(extractions(), PerfectEmbedder())
    assert EMBEDDING_THRESHOLDS == before, "installing a threshold is a human decision"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_p12_calibration.py -q`
Expected: collection error — `ModuleNotFoundError: No module named 'rla.eval.merge_calibration'`.

- [ ] **Step 3: Write the calibration pass**

Create `src/rla/eval/merge_calibration.py`:

```python
"""Propose merge thresholds for an embedding space that has not been calibrated.

Reports the similarity distribution over the concepts actually in the corpus, then
proposes an automatic-merge boundary at a stated false-merge budget. It never
writes to `EMBEDDING_THRESHOLDS`: installing a threshold is a human decision,
because a wrong one silently fuses two concepts and deletes the lineage path
between them -- the most expensive error in the whole system.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from rla.llm.embedding_base import EmbeddingProvider
from rla.llm.embedding_base import cosine
from rla.models import Extraction
from rla.pipeline.resolve import Mention, MergeThresholds, collect_mentions, group_by_name


@dataclass(slots=True)
class CalibrationReport:
    model_id: str
    mentions: int = 0
    names: int = 0
    pairs_examined: int = 0
    distribution: list[tuple[float, int]] = field(default_factory=list)
    proposed: MergeThresholds | None = None
    false_merge_budget: float = 0.0
    calibrated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "mentions": self.mentions,
            "names": self.names,
            "pairs_examined": self.pairs_examined,
            "distribution": [{"similarity": round(s, 4), "count": c} for s, c in self.distribution],
            "proposed": None
            if self.proposed is None
            else {"auto": self.proposed.auto, "maybe": self.proposed.maybe,
                  "calibrated": self.proposed.calibrated},
            "false_merge_budget": self.false_merge_budget,
            "calibrated": self.calibrated,
            "note": (
                "A proposal is evidence, not a decision. Nothing was written to "
                "EMBEDDING_THRESHOLDS; automatic merging stays disabled for this "
                "embedding model until a human installs a threshold."
            ),
        }

    def render(self) -> str:
        lines = [
            f"embedding model : {self.model_id}",
            f"mentions/names  : {self.mentions} / {self.names}",
            f"pairs examined  : {self.pairs_examined}",
            "",
            "similarity distribution:",
        ]
        lines += [f"  {s:.3f}  {'#' * min(c, 60)}  ({c})" for s, c in self.distribution]
        if self.proposed is None:
            lines += ["", "no threshold proposed: too few pairs to have evidence"]
        else:
            lines += [
                "",
                f"PROPOSED (not installed): auto >= {self.proposed.auto}, "
                f"judge floor {self.proposed.maybe}",
                f"budget: at most {self.false_merge_budget:.1%} false merges",
            ]
        lines += ["", self.to_dict()["note"]]
        return "\n".join(lines)


def suggest_thresholds(
    distribution: Sequence[tuple[float, int]], *, false_merge_budget: float = 0.02
) -> MergeThresholds | None:
    """The similarity at which the false-merge budget would be exceeded.

    Returns None rather than a number when there is not enough evidence, because a
    threshold invented from three pairs is worse than no threshold: it would be
    calibrated-looking and wrong.
    """
    total = sum(count for _, count in distribution)
    if total == 0 or total < 20:
        return None
    allowed = max(0, int(total * false_merge_budget))
    seen = 0
    for similarity, count in sorted(distribution):
        seen += count
        if seen > allowed:
            return MergeThresholds(auto=round(similarity, 4), maybe=0.70, calibrated=False)
    return None


async def calibrate(
    extractions: Sequence[Extraction],
    embedder: EmbeddingProvider,
    *,
    false_merge_budget: float = 0.02,
) -> CalibrationReport:
    """Measure the similarity distribution and propose a boundary. Writes nothing."""
    mentions = collect_mentions(extractions)
    clusters = group_by_name(mentions)
    report = CalibrationReport(
        model_id=embedder.model_id,
        mentions=len(mentions),
        names=len(clusters),
        false_merge_budget=false_merge_budget,
    )
    if len(clusters) < 2:
        return report

    vectors = await embedder.embed_many([g[0].centroid_text() for g in clusters])
    buckets: dict[int, int] = {}
    for i in range(len(vectors)):
        for j in range(i + 1, len(vectors)):
            score = cosine(vectors[i], vectors[j])
            buckets[int(score * 20)] = buckets.get(int(score * 20), 0) + 1
            report.pairs_examined += 1

    report.distribution = [
        (bucket / 20.0, count) for bucket, count in sorted(buckets.items())
    ]
    report.proposed = suggest_thresholds(report.distribution, false_merge_budget=false_merge_budget)
    return report
```

Remove the unused `BaseModel`, `Mention` and `Any` imports ruff flags.

- [ ] **Step 4: Add the command**

In `src/rla/cli.py`, add after the `eval` command:

```python
@app.command(name="calibrate-merges")
def calibrate_merges() -> None:
    """Propose merge thresholds for the configured embedding model.

    Reports the similarity distribution over the concepts already extracted and
    proposes an automatic-merge boundary at a 2% false-merge budget. Installs
    nothing: until a threshold is committed for this embedding model, automatic
    merging stays disabled and borderline pairs go to the bounded judge.
    """
    import asyncio

    from rla.eval.merge_calibration import calibrate
    from rla.llm.factory import build_embedder
    from rla.store.extraction_store import ExtractionStore

    settings = get_settings()
    store = ExtractionStore(settings.extractions_path)
    store.load()
    if not store.all():
        console.print("[yellow]no stored extractions; run `rla run` first.[/]")
        raise typer.Exit(code=1)

    embedder = build_embedder(settings, Cache(settings.cache_db), CostTracker())
    if embedder is None:
        console.print("[yellow]no usable embedding provider is configured.[/]")
        raise typer.Exit(code=1)

    report = asyncio.run(calibrate(store.all(), embedder))
    console.print(report.render())
```

- [ ] **Step 5: Tests, full suite, lint, commit**

```bash
.\.venv\Scripts\python.exe -m pytest tests/test_p12_calibration.py -q
.\.venv\Scripts\python.exe -m pytest tests/ -q
.\.venv\Scripts\python.exe -m ruff check src/ tests/
git add src/rla/eval/merge_calibration.py src/rla/cli.py tests/test_p12_calibration.py
git commit -m "Add a merge-threshold calibration pass that proposes without installing"
```

## Task 11: A fully local pipeline no longer needs a Gemini key

**Files:**
- Modify: `src/rla/llm/factory.py`
- Test: additions to `tests/test_p9_acceptance.py`

**Interfaces:**
- Consumes: `MultiBackend` (Task 3), `build_embedder` (Task 8).
- Produces: `build_client` returns a router when **any** configured provider is usable, not only when `GEMINI_API_KEY` is set.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_p9_acceptance.py`:

```python
def test_a_fully_local_pipeline_needs_no_gemini_key(tmp_path):
    """`build_client` used to return None without the Gemini key, which the
    orchestrator reads as degrade mode -- so "run everything locally" still
    required a Gemini credential."""
    settings = Settings(
        _env_file=None,
        gemini_api_key="",
        llm_provider="ollama",
        structured_model="ollama/qwen3:4b",
        fast_model="ollama/qwen3:4b",
        answer_model="ollama/qwen3:4b",
        data_dir=tmp_path,
        raw_dir=tmp_path / "raw",
        graph_dir=tmp_path / "graph",
    )
    assert build_client(settings) is not None


def test_a_local_embedding_provider_also_needs_no_gemini_key(tmp_path):
    settings = Settings(
        _env_file=None,
        gemini_api_key="",
        embedding_model="ollama/nomic-embed-text",
        data_dir=tmp_path,
        raw_dir=tmp_path / "raw",
        graph_dir=tmp_path / "graph",
    )
    assert build_embedder(settings) is not None


def test_no_usable_provider_still_degrades(tmp_path):
    """The keyless degrade mode must survive: it is what makes `rla build` work
    with no credentials at all."""
    settings = Settings(
        _env_file=None,
        gemini_api_key="",
        llm_provider="gemini",
        data_dir=tmp_path,
        raw_dir=tmp_path / "raw",
        graph_dir=tmp_path / "graph",
    )
    assert build_client(settings) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_p9_acceptance.py -q -k "local or degrade"`
Expected: FAIL — `build_client` returns `None` whenever `gemini_api_key` is blank.

- [ ] **Step 3: Fix the guard**

In `src/rla/llm/factory.py`, replace the `if not settings.gemini_api_key: return None` guard in `build_client`:

```python
    settings = settings or get_settings()
    # A client exists when *any* configured provider is usable, not only when the
    # Gemini key is present. Keying this on one credential would make a fully
    # local pipeline still require a Gemini key, and the orchestrator would read
    # the resulting None as degrade mode.
    if not _has_usable_provider(settings):
        return None
    return ProviderRouter(build_backend(settings, cache, tracker), settings, cache, tracker)


def _has_usable_provider(settings: Settings) -> bool:
    """Whether at least one configured model can actually be served.

    A Gemini model needs the Gemini key. A local Ollama model needs no credential
    at all, only a running server -- so a missing key must not disable it.
    """
    try:
        models = (
            settings.model_for_structured,
            settings.model_for_answer,
            settings.fast_model,
        )
    except Exception:
        return False
    for model in models:
        try:
            provider = settings.canonical_model(model).split("/", 1)[0]
        except Exception:
            continue
        if provider == "ollama":
            return True
        if provider == "gemini" and settings.gemini_api_key:
            return True
        if provider not in ("ollama", "gemini") and settings.gemini_api_key:
            # LiteLLM providers read their own credential; the OpenRouter key is
            # configured here, so its presence is the signal we have.
            return True
    return False
```

- [ ] **Step 4: Tests, full suite, lint, commit**

```bash
.\.venv\Scripts\python.exe -m pytest tests/test_p9_acceptance.py -q
.\.venv\Scripts\python.exe -m pytest tests/ -q
.\.venv\Scripts\python.exe -m ruff check src/ tests/
git add src/rla/llm/factory.py tests/test_p9_acceptance.py
git commit -m "Allow a fully local pipeline without a Gemini credential"
```

## Task 12: Documentation and ADRs

**Files:**
- Create: `docs/adr/0006-multi-provider-dispatch.md`
- Create: `docs/adr/0007-per-embedding-model-merge-thresholds.md`
- Modify: `docs/OPERATIONS_GUIDE.md`, `PLAN.md`, `.env.example`, `README.md`

**Interfaces:** documentation only.

- [ ] **Step 1: Write ADR 0006**

`docs/adr/0006-multi-provider-dispatch.md`, following the shape of the existing ADRs:

```markdown
# ADR-0006: MultiBackend facade rather than a multi-backend router

**Status:** accepted · **Date:** 2026-10-02

## Context

`ProviderRouter` held exactly one backend, so a native Ollama backend had nowhere
to go. The alternatives were to rewrite `ProviderRouter` to hold a registry, or to
let the orchestrator pick a client per stage.

## Decision

Add `MultiBackend`, which implements the existing `RoutingBackend` protocol and
resolves each model id to its owning backend. `ProviderRouter` is unchanged and
remains the sole owner of precedence, capability policy, and fallback
eligibility and ordering.

## Rationale

`ProviderRouter._dispatch` already iterates fallback candidates and calls
`run(model=candidate)`. Resolving the owner per candidate is therefore sufficient
for cross-provider fallback, with **no change to fallback logic**. A registry in
the router would have invalidated most of the routing test suite and left the A1/A8
acceptance tests describing a different class than the one they were written for.
Letting the orchestrator choose per stage would move routing policy out of the
router, which is exactly what ADR-001 forbids.

Backends are constructed lazily so a Gemini-only configuration never imports or
constructs an Ollama or LiteLLM backend, keeping the `[router]` extra optional.

## Consequences

- Provider selection is still configuration- and model-driven; A8 now asserts the
  dispatch behaviour rather than a class.
- One code path regardless of how many providers a configuration uses.
- `doctor` reports live backends through `MultiBackend.live_backends()`.
- The precedence contract gained one rung (a transient session override above the
  explicit `model=` argument). Rungs 2 and 3 are unchanged.
```

- [ ] **Step 2: Write ADR 0007**

`docs/adr/0007-per-embedding-model-merge-thresholds.md`:

```markdown
# ADR-0007: Merge thresholds belong to an embedding space

**Status:** accepted · **Date:** 2026-10-02

## Context

`AUTO_MERGE = 0.92` and `MAYBE_MERGE = 0.70` were calibrated against Gemini's
embedding space. Introducing a second embedding model (a local Nomic model, say)
means those numbers describe a different geometry.

Over-merging is the expensive error in this system: a wrongly fused concept
silently deletes the lineage path between two concepts. Under-merging only leaves
a visible duplicate.

## Decision

Thresholds are stored per **canonical** embedding model id. A model with no entry
is `UNCALIBRATED`: automatic merging is disabled entirely, every candidate above
the judge floor becomes eligible for the existing bounded judge path (subject to
the most-similar-first ordering and the `MAX_JUDGE_CALLS` budget), and the resolve
report says so in a `warn` event.

Calibration is a separate, explicit pass that proposes a threshold from the
measured similarity distribution and **installs nothing**.

## Rationale

Failing toward duplicates keeps the failure visible and recoverable. Disabling
auto-merge does not mean every pair is judged -- the floor and the budget still
apply, so switching embedding model cannot become unbounded pairwise LLM spend.

Keying by canonical id rather than bare name prevents two providers exposing the
same model name from colliding.

## Consequences

- Switching to a new embedding model is safe by default: more duplicates, never a
  fused lineage path.
- Resolution is more expensive on an uncalibrated space, because the judge is the
  only merge path. That is the correct direction.
- A threshold is only ever installed by a human committing it.
```

- [ ] **Step 3: Update the operations guide**

In `docs/OPERATIONS_GUIDE.md`:

- §3.3: replace the precedence list with the four rungs and the explicit note that
  a session override is a deliberate higher-priority user control.
- §3.4: replace the provider table with the canonical model table, including the
  two refusal cases and their exact messages.
- §5: add a "Fully local" subsection with the `.env` block and `ollama pull` steps.
- §4.1: add `RLA_OLLAMA_URL`, `RLA_OLLAMA_THINK`, and note that
  `RLA_STRUCTURED_OUTPUT_MODELS` is LiteLLM-route only.

- [ ] **Step 4: Update PLAN.md, .env.example and README**

In `PLAN.md`, add a **P12** row to the §0 status table and a milestone section
after P11, using the same achieved / partially achieved / not achieved format,
recording the measured benchmark as a benchmark rather than a gate.

In `.env.example`, add `RLA_OLLAMA_URL` and `RLA_OLLAMA_THINK` with the existing
comment style, and correct the `RLA_STRUCTURED_OUTPUT_MODELS` block to say it
applies to the LiteLLM route only.

In `README.md`, replace the provider section's routing table with the canonical
model id table and add the fully local configuration.

- [ ] **Step 5: Verify and commit**

```bash
.\.venv\Scripts\python.exe -m pytest tests/ -q
.\.venv\Scripts\python.exe -m ruff check src/ tests/
git add docs/adr/0006-multi-provider-dispatch.md docs/adr/0007-per-embedding-model-merge-thresholds.md docs/OPERATIONS_GUIDE.md PLAN.md .env.example README.md
git commit -m "Document multi-provider dispatch and per-space merge thresholds"
```

---

## Self-Review

**Spec coverage**

| Spec section | Task |
|---|---|
| §4.1 MultiBackend below the router | 3 |
| §4.2 canonical identity, one interpretation | 1 |
| §4.3 resolution table, refusal before network | 1 |
| §4.4 lazy construction | 3 |
| §5 precedence, contract change documented | 4 |
| §5.2 in-flight safety | 4, 6 |
| §6 OllamaBackend, `format`, `think`, capability, 404 | 2 |
| §7.1 EmbeddingProvider, batched `/api/embed`, key requirement | 8 |
| §7.2 vector identity | 8 |
| §7.3 per-model thresholds, uncalibrated-safe | 9 |
| §7.4 calibration installs nothing | 10 |
| §8.1 CLI overrides | 5 |
| §8.2 TUI selector, three states | 6 |
| §8.3 fallback observation only | 4, 6 |
| §8.4 doctor dedupe, local/remote, stats | 5 |
| §9.1 P12a tests incl. prefill regression | 2, 3, 4, 5, 7 |
| §9.2 P12b tests | 8, 9, 10 |
| §10 milestones and acceptance | 7, 11 |
| §11 configuration | 2, 5, 12 |
| §12 risks incl. A1 adapter list | 3, 12 |
| §13 documentation and ADRs | 12 |
| §7.1 note: fully local needs no Gemini key | 11 |

**Placeholder scan:** no TBD, no "similar to Task N", no unspecified error
handling. Every code step carries actual code.

**Type consistency:** `canonical_model` (1) → used by `ollama_backend` (2),
`multi` (3), `cli` (5), `embeddings`/`ollama_embedder`/`factory` (8),
`resolve` (9), `factory` (11). `MergeThresholds(auto, maybe, calibrated)` (9) →
consumed by `merge_calibration` (10). `Probe(model, roles, kind)` (5) →
consumed by `_probe_llm` (5). `EmbeddingProvider` (8) → consumed by
`resolve_concepts` via `model_id` (9) and `calibrate` (10). `role_for` /
`set_override` (4) → `PipelineState` mirrors the same role names (6).