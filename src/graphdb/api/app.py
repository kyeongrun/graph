"""FastAPI entry point for the graph RAG query API + a static visualization
page. Run via `scripts/run_api.py`, NOT `uvicorn graphdb.api.app:app`
directly — the raw uvicorn CLI creates its asyncio event loop before
importing this module, so the Windows event-loop-policy fix below (needed
for psycopg's async pool) ends up applied too late. See run_api.py's
docstring for how this was diagnosed.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

if sys.platform == "win32":
    # Same fix as scripts/run_pipeline.py: psycopg's async pool needs a
    # selector-based loop, but Windows' default asyncio policy hands out a
    # ProactorEventLoop — must be set before uvicorn creates its loop, so
    # this runs at import time (uvicorn imports the app before starting).
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from graphdb.query.rag import answer_question

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Law Graph RAG API")


class QueryRequest(BaseModel):
    question: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)
    depth: int = Field(default=1, ge=1, le=3)


class NodeOut(BaseModel):
    id: str
    name: str | None
    label: str | None
    description: str | None = None


class EdgeOut(BaseModel):
    id: str
    source: str
    target: str
    edge_type: str
    source_law: str | None = None
    article_no: int | None = None
    paragraph_no: int | None = None
    modality: str | None = None
    voice: str | None = None


class QueryResponse(BaseModel):
    answer: str
    seed_entities: list[dict]
    nodes: list[NodeOut]
    edges: list[EdgeOut]
    context_truncated: bool = False
    hub_seeds_capped: int = 0
    edge_type_source: str | None = None
    edge_type_refined: bool = False


@app.post("/api/query", response_model=QueryResponse)
async def query(req: QueryRequest) -> QueryResponse:
    result = await answer_question(req.question, top_k=req.top_k, depth=req.depth)
    return QueryResponse(
        answer=result.answer,
        seed_entities=result.seed_entities,
        nodes=[NodeOut(**n) for n in result.nodes],
        edges=[EdgeOut(**e) for e in result.edges],
        context_truncated=result.context_truncated,
        hub_seeds_capped=result.hub_seeds_capped,
        edge_type_source=result.edge_type_source,
        edge_type_refined=result.edge_type_refined,
    )


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return (_STATIC_DIR / "index.html").read_text(encoding="utf-8")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
