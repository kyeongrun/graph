from __future__ import annotations

import json
import re
from typing import Any, Sequence

import psycopg

from graphdb.config import get_settings
from graphdb.schema import EdgeLabel, NodeLabel

# Apache AGE renders composite results as `<json-payload>::<type_tag>`,
# e.g. `{"id":..,"label":"Company","properties":{...}}::vertex`.
_AGTYPE_SUFFIX_RE = re.compile(r"::(vertex|edge|path|[a-zA-Z0-9_]+)$")


def parse_agtype(raw: Any) -> Any:
    """Parse a single agtype column value into plain Python data.

    Vertices/edges come back as dicts with an extra ``_agtype`` tag so
    callers can tell a node apart from a plain map. Scalars, lists and
    nested maps are returned as-is via ``json.loads``.
    """
    if raw is None:
        return None
    if not isinstance(raw, str):
        return raw

    match = _AGTYPE_SUFFIX_RE.search(raw)
    payload, type_tag = (raw[: match.start()], match.group(1)) if match else (raw, None)

    try:
        value = json.loads(payload)
    except json.JSONDecodeError:
        return raw

    if type_tag in ("vertex", "edge") and isinstance(value, dict):
        value = {**value, "_agtype": type_tag}
    return value


def parse_row(row: Sequence[Any]) -> tuple[Any, ...]:
    return tuple(parse_agtype(col) for col in row)


async def run_cypher(
    cur: psycopg.AsyncCursor,
    query: str,
    params: dict | None = None,
    *,
    columns: str = "result agtype",
    graph_name: str | None = None,
) -> list[tuple[Any, ...]]:
    """Execute a Cypher query against the AGE graph and return parsed rows.

    `columns` must match the RETURN clause shape, e.g. "n agtype" for a
    single-column result or "n agtype, r agtype" for two. `params` are
    passed through AGE's native `$name` parameter binding (never string
    interpolated into the query text), so untrusted values are safe here.
    """
    graph = graph_name or get_settings().graph_name
    sql = f"SELECT * FROM cypher(%s, %s, %s::agtype) AS ({columns})"
    await cur.execute(sql, (graph, query, json.dumps(params or {}, default=str)))
    rows = await cur.fetchall()
    return [parse_row(row) for row in rows]


async def upsert_node_raw(
    cur: psycopg.AsyncCursor,
    label: NodeLabel,
    node_id: str,
    properties: dict[str, Any],
    *,
    graph_name: str | None = None,
) -> dict[str, Any] | None:
    """MERGE a node by (label, id), merging `properties` on top via SET n += .

    `label` must come from the `NodeLabel` enum (never raw user input) since
    Cypher requires the label to be a literal, not a bind parameter.
    """
    query = f"""
        MERGE (n:{label.value} {{id: $id}})
        SET n += $props
        RETURN n
    """
    rows = await run_cypher(
        cur, query, {"id": node_id, "props": properties}, columns="n agtype", graph_name=graph_name
    )
    return rows[0][0] if rows else None


async def upsert_edge_raw(
    cur: psycopg.AsyncCursor,
    label: EdgeLabel,
    start_label: NodeLabel,
    start_id: str,
    end_label: NodeLabel,
    end_id: str,
    properties: dict[str, Any],
    *,
    graph_name: str | None = None,
) -> dict[str, Any] | None:
    """MERGE an edge between two existing nodes, matched by (label, id).

    Returns None if either endpoint does not exist (MATCH finds nothing).
    """
    query = f"""
        MATCH (a:{start_label.value} {{id: $start_id}}), (b:{end_label.value} {{id: $end_id}})
        MERGE (a)-[r:{label.value}]->(b)
        SET r += $props
        RETURN r
    """
    rows = await run_cypher(
        cur,
        query,
        {"start_id": start_id, "end_id": end_id, "props": properties},
        columns="r agtype",
        graph_name=graph_name,
    )
    return rows[0][0] if rows else None


async def find_node_id_by_name(
    cur: psycopg.AsyncCursor,
    label: NodeLabel,
    name: str,
    *,
    graph_name: str | None = None,
) -> str | None:
    """Look up an existing node's `id` by (label, name), for entity
    resolution when merging LLM-extracted entities into the graph."""
    query = f"MATCH (n:{label.value} {{name: $name}}) RETURN n.id AS id LIMIT 1"
    rows = await run_cypher(cur, query, {"name": name}, columns="id agtype", graph_name=graph_name)
    return rows[0][0] if rows else None
