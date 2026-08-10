"""GraphRAG retrieval: pull a relevant subgraph around one or more entities
and render it as a compact text block suitable for prompt injection
alongside vector-search hits (e.g. from OpenSearch) in the RAG pipeline.
"""

from __future__ import annotations

import psycopg

from graphdb.cypher import run_cypher
from graphdb.schema import NodeLabel

_MAX_DEPTH = 3


def _vertex_label_and_props(vertex: dict) -> tuple[str, dict]:
    label = vertex.get("label", "?")
    props = vertex.get("properties", {})
    return label, props


def _edge_label(edge: dict) -> str:
    return edge.get("label", "?")


async def find_entity_id(
    cur: psycopg.AsyncCursor,
    name: str,
    *,
    label: NodeLabel | None = None,
    graph_name: str | None = None,
) -> tuple[str, str] | None:
    """Resolve a free-text name to (label, id) of the best-matching node.

    If `label` is given, search is restricted to that label; otherwise all
    domain labels are tried and the first match wins. Intended for turning
    an entity mention (from a user question or a vector-search hit) into a
    graph anchor point.
    """
    labels = [label] if label else list(NodeLabel)
    for candidate_label in labels:
        query = f"""
            MATCH (n:{candidate_label.value})
            WHERE n.name = $name
            RETURN n.id AS id
            LIMIT 1
        """
        rows = await run_cypher(cur, query, {"name": name}, columns="id agtype", graph_name=graph_name)
        if rows:
            return candidate_label.value, rows[0][0]
    return None


async def get_subgraph(
    cur: psycopg.AsyncCursor,
    node_id: str,
    *,
    depth: int = 1,
    graph_name: str | None = None,
) -> list[tuple]:
    """Fetch the neighborhood around a node up to `depth` hops (both
    directions). `depth` is clamped to keep queries bounded."""
    depth = max(1, min(int(depth), _MAX_DEPTH))
    query = f"""
        MATCH (n {{id: $id}})-[r*1..{depth}]-(m)
        RETURN n, r, m
    """
    return await run_cypher(
        cur, query, {"id": node_id}, columns="n agtype, r agtype, m agtype", graph_name=graph_name
    )


def format_subgraph_as_context(rows: list[tuple]) -> str:
    """Render `get_subgraph` rows as human-readable "A -[REL]-> B" lines,
    deduplicated, for injection into an LLM prompt."""
    lines: list[str] = []
    seen: set[str] = set()

    for n, edges, m in rows:
        edge_list = edges if isinstance(edges, list) else [edges]
        n_label, n_props = _vertex_label_and_props(n)
        m_label, m_props = _vertex_label_and_props(m)
        n_name = n_props.get("name", n.get("id", "?"))
        m_name = m_props.get("name", m.get("id", "?"))

        for edge in edge_list:
            if not isinstance(edge, dict):
                continue
            rel = _edge_label(edge)
            line = f"({n_label}) {n_name} -[{rel}]-> ({m_label}) {m_name}"
            if line not in seen:
                seen.add(line)
                lines.append(line)

    return "\n".join(lines)


async def get_context_for_rag(
    cur: psycopg.AsyncCursor,
    entity_name: str,
    *,
    label: NodeLabel | None = None,
    depth: int = 1,
    graph_name: str | None = None,
) -> str | None:
    """End-to-end helper: resolve `entity_name` to a node, fetch its
    neighborhood, and return it pre-formatted as RAG context text.
    Returns None if the entity can't be found in the graph.
    """
    resolved = await find_entity_id(cur, entity_name, label=label, graph_name=graph_name)
    if resolved is None:
        return None
    _, node_id = resolved
    rows = await get_subgraph(cur, node_id, depth=depth, graph_name=graph_name)
    return format_subgraph_as_context(rows)


async def get_controls_for_risk(
    cur: psycopg.AsyncCursor,
    risk_name: str,
    *,
    graph_name: str | None = None,
) -> list[dict]:
    """Domain-specific traversal: which control items mitigate a named
    risk, and which regulation each control implements."""
    query = """
        MATCH (c:ControlItem)-[:MITIGATES]->(r:Risk {name: $risk_name})
        OPTIONAL MATCH (c)-[:IMPLEMENTS]->(reg:Regulation)
        OPTIONAL MATCH (p:Person)-[:RESPONSIBLE_FOR]->(c)
        RETURN c, reg, p
    """
    rows = await run_cypher(
        cur,
        query,
        {"risk_name": risk_name},
        columns="c agtype, reg agtype, p agtype",
        graph_name=graph_name,
    )
    results = []
    for control, regulation, person in rows:
        results.append(
            {
                "control": (control or {}).get("properties", {}),
                "regulation": (regulation or {}).get("properties") if regulation else None,
                "responsible_person": (person or {}).get("properties") if person else None,
            }
        )
    return results
