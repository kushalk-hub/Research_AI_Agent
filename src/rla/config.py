"""Configuration loaded from environment / .env.

Every field except the Gemini API key is optional: the pipeline degrades to
keyless sources (spec section 3a) rather than failing when a paid key is absent.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from rla.errors import ModelResolutionError

PROJECT_ROOT = Path(__file__).resolve().parents[2]

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


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_prefix="RLA_",
        extra="ignore",
    )

    # --- LLM ---------------------------------------------------------------
    gemini_api_key: str = Field(
        default="",
        validation_alias="GEMINI_API_KEY",
        description="Required for every LLM stage. Pipeline runs in degrade mode without it.",
    )
    #: Free-tier keys report "limit: 0" for every Pro model, so the fast/strong
    #: split is drawn across the flash tier instead of failing at run time.
    fast_model: str = "gemini-2.5-flash-lite"
    strong_model: str = "gemini-2.5-flash"
    #: text-embedding-004 was retired and now 404s; this is the GA replacement.
    embedding_model: str = "gemini-embedding-001"

    #: --- Provider routing -------------------------------------------------
    #: `gemini` uses the native SDK directly (no LiteLLM import). `litellm` routes
    #: through the optional [router] extra. Both satisfy the same LLMClient
    #: Protocol, so this is a config change and never a code change.
    llm_provider: str = "gemini"
    #: Model for the four structured stages (query expansion, relevance scoring,
    #: extraction, resolution). Separate from `fast_model` because those stages
    #: dominate request volume: a 100-paper corpus is ~100 extraction calls, which
    #: is five days of the fast model's free-tier daily allowance. Defaulting to
    #: `fast_model` keeps that affordable and is now honoured explicitly rather
    #: than by accident (the previous code accepted `strong_model` and discarded
    #: it, so extraction silently ran on the cheap model anyway).
    structured_model: str = ""
    #: Model for streamed answer generation, where quality is user-visible and
    #: volume is one call per question.
    answer_model: str = ""
    #: Ordered fallback models, tried only on recoverable transport faults.
    fallback_models: str = "gemini-2.5-flash"
    #: Quota exhaustion is a capacity condition, not a fault, so failing over
    #: spends a second model's budget on a first model's ceiling. Off unless the
    #: operator explicitly wants that trade. See ADR-004.
    fallback_on_quota: bool = False
    #: Model ids the operator declares to support schema-constrained output even
    #: when LiteLLM's static table says otherwise.
    #:
    #: LiteLLM reports `supports_response_schema() == False` for any model it has
    #: no entry for -- including a self-hosted llama.cpp/Ollama server that
    #: honours `response_format` perfectly well. Left unaddressed, the capability
    #: gate (ADR-004) refuses such a model, and because scoring, extraction and
    #: resolution are *all* structured stages, it becomes unusable for exactly the
    #: bulk work a local model is wanted for.
    #:
    #: Substring-matched against both the bare and the `provider/`-prefixed id, so
    #: one entry covers both spellings. Empty preserves the gate unchanged: this is
    #: an explicit operator assertion, never a silent assumption.
    structured_output_models: str = ""
    #: Bound a single provider attempt. Previously no provider call had any
    #: bound: `request_timeout_seconds` only ever applied to source HTTP.
    llm_timeout_seconds: float = Field(default=120.0, gt=0.0)

    # --- Optional sources --------------------------------------------------
    serpapi_api_key: str = ""
    core_api_key: str = ""

    # --- Second LLM provider -----------------------------------------------
    #: Credential for the secondary LLM provider. Named for the PROVIDER, not for
    #: the routing role: credentials belong to providers, and a provider can be
    #: promoted to primary later, at which point a `FALLBACK_API_KEY` name would
    #: be actively misleading. Optional -- the pipeline runs on the primary alone
    #: when this is blank.
    openai_api_key: str = Field(
        default="",
        validation_alias="OPENAI_API_KEY",
        description="Optional second LLM provider credential, for cross-provider failover.",
    )

    # --- Provider endpoints -------------------------------------------------
    #: Per-provider base URL overrides, as a JSON object keyed by the SAME provider
    #: prefix used in model strings (`gemini/...`, `openai/...`, `openrouter/...`).
    #:
    #: Deliberately a map and not a single URL. Cross-provider routing means two
    #: providers are live at once, and they must not share an endpoint: pointing
    #: Gemini and a local vLLM at the same base URL would silently break the primary.
    #:
    #: A map is also the only shape that supports an arbitrary provider -- an
    #: OpenAI-compatible gateway, a proxy, or a self-hosted endpoint -- without a
    #: code change per provider. Entries are optional; an absent key means
    #: "use the provider's default endpoint".
    #:
    #: Example:
    #:   RLA_LLM_BASE_URLS={"openrouter": "https://openrouter.ai/api/v1",
    #:                     "local": "http://localhost:8000/v1"}
    llm_base_urls: str = Field(
        default="",
        description="JSON object of provider prefix -> base URL, e.g. '{\"openrouter\": \"...\"}'.",
    )

    # --- Optional phase 2: full text ---------------------------------------
    unpaywall_email: str = ""
    grobid_url: str = ""

    # --- Optional graph server ---------------------------------------------
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""

    # --- Pipeline tuning ---------------------------------------------------
    max_concurrency: int = Field(default=4, ge=1, le=16)
    #: Per-minute pacing, kept as a guard against bursty local bursts. It is not
    #: the binding constraint: the free tier also caps each model at
    #: `llm_daily_budget` requests *per day*, and that ceiling resets only at the
    #: daily boundary, so no amount of pacing gets under it. See
    #: `rla.llm.retry.is_daily_quota`, which fails fast instead of retrying.
    llm_rpm: int = Field(default=15, ge=1, le=60)
    llm_max_retries: int = Field(default=5, ge=1, le=10)
    #: Requests a stage may spend per model per run. Stops a large batch from
    #: spending the whole day's allowance on the first pass and leaving nothing
    #: for resolution, graph building, or answering. Set to 0 for no cap.
    llm_daily_budget: int = Field(default=15, ge=0)
    s2_delay_seconds: float = Field(default=1.1, ge=0.0)
    target_corpus_min: int = 40
    target_corpus_max: int = 100
    request_timeout_seconds: float = 30.0
    max_retries: int = 4
    log_level: str = "INFO"

    # --- Paths -------------------------------------------------------------
    data_dir: Path = PROJECT_ROOT / "data"
    raw_dir: Path = PROJECT_ROOT / "data" / "raw"
    graph_dir: Path = PROJECT_ROOT / "data" / "graph"

    @property
    def cache_db(self) -> Path:
        return self.data_dir / "cache.db"

    @property
    def llm_limiter(self):
        """Shared pace for every Gemini call, text and embedding alike."""
        from rla.llm.retry import get_limiter

        return get_limiter(self.llm_rpm)

    @property
    def llm_spender(self):
        """Budget tracker guarding the per-run allowance, shared like the limiter."""
        from rla.llm.retry import get_spender

        return get_spender(self.llm_daily_budget)

    @property
    def corpus_path(self) -> Path:
        return self.data_dir / "corpus.json"

    @property
    def extractions_path(self) -> Path:
        return self.data_dir / "extractions.jsonl"

    @property
    def concepts_path(self) -> Path:
        return self.data_dir / "concepts.json"

    @property
    def graph_json(self) -> Path:
        return self.graph_dir / "graph.json"

    @property
    def graph_graphml(self) -> Path:
        return self.graph_dir / "graph.graphml"

    # --- Base URL overrides ------------------------------------------------
    # Methods live after the field block on purpose. Pydantic collects fields by
    # scanning class-level annotations, so a method interleaved among them silently
    # terminates field collection and every later annotated attribute becomes an
    # ordinary class variable instead of a setting.

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

    def declared_structured_models(self) -> list[str]:
        """Model ids the operator has asserted honour schema-constrained output."""
        raw = [m.strip() for m in (self.structured_output_models or "").split(",") if m.strip()]
        return list(dict.fromkeys(raw))

    def declares_structured_output(self, model: str) -> bool:
        """Whether `model` is on that list.

        Substring-matched against the id as written and as routed, because a bare
        `qwen3:4b` and `openai/qwen3:4b` name the same model and this project writes
        both. Substring rather than equality so one entry can cover a family
        (`qwen3`) without enumerating every quantisation.
        """
        declared = self.declared_structured_models()
        if not declared:
            return False
        candidates = {model}
        if "/" in model:
            candidates.add(model.split("/", 1)[1])
        return any(entry in candidate for entry in declared for candidate in candidates)

    def base_url_for(self, model: str) -> str | None:
        """Resolve the base URL override for a model's provider, if any.

        Returns None when no override is configured, which means "use the provider
        default" -- an explicit distinction from an override pointing at an empty
        string.
        """
        override = self.parsed_base_urls()
        if not override:
            return None
        return override.get(self.provider_prefix_for(model))

    def provider_prefix_for(self, model: str) -> str:
        """Which provider key in the base URL map a model belongs to.

        An explicit `provider/model` prefix is authoritative. A *bare* id is asked
        what provider it names -- `gemini-2.5-flash` is a Gemini model whoever
        happens to be primary -- and only an id that identifies no provider falls
        back to the configured primary.

        Getting this wrong is silent and severe: pointing the primary at a
        self-hosted `openai/qwen3:4b` once made a bare `gemini-2.5-flash` resolve
        to the local endpoint, so the answer stage would have shipped a Gemini
        model to Ollama. The table matches `llm.litellm_backend.route_model`, and
        `test_p10_base_urls.py` asserts the two agree.
        """
        if "/" in model:
            return model.split("/", 1)[0]
        for prefix, provider in (
            ("gemini", "gemini"),
            ("gpt", "openai"),
            ("o1", "openai"),
            ("o3", "openai"),
            ("text-embedding", "openai"),
            ("claude", "anthropic"),
        ):
            if model.startswith(prefix):
                return provider
        return self.primary_provider_prefix

    @property
    def primary_provider_prefix(self) -> str:
        """Provider prefix for a bare (unprefixed) model id.

        A bare id like `gemini-2.5-flash` is a Google model, so an override keyed
        `gemini` applies to it. Without this, per-provider overrides would silently
        not apply to exactly the model strings the project defaults to.
        """
        model = self.model_for_structured
        if "/" in model:
            return model.split("/", 1)[0]
        return "gemini" if model.startswith("gemini") else model

    def parsed_base_urls(self) -> dict[str, str]:
        """Parse `llm_base_urls`, tolerating anything malformed.

        A typo in this optional convenience setting must not stop the pipeline, so
        bad input yields an empty map. Ignoring it silently would be worse than
        failing loudly, so a warning is emitted once per distinct bad value.
        """
        raw = (self.llm_base_urls or "").strip()
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            _warn_once(
                f"RLA_LLM_BASE_URLS is not valid JSON ({exc}); ignoring the override. "
                "Expected a JSON object like '{\"openrouter\": \"https://...\"}'."
            )
            return {}
        if not isinstance(parsed, dict):
            _warn_once(
                "RLA_LLM_BASE_URLS must be a JSON object of provider -> url, "
                f"got {type(parsed).__name__}; ignoring the override."
            )
            return {}
        return {str(k): str(v) for k, v in parsed.items() if v}

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.raw_dir, self.graph_dir):
            path.mkdir(parents=True, exist_ok=True)

    @property
    def model_for_structured(self) -> str:
        """Model for the four schema-constrained stages."""
        return self.structured_model or self.fast_model

    @property
    def model_for_answer(self) -> str:
        """Model for streamed answer generation."""
        return self.answer_model or self.strong_model

    @property
    def configured_fallbacks(self) -> list[str]:
        """Fallback models exactly as configured, in order, de-duplicated."""
        raw = [m.strip() for m in self.fallback_models.split(",") if m.strip()]
        return list(dict.fromkeys(raw))

    def fallback_chain_for(self, model: str) -> list[str]:
        """Fallbacks available to a specific primary model.

        Only the model being asked about is excluded. Excluding the answer-stage
        primary as well would leave the structured stages -- the bulk of the call
        volume -- with nothing to fail over to, since the two primaries are
        sibling models and the structured primary is the cheaper one.
        """
        return [m for m in self.configured_fallbacks if m != model]

    @property
    def fallback_chain(self) -> list[str]:
        """Fallbacks available to the structured primary (the bulk of calls)."""
        return self.fallback_chain_for(self.model_for_structured)

    def enabled_sources(self) -> list[str]:
        """Keyless sources are always on; SerpApi only when a key is present."""
        sources = ["semantic_scholar", "openalex", "arxiv", "dblp", "crossref"]
        if self.serpapi_api_key:
            sources.append("serpapi")
        return sources


_WARNED: set[str] = set()


def _warn_once(message: str) -> None:
    """Emit a configuration warning once, without a logging dependency.

    `config.py` is imported by every entrypoint including `rla doctor --help`, so
    it deliberately sets up no logging. A malformed optional setting is worth
    saying out loud once rather than being silently ignored.
    """
    if message in _WARNED:
        return
    _WARNED.add(message)
    import sys

    print(f"warning: {message}", file=sys.stderr)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
