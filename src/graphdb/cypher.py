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

_GRAPH_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_PROP_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def map_literal(properties: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Build a `{k1: $p_k1, k2: $p_k2, ...}` Cypher map literal (for inline
    node/edge properties in a MERGE pattern) and its matching flattened
    param dict.

    Verified against a live instance (2026-08-16): AGE 1.5.0 edges have a
    separate bug from the one `flattened_set_clause` works around — a
    post-MERGE `SET rel.k = $v` (map-form *or* flattened per-key form)
    shows the new value in that same statement's `RETURN`, but the write
    doesn't actually persist; a fresh read (even same transaction, same
    connection) comes back with only the properties that were part of the
    original MERGE pattern. Properties baked into the MERGE pattern itself
    (`MERGE (a)-[rel:TYPE {id: $id, k: $v, ...}]->(b)`) persist correctly.
    This only matters for edges we know are immutable per-id (never
    re-set with different values for the same id, e.g. relation rows here
    are write-once from RDB) — MERGE then treats the full map as its match
    key, which is fine exactly because it never varies for a given id.
    """
    params: dict[str, Any] = {}
    parts: list[str] = []
    for key, value in properties.items():
        if not _PROP_KEY_RE.fullmatch(key):
            raise ValueError(f"unsafe AGE property key: {key!r}")
        param_name = f"p_{key}"
        parts.append(f"{key}: ${param_name}")
        params[param_name] = value
    return "{" + ", ".join(parts) + "}", params


def flattened_set_clause(var: str, properties: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Build a `SET var.k1 = $p_k1, var.k2 = $p_k2, ...` clause and its
    matching flattened param dict.

    This AGE version (1.5.0) errors ("SET clause expects a map") on
    `SET n += $props` when `$props` is an external query parameter rather
    than a map literal or another node's property map — verified against a
    live instance, not documented anywhere obvious. Setting each property
    individually sidesteps it. Keys are validated as bare identifiers since
    they're interpolated into the query text (always come from this
    codebase's own property dicts, never user input).
    """
    params: dict[str, Any] = {}
    clauses: list[str] = []
    for key, value in properties.items():
        if not _PROP_KEY_RE.fullmatch(key):
            raise ValueError(f"unsafe AGE property key: {key!r}")
        param_name = f"p_{key}"
        clauses.append(f"{var}.{key} = ${param_name}")
        params[param_name] = value
    return ", ".join(clauses), params


_json_decoder = json.JSONDecoder()
_LIST_ELEMENT_TAG_RE = re.compile(r"::([a-zA-Z0-9_]+)")


def _parse_agtype_list_body(body: str) -> list[Any]:
    """Parse the inside of a `[...]` agtype list whose elements are
    individually tagged (`{...}::edge, {...}::edge`) — the case a bare
    `json.loads` can't handle, since `::edge` isn't valid JSON. This is how
    AGE serializes a variable-length-path column (`-[r*1..N]-`), even when
    the column as a whole carries no outer type tag. Uses
    `json.JSONDecoder.raw_decode` to parse one element at a time (correctly
    handling nested braces/strings, unlike a brace-counting regex) and reads
    off each element's own `::tag` suffix, if any, right after it.
    """
    items: list[Any] = []
    i, n = 0, len(body)
    while i < n:
        while i < n and body[i] in " \t\n\r,":
            i += 1
        if i >= n:
            break
        obj, end = _json_decoder.raw_decode(body, i)
        i = end
        tag_match = _LIST_ELEMENT_TAG_RE.match(body, i)
        if tag_match:
            tag = tag_match.group(1)
            i = tag_match.end()
            if tag in ("vertex", "edge") and isinstance(obj, dict):
                obj = {**obj, "_agtype": tag}
        items.append(obj)
    return items


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
        stripped = raw.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            return _parse_agtype_list_body(stripped[1:-1])
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

    AGE's `cypher()` is a parse-time special form: the PostgreSQL parser
    rewrites it into a per-query row type before execution, which requires
    the graph name AND the query text to be literal constants in the SQL —
    binding either as a `$1`-style parameter fails ("a name constant is
    expected" / "type agtype does not exist", verified against a live AGE
    instance; this module had never actually been exercised against a
    running AGE server before). Only the third `params` argument is a real
    bind parameter, evaluated at execution time. `graph` is validated as a
    bare identifier and `query` is dollar-quoted before being inlined —
    both come from this codebase's own callers, never raw user input.
    """
    graph = graph_name or get_settings().graph_name
    if not _GRAPH_NAME_RE.fullmatch(graph):
        raise ValueError(f"unsafe AGE graph name: {graph!r}")
    sql = f"SELECT * FROM cypher('{graph}', $CYPHER${query}$CYPHER$, %s) AS ({columns})"
    await cur.execute(sql, (json.dumps(params or {}, default=str),))
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
    """MERGE a node by (label, id), setting `properties` on top individually.

    `label` must come from the `NodeLabel` enum (never raw user input) since
    Cypher requires the label to be a literal, not a bind parameter.
    """
    set_clause, prop_params = flattened_set_clause("n", properties)
    query = f"""
        MERGE (n:{label.value} {{id: $id}})
        {"SET " + set_clause if set_clause else ""}
        RETURN n
    """
    rows = await run_cypher(
        cur, query, {"id": node_id, **prop_params}, columns="n agtype", graph_name=graph_name
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

    KNOWN LIMITATION (verified live, 2026-08-16, see `map_literal`'s
    docstring): the post-MERGE `SET` here does not actually persist
    property updates on edges in AGE 1.5.0 — it will silently no-op on
    every call after the edge's first creation. This function is currently
    unused by any loader; `graphdb.ingest.age_loader` bakes properties into
    the MERGE pattern itself via `map_literal` instead, which works, but
    only because its properties are write-once and never change for a
    given id — that trick isn't a valid fix here since it would turn a
    genuine property *update* into a MERGE-key mismatch (a new edge
    instead of an update). Don't use this function to update an existing
    edge's properties until AGE's behavior changes; safe only for
    create-and-never-touch-again edges.
    """
    set_clause, prop_params = flattened_set_clause("r", properties)
    query = f"""
        MATCH (a:{start_label.value} {{id: $start_id}}), (b:{end_label.value} {{id: $end_id}})
        MERGE (a)-[r:{label.value}]->(b)
        {"SET " + set_clause if set_clause else ""}
        RETURN r
    """
    rows = await run_cypher(
        cur,
        query,
        {"start_id": start_id, "end_id": end_id, **prop_params},
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
