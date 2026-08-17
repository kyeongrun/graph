"""RAG query pipeline: question -> embed -> kNN-seeded graph traversal ->
LLM-generated answer + the traversed subgraph for visualization.

Rough v1 strategy (per user direction, 2026-08-16): embed the question,
pull the top-k most similar entities/relations from OpenSearch as seeds,
expand each seed into its AGE neighborhood, format that as context, and
have the LLM answer the question from it. Reranking and top-k tuning are
explicitly deferred — this is the simplest version that works end to end.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from graphdb.connection import GraphConnection
from graphdb.embeddings import embed_text
from graphdb.ingest.opensearch_loader import get_client as get_opensearch_client
from graphdb.llm import chat_text
from graphdb.query.edge_type_hints import infer_edge_types, infer_edge_types_llm, refine_edge_types_llm
from graphdb.query.retrieval import get_degree, get_node_by_id, get_subgraph
from graphdb.query.vector_search import knn_search_entities, knn_search_relations

logger = logging.getLogger(__name__)

# depth>=2 on a densely-connected legal graph blows up fast — one bad
# question with top_k=5/depth=2 produced a 261k-token context and a hard
# 400 from the LLM (its 262144-token limit), live-verified 2026-08-16.
# Cap what actually goes to the LLM; the fuller (but still bounded) node/
# edge set is still returned for the visualization, since rendering a big
# graph is cheap compared to blowing an LLM's context window.
_MAX_CONTEXT_LINES = 300
_MAX_RETURNED_NODES = 1000
_MAX_RETURNED_EDGES = 1500

# A single depth=2 traversal from a hub node (금융위원회, degree 3906) took
# 936s and returned 852,873 rows — live-measured 2026-08-16. A low-degree
# node (degree 2) took 0.45s for the same depth. `get_degree` is cheap
# (~1s even for the hub) so it's always worth checking before committing to
# depth>1 for a given seed. Threshold picked well below the observed
# blowup point, not tuned precisely — revisit with more degree samples if
# it turns out to cap too aggressively or too rarely.
_HUB_DEGREE_THRESHOLD = 300

_SYSTEM_PROMPT = (
    "당신은 대한민국 금융권 법령 지식그래프를 근거로 질문에 답하는 어시스턴트다. "
    "아래 '그래프 컨텍스트'에 나온 사실(엔티티 간 관계, 근거 법령/조항)만 사용해서 "
    "답하라. 컨텍스트에 없는 내용은 추측하지 말고, 근거가 부족하면 그렇다고 명시하라. "
    "가능하면 답변에 근거가 된 법령명과 조항 번호를 함께 언급하라."
)


@dataclass
class RagResult:
    answer: str
    seed_entities: list[dict]
    nodes: list[dict] = field(default_factory=list)
    edges: list[dict] = field(default_factory=list)
    context_truncated: bool = False
    hub_seeds_capped: int = 0
    edge_type_source: str | None = None  # "keyword" | "llm_category" | None (unrestricted)
    edge_type_refined: bool = False  # whether the second-stage LLM narrowing changed anything


def _vertex_to_node(vertex: dict) -> dict:
    props = vertex.get("properties", {})
    return {
        "id": props.get("id", vertex.get("id")),
        "name": props.get("name", "?"),
        "label": vertex.get("label", "?"),
        "description": props.get("description", ""),
    }


def _edge_to_edge(edge: dict, source_id: str, target_id: str) -> dict:
    props = edge.get("properties", {})
    return {
        "id": props.get("id", edge.get("id")),
        "source": source_id,
        "target": target_id,
        "edge_type": edge.get("label", "?"),
        "source_law": props.get("source_law"),
        "article_no": props.get("article_no"),
        "paragraph_no": props.get("paragraph_no"),
        "modality": props.get("modality"),
        "voice": props.get("voice"),
    }


def _build_context_and_graph(
    seed_rows: list[tuple],
) -> tuple[str, dict[str, dict], dict[str, dict]]:
    nodes: dict[str, dict] = {}
    edges: dict[str, dict] = {}
    lines: list[str] = []
    seen_lines: set[str] = set()

    for n, edge_list, m in seed_rows:
        n_node = _vertex_to_node(n)
        m_node = _vertex_to_node(m)
        nodes[n_node["id"]] = n_node
        nodes[m_node["id"]] = m_node

        edge_seq = edge_list if isinstance(edge_list, list) else [edge_list]
        for e in edge_seq:
            if not isinstance(e, dict):
                continue
            e_edge = _edge_to_edge(e, n_node["id"], m_node["id"])
            edges[e_edge["id"]] = e_edge

            article = f"{e_edge['source_law']} 제{e_edge['article_no']}조"
            if e_edge["paragraph_no"]:
                article += f" 제{e_edge['paragraph_no']}항"
            line = (
                f"[{article}] {n_node['name']} -[{e_edge['edge_type']}]-> {m_node['name']} "
                f"(modality={e_edge['modality']}, voice={e_edge['voice']})"
            )
            if line not in seen_lines:
                seen_lines.add(line)
                lines.append(line)

    return "\n".join(lines), nodes, edges


async def _traverse_seeds(
    cur,
    seed_ids: dict,
    *,
    depth: int,
    edge_types: list | None,
) -> tuple[list[tuple], dict[str, dict], int]:
    """Run the per-seed get_subgraph traversal once, applying the hub-node
    depth cap. Returns (rows, nodes-by-id-from-direct-lookup, hub_capped
    count) — factored out so `answer_question` can retry with a different
    `edge_types` (the empty-result fallback) without duplicating the
    degree-check/capping logic."""
    all_rows: list[tuple] = []
    nodes: dict[str, dict] = {}
    hub_capped = 0
    for seed_id in seed_ids:
        seed_vertex = await get_node_by_id(cur, seed_id)
        if seed_vertex is not None:
            node = _vertex_to_node(seed_vertex)
            nodes[node["id"]] = node

        seed_depth = depth
        if depth > 1:
            node_degree = await get_degree(cur, seed_id)
            if node_degree > _HUB_DEGREE_THRESHOLD:
                logger.info(
                    "hub seed capped to depth=1: id=%s degree=%d (requested depth=%d)",
                    seed_id, node_degree, depth,
                )
                seed_depth = 1
                hub_capped += 1

        rows = await get_subgraph(cur, seed_id, depth=seed_depth, edge_types=edge_types)
        all_rows.extend(rows)
    return all_rows, nodes, hub_capped


async def answer_question(question: str, *, top_k: int = 5, depth: int = 1) -> RagResult:
    query_vector = embed_text(question)
    os_client = get_opensearch_client()

    seed_entity_hits = knn_search_entities(os_client, query_vector, k=top_k)
    seed_relation_hits = knn_search_relations(os_client, query_vector, k=top_k)

    seed_ids: dict[str, dict] = {e["id"]: e for e in seed_entity_hits}
    for r in seed_relation_hits:
        for eid in (r["source_entity_id"], r["target_entity_id"]):
            seed_ids.setdefault(eid, {"id": eid, "name": None, "label": None, "score": r["score"]})

    # Narrow traversal to question-relevant edge types: keyword table first
    # (free, instant), LLM category routing only if that finds nothing
    # (picks from 12 categories, never free-form — see edge_type_hints.py).
    # Falls back to an unfiltered retraversal below if even that returns
    # nothing, since a routing miss shouldn't silently produce an empty
    # answer.
    edge_types = infer_edge_types(question)
    edge_type_source = "keyword" if edge_types else None
    if edge_types is None:
        edge_types = infer_edge_types_llm(question)
        if edge_types is not None:
            edge_type_source = "llm_category"

    # Second-stage LLM narrowing only runs on the LLM-category tier, NOT
    # on a keyword-tier match. Reasoning (same rule/LLM boundary this
    # project already draws elsewhere, e.g. svo.py's output): a keyword
    # hit is a deterministic, hand-curated rule — letting an LLM
    # re-litigate its output risks the LLM silently overriding a rule
    # that was right, which is exactly the failure this project has
    # avoided elsewhere. Live-verified 2026-08-18: for "...보고를
    # 요구하는 조항..." (keyword "보고" -> NOTIFIES/SUBMITS/RECORDS),
    # refine dropped NOTIFIES — the single most relevant type — even
    # though it's a small, already-precise 4-item set. The LLM-category
    # tier is different: it's inherently coarse (up to 12 types from one
    # category), so narrowing it is cutting real noise, not overruling a
    # rule.
    edge_type_refined = False
    if edge_types and edge_type_source == "llm_category":
        refined = refine_edge_types_llm(question, edge_types)
        if refined != edge_types:
            edge_type_refined = True
        edge_types = refined

    conn = GraphConnection()
    await conn.open()
    try:
        async with conn.cursor() as cur:
            all_rows, nodes, hub_capped = await _traverse_seeds(
                cur, seed_ids, depth=depth, edge_types=edge_types
            )
            if edge_types and not all_rows:
                logger.info("edge_type filter %s returned nothing, retrying unfiltered", edge_types)
                edge_type_source = None
                edge_type_refined = False
                all_rows, nodes, hub_capped = await _traverse_seeds(
                    cur, seed_ids, depth=depth, edge_types=None
                )
    finally:
        await conn.close()

    context, expanded_nodes, edges = _build_context_and_graph(all_rows)
    nodes.update(expanded_nodes)

    # seed_relation_hits contributed endpoint ids with name=None/label=None
    # (OpenSearch's relation docs don't carry endpoint label) — backfill
    # from the AGE-fetched node info now that we have it, so the "시드
    # 엔티티" panel doesn't show blank names for relation-derived seeds.
    for sid, info in seed_ids.items():
        if info.get("name") is None and sid in nodes:
            info["name"] = nodes[sid]["name"]
            info["label"] = nodes[sid]["label"]

    context_lines = context.split("\n") if context else []
    context_truncated = len(context_lines) > _MAX_CONTEXT_LINES
    if context_truncated:
        logger.warning(
            "RAG context truncated: %d lines -> %d for LLM (depth=%d, top_k=%d, %d nodes/%d edges total)",
            len(context_lines), _MAX_CONTEXT_LINES, depth, top_k, len(nodes), len(edges),
        )
        context_lines = context_lines[:_MAX_CONTEXT_LINES]

    if not context_lines:
        answer = "그래프에서 이 질문과 관련된 근거를 찾지 못했습니다."
    else:
        llm_context = "\n".join(context_lines)
        if context_truncated:
            llm_context += (
                f"\n\n[참고: 탐색된 관계가 너무 많아 상위 {_MAX_CONTEXT_LINES}개만 표시함 — "
                "답변이 불완전할 수 있음]"
            )
        user_prompt = f"질문: {question}\n\n그래프 컨텍스트:\n{llm_context}"
        answer = chat_text(_SYSTEM_PROMPT, user_prompt)

    return RagResult(
        answer=answer,
        seed_entities=list(seed_ids.values()),
        nodes=list(nodes.values())[:_MAX_RETURNED_NODES],
        edges=list(edges.values())[:_MAX_RETURNED_EDGES],
        context_truncated=context_truncated,
        hub_seeds_capped=hub_capped,
        edge_type_source=edge_type_source,
        edge_type_refined=edge_type_refined,
    )
