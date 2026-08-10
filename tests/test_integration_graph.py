"""End-to-end tests against a real Apache AGE instance.

Skipped by default. Run against docker-compose's age-db service with:

    docker compose up -d age-db
    RUN_GRAPHDB_INTEGRATION_TESTS=1 pytest tests/test_integration_graph.py
"""

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_GRAPHDB_INTEGRATION_TESTS") != "1",
    reason="set RUN_GRAPHDB_INTEGRATION_TESTS=1 with age-db running to enable",
)


@pytest.mark.asyncio
async def test_seed_and_query_roundtrip():
    from graphdb.connection import GraphConnection
    from graphdb.ingest.domain_loader import upsert_edge, upsert_node
    from graphdb.models.entities import Company, Department, Edge
    from graphdb.query.retrieval import get_context_for_rag
    from graphdb.schema import EdgeLabel, NodeLabel

    conn = GraphConnection()
    await conn.open()
    try:
        async with conn.cursor() as cur:
            await upsert_node(cur, Company(id="it-co-1", name="테스트금융지주"))
            await upsert_node(cur, Department(id="it-dept-1", name="테스트준법감시부", company_id="it-co-1"))
            await upsert_edge(
                cur,
                Edge(
                    label=EdgeLabel.BELONGS_TO,
                    start_label=NodeLabel.DEPARTMENT,
                    start_id="it-dept-1",
                    end_label=NodeLabel.COMPANY,
                    end_id="it-co-1",
                ),
            )

        async with conn.cursor() as cur:
            context = await get_context_for_rag(cur, "테스트준법감시부", label=NodeLabel.DEPARTMENT)
        assert context is not None
        assert "BELONGS_TO" in context
    finally:
        await conn.close()
