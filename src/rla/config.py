"""Configuration loaded from environment / .env.

Every field except the Gemini API key is optional: the pipeline degrades to
keyless sources (spec section 3a) rather than failing when a paid key is absent.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


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

    # --- Optional sources --------------------------------------------------
    serpapi_api_key: str = ""
    core_api_key: str = ""

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

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.raw_dir, self.graph_dir):
            path.mkdir(parents=True, exist_ok=True)

    def enabled_sources(self) -> list[str]:
        """Keyless sources are always on; SerpApi only when a key is present."""
        sources = ["semantic_scholar", "openalex", "arxiv", "dblp", "crossref"]
        if self.serpapi_api_key:
            sources.append("serpapi")
        return sources


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
