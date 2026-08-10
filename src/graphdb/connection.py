from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

import psycopg
from psycopg_pool import AsyncConnectionPool

from graphdb.config import GraphDBSettings, get_settings

logger = logging.getLogger(__name__)

_AGE_SETUP_SQL = "LOAD 'age'; SET search_path = ag_catalog, \"$user\", public;"


class GraphConnection:
    """Owns a psycopg async connection pool wired up for Apache AGE.

    Every connection handed out by the pool has the `age` extension loaded
    and `search_path` set so that `cypher(...)` and `agtype` are resolvable
    without repeating the setup in every call site.
    """

    def __init__(self, settings: GraphDBSettings | None = None) -> None:
        self.settings = settings or get_settings()
        self._pool: AsyncConnectionPool | None = None

    async def open(self) -> None:
        if self._pool is not None:
            return
        self._pool = AsyncConnectionPool(
            conninfo=self.settings.dsn,
            min_size=self.settings.pool_min_size,
            max_size=self.settings.pool_max_size,
            configure=self._configure_connection,
            open=False,
        )
        await self._pool.open(wait=True)
        logger.info(
            "Graph DB pool opened (host=%s db=%s graph=%s)",
            self.settings.host,
            self.settings.name,
            self.settings.graph_name,
        )

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    @staticmethod
    async def _configure_connection(conn: psycopg.AsyncConnection) -> None:
        async with conn.cursor() as cur:
            await cur.execute(_AGE_SETUP_SQL)
        await conn.commit()

    @asynccontextmanager
    async def cursor(self) -> AsyncIterator[psycopg.AsyncCursor]:
        if self._pool is None:
            await self.open()
        assert self._pool is not None
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                yield cur

    async def __aenter__(self) -> "GraphConnection":
        await self.open()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()
