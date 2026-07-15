from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM (OpenAI-kompatibilen API)
    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    llm_temperature: float = 0.1
    max_answer_tokens: int = 1200

    # Qdrant
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str | None = None
    qdrant_collection: str = "askugd"
    use_hybrid: bool = True

    # Embeddings / rerank
    dense_model: str = "intfloat/multilingual-e5-large"
    dense_dim: int = 1024
    sparse_model: str = "Qdrant/bm25"
    rerank_model: str = "jinaai/jina-reranker-v2-base-multilingual"

    # Retrieval
    top_k: int = 5
    candidate_k: int = 20
    rerank_threshold: float = 0.1
    max_retrieval_iterations: int = 3
    llm_retries: int = 3

    # API bezbednost
    api_access_key: str | None = None
    cors_origins: str = ""
    rate_limit: int = 20
    rate_limit_ip: int = 300
    max_question_chars: int = 1000
    trust_proxy_headers: bool = False

    # Istorija na razgovor
    history_ttl_seconds: int = 3600
    history_max_turns: int = 6

    # Redis (opcionalno, za povekje workers)
    redis_url: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [domen.strip() for domen in self.cors_origins.split(",")
                if domen.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
