"""Runtime configuration.

Everything is environment-driven so the same image runs locally, in CI and in
production. Defaults point at a local Postgres and assume no LLM credentials —
the deterministic half of the system must work with zero external services.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="QRA_", env_file=".env", extra="ignore", case_sensitive=False
    )

    database_url: str = "postgresql+psycopg://qra:qra@localhost:5432/qra"
    redis_url: str = "redis://localhost:6379/0"

    # Where downloaded source dumps are cached before ingest.
    data_dir: Path = REPO_ROOT / "data"

    # Ingest may only pull editions whose licence status is in this set.
    # Add "restricted" (and supply your own licensed dumps) only after your own
    # legal review — see docs/LICENSING.md.
    allowed_license_status: set[str] = {"public_domain", "permissive"}

    # --- Models -------------------------------------------------------------
    # Planner/Critic want a strong reasoning model; extraction/summarisation can
    # run on a cheap local tier (e.g. an Ollama box).
    reasoning_model: str = "claude-opus-5"
    fast_model: str = "claude-haiku-4-5-20251001"
    anthropic_api_key: str | None = None
    ollama_base_url: str | None = None
    # Hard cap on agent turns so a runaway plan can't burn a budget.
    max_agent_steps: int = 40

    # --- Embeddings ---------------------------------------------------------
    # Semantic retrieval is optional and OFF unless an embedding provider is
    # configured. A disabled semantic tier is honest; a fake one is not.
    embedding_provider: str | None = None  # "ollama" | "openai_compatible" | None
    embedding_model: str = "bge-m3"
    embedding_dim: int = 1024
    embedding_base_url: str | None = None
    embedding_api_key: str | None = None

    # --- Observability ------------------------------------------------------
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_host: str = "https://cloud.langfuse.com"

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def metadata_dir(self) -> Path:
        return self.data_dir / "metadata"

    @property
    def semantic_enabled(self) -> bool:
        return self.embedding_provider is not None


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
