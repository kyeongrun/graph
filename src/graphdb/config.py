from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class GraphDBSettings(BaseSettings):
    """Connection settings for the Apache AGE graph database.

    Values are read from environment variables / .env, falling back to
    the docker-compose.yml defaults for local development.
    """

    model_config = SettingsConfigDict(
        env_prefix="AGE_DB_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = "localhost"
    port: int = 5433
    user: str = "graph_admin"
    password: str = "changeme"
    name: str = "internal_control"
    graph_name: str = "internal_control"

    # Connection pool sizing
    pool_min_size: int = 1
    pool_max_size: int = 10

    @property
    def dsn(self) -> str:
        return (
            f"host={self.host} port={self.port} dbname={self.name} "
            f"user={self.user} password={self.password}"
        )


@lru_cache
def get_settings() -> GraphDBSettings:
    return GraphDBSettings()


class RDBSettings(BaseSettings):
    """Connection settings for the RDB (PostgreSQL 17.10) that holds
    document/entity/relation — the ID-issuing SSOT for the 3-store pipeline
    (CLAUDE.md "5단계"). Separate instance from the AGE graph DB above: the
    AGE image is pinned to PG16, RDB has no such constraint.
    """

    model_config = SettingsConfigDict(
        env_prefix="RDB_DB_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = "localhost"
    port: int = 5434
    user: str = "rdb_admin"
    password: str = "changeme"
    name: str = "internal_control"

    pool_min_size: int = 1
    pool_max_size: int = 10

    @property
    def dsn(self) -> str:
        return (
            f"host={self.host} port={self.port} dbname={self.name} "
            f"user={self.user} password={self.password}"
        )


@lru_cache
def get_rdb_settings() -> RDBSettings:
    return RDBSettings()


class OpenSearchSettings(BaseSettings):
    """Connection settings for OpenSearch (entity/relation indices with
    description embeddings — CLAUDE.md "5단계"). Local dev compose runs
    OpenSearch with the security plugin disabled, so no auth by default.
    """

    model_config = SettingsConfigDict(
        env_prefix="OPENSEARCH_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = "localhost"
    port: int = 9200
    use_ssl: bool = False
    verify_certs: bool = False
    user: str | None = None
    password: str | None = None

    @property
    def url(self) -> str:
        scheme = "https" if self.use_ssl else "http"
        return f"{scheme}://{self.host}:{self.port}"


@lru_cache
def get_opensearch_settings() -> OpenSearchSettings:
    return OpenSearchSettings()


class LLMSettings(BaseSettings):
    """vLLM (OpenAI-compatible) endpoint used for the narrow LLM roles in
    CLAUDE.md "5단계" (edge_type disambiguation for needs_context/AMBIGUOUS
    verb roots, entity typing/alias augmentation for context-dependent
    mentions). Reuses the repo-outside-git-but-in-tree `.env.dev` shared by
    the parent project (gitignored) — see CLAUDE.md "LLM 엔드포인트".
    """

    model_config = SettingsConfigDict(
        env_prefix="VLLM_",
        env_file=".env.dev",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    base_url: str = "http://localhost:8000/v1"
    api_key: str = "not-needed"
    # model_name is intentionally NOT used to pick the model at call time —
    # CLAUDE.md 2026-08-15 note: the value pinned here has drifted from what
    # the server actually serves and 404s. Always discover via
    # client.models.list() instead (see graphdb.llm.get_model_id).
    model_name: str = ""


@lru_cache
def get_llm_settings() -> LLMSettings:
    return LLMSettings()
