from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class ProductConfig(BaseModel):
    key: str
    display: str
    appstore_id: str | None = None
    play_package: str | None = None
    gdoc_id: str | None = None
    gmail_to: str | None = None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="PULSE_", extra="ignore")

    db_path: Path = Path("data/pulse.db")
    products_path: Path = Path("data/products.yaml")
    raw_reviews_dir: Path = Path("data/raw")
    summaries_dir: Path = Path("data/summaries")
    artifacts_dir: Path = Path("data/artifacts")
    embedding_cache_path: Path = Path("data/cache/embeddings.json")
    default_country: str = "in"
    cluster_language: str = "en"
    cluster_min_chars: int = 20
    embedding_provider: str = "local_hash"
    embedding_model_local: str = "BAAI/bge-small-en-v1.5"
    embedding_model_openai: str = "text-embedding-3-small"
    embedding_dimensions: int = 384
    umap_n_components: int = 15
    hdbscan_min_cluster_size: int = 8
    keyphrase_top_n: int = 8
    use_keybert: bool = False
    llm_provider: str = "mock"
    llm_model: str = "mock-v1"
    groq_api_key: str | None = None
    llm_timeout_seconds: int = 30
    llm_max_retries: int = 2
    llm_token_cap_per_run: int = 50000
    llm_cost_cap_usd_per_run: float = 20.0
    docs_mcp_transport: str = "mock"
    docs_mcp_url: str | None = None
    docs_mcp_command: str | None = None
    gmail_mcp_transport: str = "mock"
    gmail_mcp_url: str | None = None
    gmail_mcp_command: str | None = None
    mcp_mock_state_path: Path = Path("data/mcp/mock_state.json")
    run_weeks_default: int = 10
    log_level: str = "INFO"
    confirm_send: bool = False


def load_settings() -> Settings:
    return Settings()


def load_products(path: Path) -> list[ProductConfig]:
    if not path.exists():
        return []
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    return [ProductConfig.model_validate(item) for item in payload]
