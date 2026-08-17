#!/usr/bin/env python3
"""RAG 쿼리 API 서버 진입점.

Windows에서 이게 왜 필요한지(2026-08-16 진단): `uvicorn.run()`은 내부적으로
Python 3.11에서 `asyncio.Runner`가 아니라 자체 `asyncio_run(..., loop_factory=...)`
래퍼를 쓰는데, 그 `loop_factory`가 `uvicorn/loops/asyncio.py`의
`asyncio_loop_factory()`에서 `sys.platform == "win32"`면 **무조건**
`asyncio.ProactorEventLoop`를 반환한다 — 미리 `asyncio.set_event_loop_policy(
WindowsSelectorEventLoopPolicy())`를 설정해둬도 uvicorn이 정책을 아예 안
보고 무시한다. psycopg의 비동기 커넥션 풀(graphdb.connection.GraphConnection,
AGE 연결에 사용)은 SelectorEventLoop가 필요해서, 이 조합으로 실행하면
`PoolTimeout: pool initialization incomplete after 30.0 sec`가 재현된다
(`uvicorn.run()`이나 `python -m uvicorn ...` CLI 둘 다 동일하게 실패 —
앱 모듈을 언제 import하냐의 문제가 아니라 uvicorn이 루프 자체를 직접
만드는 게 원인이었다).

해결: `uvicorn.run()`을 아예 안 쓰고, SelectorEventLoop를 직접 만들어
`uvicorn.Server.serve()`를 그 위에서 돈다 — uvicorn의 loop_factory 경로를
완전히 우회한다.

Usage:
    PYTHONPATH=src python scripts/run_api.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import uvicorn  # noqa: E402


async def _serve() -> None:
    config = uvicorn.Config("graphdb.api.app:app", host="127.0.0.1", port=8123, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    if sys.platform == "win32":
        loop = asyncio.SelectorEventLoop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_serve())
    else:
        asyncio.run(_serve())
