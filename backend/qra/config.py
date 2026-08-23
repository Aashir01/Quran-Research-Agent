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
    # No model id appears here. Ids, prices, context windows and the role→model
    # policy all live in ``config/models.yaml`` — see qra.ai.registry — because
    # model names change far faster than this file does. Provider credentials
    # are read from the env var each registry block names (QRA_ANTHROPIC_API_KEY,
    # QRA_OPENAI_API_KEY, …), or supplied per-user through /auth/keys.
    models_config: Path | None = None  # overrides config/models.yaml
    # Hard cap on agent turns so a runaway plan can't burn a budget.
    max_agent_steps: int = 40

    # --- Embeddings ---------------------------------------------------------
    # Semantic retrieval is optional and OFF unless an embedding provider is
    # named here. A disabled semantic tier is honest; a fake one is not. The
    # value is a provider key from the `embedding:` block of models.yaml
    # (bge_m3_local, ollama, openai, voyage, cohere, google, jina).
    embedding_provider: str | None = None
    # Optional: pin one of that provider's models. Unset means "the one the
    # registry lists", which is the usual case since most blocks list one.
    embedding_model: str | None = None

    # --- Identity and secrets (WP-01, WP-12) --------------------------------
    # Auth is enabled by the presence of a JWT secret. A deployment without one
    # runs open — fine on a laptop, never fine on a shared server — and
    # /meta/capabilities reports which mode is live.
    jwt_secret: str | None = None
    jwt_ttl_seconds: int = 12 * 3600
    # Master key for envelope-encrypting provider keys at rest.
    secret_key: str | None = None
    oidc_issuer: str | None = None
    oidc_audience: str | None = None
    # Requests per minute, per principal. 0 disables.
    rate_limit_per_minute: int = 240
    # Browser origins allowed to call this API. Empty means "any origin, without
    # credentials" — correct for a Bearer-token API and the only wildcard the
    # CORS spec permits. Name origins here on a shared deployment.
    cors_origins: list[str] = []

    # --- Cost governance (WP-05) --------------------------------------------
    default_run_cost_ceiling_usd: float = 2.0
    default_monthly_token_budget: int | None = None

    # --- Caching (WP-06) ----------------------------------------------------
    cache_enabled: bool = True
    cache_ttl_seconds: int = 30 * 24 * 3600

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
