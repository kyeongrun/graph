"""GraphRAG retrieval: pull a relevant subgraph around one or more entities
and render it as a compact text block suitable for prompt injection
alongside vector-search hits (e.g. from OpenSearch) in the RAG pipeline.
"""

from __future__ import annotations

from typing import Literal

import psycopg

from graphdb.cypher import run_cypher
from graphdb.schema import EdgeLabel, NodeLabel

_MAX_DEPTH = 3

Direction = Literal["both", "out", "in"]


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


async def get_node_by_id(
    cur: psycopg.AsyncCursor,
    node_id: str,
    *,
    graph_name: str | None = None,
) -> dict | None:
    """Fetch a single node by id regardless of whether it has any edges —
    `get_subgraph`'s `-[r*1..depth]-` pattern requires at least one hop, so
    an isolated seed node (no relations at all) would otherwise vanish from
    a RAG result even though it's exactly what the query matched."""
    query = "MATCH (n {id: $id}) RETURN n LIMIT 1"
    rows = await run_cypher(cur, query, {"id": node_id}, columns="n agtype", graph_name=graph_name)
    return rows[0][0] if rows else None


async def get_degree(
    cur: psycopg.AsyncCursor,
    node_id: str,
    *,
    graph_name: str | None = None,
) -> int:
    """Count of a node's direct (1-hop) edges, both directions.

    Cheap (~1s even for a 3,900-edge hub, live-verified 2026-08-16) compared
    to actually materializing a `depth>1` traversal from the same node —
    which for a real hub (금융위원회, degree 3906) took 936s and returned
    852,873 rows. Meant to be checked *before* choosing a traversal depth
    for a given seed, not after.
    """
    query = "MATCH (n {id: $id})-[r]-() RETURN count(r) AS c"
    rows = await run_cypher(cur, query, {"id": node_id}, columns="c agtype", graph_name=graph_name)
    return rows[0][0] if rows else 0


def _pattern(rel: str, direction: Direction) -> str:
    if direction == "out":
        return f"(n {{id: $id}})-[{rel}]->(m)"
    if direction == "in":
        return f"(n {{id: $id}})<-[{rel}]-(m)"
    return f"(n {{id: $id}})-[{rel}]-(m)"


async def get_subgraph(
    cur: psycopg.AsyncCursor,
    node_id: str,
    *,
    depth: int = 1,
    edge_types: list[EdgeLabel] | None = None,
    direction: Direction = "both",
    graph_name: str | None = None,
) -> list[tuple]:
    """Fetch the neighborhood around a node up to `depth` hops.

    `edge_types`, if given, restricts traversal to those relationship types
    only (narrows a query-time search, e.g. by keyword hints from the
    user's question — see `graphdb.query.edge_type_hints` — it never
    changes what edge_type an already-extracted relation was assigned).
    Each type comes from the `EdgeLabel` enum (never raw user input) since
    it's interpolated as a Cypher literal, not a bind parameter — same
    constraint as node labels elsewhere in this module.

    Implementation note: AGE 1.5.0's Cypher parser does NOT support the
    standard openCypher `-[r:TYPE1|TYPE2]-` multi-type disjunction syntax
    at all (live-verified 2026-08-16: `syntax error at or near "|"`, even
    for a non-variable-length pattern) — every relationship pattern here
    can only name one type. So when multiple `edge_types` are given, this
    issues one single-type query per type and unions the rows in Python,
    instead of one query with a type-list.

    `direction` picks `-[r]-` (both, default), `-[r]->` (out), or
    `<-[r]-` (in). Callers choosing "out"/"in" should be prepared to retry
    with "both" if the result comes back empty — this module doesn't
    guess direction from the question itself (no reliable signal for that
    in general Korean phrasing), so a wrong guess here is a caller-side
    concern, not something this function protects against.

    `depth` is clamped to keep queries bounded — but clamping alone does
    NOT bound cost: a `depth>1` traversal from a high-degree node can still
    blow up combinatorially (measured: 936s / 852,873 rows from a single
    depth=2 call on a 3,906-edge node). Callers should check `get_degree`
    first and cap `depth` to 1 for high-degree seeds.
    """
    depth = max(1, min(int(depth), _MAX_DEPTH))
    type_options: list[EdgeLabel | None] = list(edge_types) if edge_types else [None]

    all_rows: list[tuple] = []
    for edge_type in type_options:
        type_filter = f":{edge_type.value}" if edge_type is not None else ""
        rel = f"r{type_filter}*1..{depth}"
        query = f"MATCH {_pattern(rel, direction)} RETURN n, r, m"
        rows = await run_cypher(
            cur, query, {"id": node_id}, columns="n agtype, r agtype, m agtype", graph_name=graph_name
        )
        all_rows.extend(rows)
    return all_rows


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
