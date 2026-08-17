"""Apache AGE loader — reuses the RDB-issued entity/relation ids as-is
(CLAUDE.md "5단계 > ID 스킴": RDB is the SSOT, AGE never mints its own).
Node/edge properties are the minimal traversal/evidence set from CLAUDE.md
"AGE 스키마" — not the full RDB row (evidence_text/extraction_method stay
RDB-only, audit detail isn't needed for graph traversal).

Edges are created with a raw Cypher MERGE keyed on the edge's own `id`
property rather than via cypher.upsert_edge_raw's `MERGE (a)-[r:TYPE]->(b)`
(no property filter): CLAUDE.md "5단계 > ID 스킴" requires every extraction
instance to stay its own edge even when the same two entities repeat the
same edge_type across different articles ("같은 두 엔티티 사이에 같은
edge_type이 여러 조문에서 반복돼도 각각 별도 relation row/엣지로 남긴다") —
a bare `MERGE (a)-[r:TYPE]->(b)` would collapse those into one edge instead
of creating a new one, silently dropping provenance. Keying the MERGE on
`id` keeps re-running this loader idempotent while still allowing distinct
parallel edges of the same type between the same node pair.
"""

from __future__ import annotations

import logging

from graphdb.cypher import map_literal, run_cypher, upsert_node_raw
from graphdb.connection import GraphConnection
from graphdb.ingest.rdb_loader import RDBLoadResult
from graphdb.schema import EdgeLabel, NodeLabel

logger = logging.getLogger(__name__)

_SUBTYPE_PROP = {
    NodeLabel.ORGANIZATION: "category",
    NodeLabel.PERSON: "role_hint",
    NodeLabel.LEGAL_DOCUMENT: "doc_type",
    NodeLabel.CONCEPT: "concept_type",
}


async def truncate_age() -> None:
    conn = GraphConnection()
    await conn.open()
    try:
        async with conn.cursor() as cur:
            await run_cypher(cur, "MATCH (n) DETACH DELETE n", {}, columns="n agtype")
    finally:
        await conn.close()


async def load_to_age(result: RDBLoadResult) -> None:
    entity_by_id = {e.id: e for e in result.entities}

    conn = GraphConnection()
    await conn.open()
    try:
        async with conn.cursor() as cur:
            for e in result.entities:
                label = NodeLabel(e.label)
                props: dict[str, object] = {"name": e.name, "description": e.description}
                if e.subtype:
                    props[_SUBTYPE_PROP[label]] = e.subtype
                await upsert_node_raw(cur, label, e.id, props)
        logger.info("AGE: %d nodes upserted", len(result.entities))

        skipped = 0
        async with conn.cursor() as cur:
            for r in result.relations:
                source_entity = entity_by_id.get(r.source_entity_id)
                target_entity = entity_by_id.get(r.target_entity_id)
                if source_entity is None or target_entity is None:
                    skipped += 1
                    continue
                edge_label = EdgeLabel(r.edge_type).value
                props = {
                    "id": r.id,
                    "source_law": r.source_law,
                    "article_no": r.article_no,
                    "paragraph_no": r.paragraph_no,
                    "condition": "",
                    "modality": r.modality,
                    "voice": r.voice,
                }
                props_literal, prop_params = map_literal(props)
                query = f"""
                    MATCH (a:{source_entity.label} {{id: $start_id}}), (b:{target_entity.label} {{id: $end_id}})
                    MERGE (a)-[rel:{edge_label} {props_literal}]->(b)
                    RETURN rel
                """
                await run_cypher(
                    cur,
                    query,
                    {"start_id": r.source_entity_id, "end_id": r.target_entity_id, **prop_params},
                    columns="rel agtype",
                )
        if skipped:
            logger.warning("AGE: skipped %d edges with unresolved endpoint entity", skipped)
        logger.info("AGE: %d edges upserted", len(result.relations) - skipped)
    finally:
        await conn.close()
