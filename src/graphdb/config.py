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
