"""Load explicit domain entities (org chart, regulations, controls, risks, ...)
from structured YAML files into the AGE graph.

YAML shape (see data/domain/*.yaml for full examples)::

    nodes:
      - type: Company
        id: co-shinhan
        name: 신한금융지주

    edges:
      - label: BELONGS_TO
        start: {type: Department, id: dept-compliance}
        end: {type: Company, id: co-shinhan}
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import psycopg
import yaml

from graphdb.connection import GraphConnection
from graphdb.cypher import upsert_edge_raw, upsert_node_raw
from graphdb.models.entities import (
    Company,
    ControlItem,
    Department,
    Edge,
    Law,
    Node,
    Person,
    Process,
    Regulation,
    Risk,
)
from graphdb.schema import EdgeLabel, NodeLabel

logger = logging.getLogger(__name__)

NODE_MODELS: dict[str, type[Node]] = {
    NodeLabel.COMPANY.value: Company,
    NodeLabel.DEPARTMENT.value: Department,
    NodeLabel.PERSON.value: Person,
    NodeLabel.REGULATION.value: Regulation,
    NodeLabel.LAW.value: Law,
    NodeLabel.CONTROL_ITEM.value: ControlItem,
    NodeLabel.RISK.value: Risk,
    NodeLabel.PROCESS.value: Process,
}


@dataclass
class LoadStats:
    nodes_upserted: int = 0
    edges_upserted: int = 0
    errors: list[str] = field(default_factory=list)


def parse_node(raw: dict[str, Any]) -> Node:
    node_type = raw["type"]
    model = NODE_MODELS.get(node_type)
    if model is None:
        raise ValueError(f"Unknown node type '{node_type}'. Known types: {sorted(NODE_MODELS)}")
    fields = {k: v for k, v in raw.items() if k != "type"}
    return model(**fields)


def parse_edge(raw: dict[str, Any]) -> Edge:
    start, end = raw["start"], raw["end"]
    return Edge(
        label=EdgeLabel(raw["label"]),
        start_label=NodeLabel(start["type"]),
        start_id=start["id"],
        end_label=NodeLabel(end["type"]),
        end_id=end["id"],
        properties=raw.get("properties", {}),
    )


async def upsert_node(
    cur: psycopg.AsyncCursor, node: Node, *, graph_name: str | None = None
) -> dict[str, Any] | None:
    return await upsert_node_raw(
        cur, node.label, node.id, node.properties(), graph_name=graph_name
    )


async def upsert_edge(
    cur: psycopg.AsyncCursor, edge: Edge, *, graph_name: str | None = None
) -> dict[str, Any] | None:
    props = dict(edge.properties)
    props["source"] = edge.source
    if edge.document_id:
        props["document_id"] = edge.document_id
    return await upsert_edge_raw(
        cur,
        edge.label,
        edge.start_label,
        edge.start_id,
        edge.end_label,
        edge.end_id,
        props,
        graph_name=graph_name,
    )


def load_yaml_file(path: Path) -> tuple[list[Node], list[Edge]]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    nodes = [parse_node(n) for n in raw.get("nodes", [])]
    edges = [parse_edge(e) for e in raw.get("edges", [])]
    return nodes, edges


async def load_domain_file(conn: GraphConnection, path: Path) -> LoadStats:
    stats = LoadStats()
    nodes, edges = load_yaml_file(path)

    async with conn.cursor() as cur:
        for node in nodes:
            try:
                await upsert_node(cur, node)
                stats.nodes_upserted += 1
            except Exception as exc:  # noqa: BLE001 - collect and continue
                stats.errors.append(f"node {node.label.value}:{node.id} failed: {exc}")
                logger.exception("Failed to upsert node %s:%s", node.label.value, node.id)

        for edge in edges:
            try:
                result = await upsert_edge(cur, edge)
                if result is None:
                    stats.errors.append(
                        f"edge {edge.label.value} {edge.start_id}->{edge.end_id}: "
                        "endpoint not found (load nodes first)"
                    )
                else:
                    stats.edges_upserted += 1
            except Exception as exc:  # noqa: BLE001 - collect and continue
                stats.errors.append(
                    f"edge {edge.label.value} {edge.start_id}->{edge.end_id} failed: {exc}"
                )
                logger.exception(
                    "Failed to upsert edge %s %s->%s", edge.label.value, edge.start_id, edge.end_id
                )

    logger.info(
        "Loaded %s: %d nodes, %d edges, %d errors",
        path.name,
        stats.nodes_upserted,
        stats.edges_upserted,
        len(stats.errors),
    )
    return stats
