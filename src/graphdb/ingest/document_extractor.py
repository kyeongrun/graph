"""LLM-based entity/relation extraction from internal control documents.

Uses the project's existing vLLM-served chat model (OpenAI-compatible API)
through langchain's structured-output support to pull entities/relations
out of a document chunk, then merges them into the same AGE graph used by
the domain loader — tagged `source="document"` with provenance
(`document_id`, `chunk_id`) so extracted claims can be traced back to text.

Entity resolution is name-based: before creating a new node, we look for an
existing node with the same (label, name) so an extraction that mentions
e.g. "정보보안관리규정" reuses the domain-loaded Regulation node instead of
creating a duplicate.
"""

from __future__ import annotations

import hashlib
import logging
import os

import psycopg
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from graphdb.connection import GraphConnection
from graphdb.cypher import find_node_id_by_name, upsert_edge_raw, upsert_node_raw
from graphdb.models.entities import Document
from graphdb.schema import EXTRACTABLE_NODE_LABELS, EdgeLabel, NodeLabel

logger = logging.getLogger(__name__)

_EXTRACTABLE_LABELS_TEXT = ", ".join(label.value for label in EXTRACTABLE_NODE_LABELS)
_EDGE_LABELS_TEXT = ", ".join(label.value for label in EdgeLabel)

_EXTRACTION_SYSTEM_PROMPT = """당신은 금융지주회사 내부통제 문서에서 지식그래프용 엔티티와 관계를 추출하는 전문가입니다.

엔티티는 다음 유형만 추출하세요: {labels}.
관계는 다음 유형 중에서만 선택하세요: {edge_labels}.

규칙:
- 텍스트에 명시적 근거가 없는 엔티티/관계는 추출하지 마세요. 확실하지 않으면 생략하세요.
- 엔티티 이름은 문서에 등장하는 표현을 최대한 그대로 사용하세요 (임의로 정규화하지 마세요).
- 관계의 source_name/target_name은 반드시 함께 추출한 엔티티 이름과 정확히 일치해야 합니다."""


class ExtractedEntity(BaseModel):
    label: NodeLabel = Field(description=f"엔티티 유형. 다음 중 하나: {_EXTRACTABLE_LABELS_TEXT}")
    name: str = Field(description="문서에 등장하는 원문 그대로의 엔티티 이름")
    properties: dict[str, str] = Field(
        default_factory=dict,
        description="선택적 부가 속성 (예: severity, category, control_type, article)",
    )


class ExtractedRelation(BaseModel):
    label: EdgeLabel = Field(description=f"관계 유형. 다음 중 하나: {_EDGE_LABELS_TEXT}")
    source_name: str = Field(description="관계의 시작 엔티티 이름 (entities 목록의 name과 일치)")
    target_name: str = Field(description="관계의 끝 엔티티 이름 (entities 목록의 name과 일치)")


class ExtractionResult(BaseModel):
    entities: list[ExtractedEntity] = Field(default_factory=list)
    relations: list[ExtractedRelation] = Field(default_factory=list)


def default_llm() -> ChatOpenAI:
    """Chat model pointed at the project's local vLLM server (see the
    'LLM 및 에이전트' section of the project's environment: Qwen/Qwen3.6-27B
    served on port 8000, OpenAI-compatible)."""
    return ChatOpenAI(
        model=os.environ.get("LLM_MODEL_NAME", "Qwen/Qwen3.6-27B"),
        base_url=os.environ.get("LLM_BASE_URL", "http://localhost:8000/v1"),
        api_key=os.environ.get("LLM_API_KEY", "not-needed"),
        temperature=0,
    )


def build_extraction_chain(llm: ChatOpenAI | None = None):
    llm = llm or default_llm()
    structured_llm = llm.with_structured_output(ExtractionResult)
    prompt = ChatPromptTemplate.from_messages(
        [("system", _EXTRACTION_SYSTEM_PROMPT), ("human", "{chunk_text}")]
    )
    return prompt | structured_llm


async def extract_from_chunk(chunk_text: str, *, llm: ChatOpenAI | None = None) -> ExtractionResult:
    chain = build_extraction_chain(llm)
    result = await chain.ainvoke(
        {"labels": _EXTRACTABLE_LABELS_TEXT, "edge_labels": _EDGE_LABELS_TEXT, "chunk_text": chunk_text}
    )
    if not isinstance(result, ExtractionResult):
        # Some structured-output backends return a dict instead of the model.
        result = ExtractionResult.model_validate(result)
    return result


def _generate_document_entity_id(label: NodeLabel, name: str) -> str:
    digest = hashlib.sha1(f"{label.value}:{name}".encode("utf-8")).hexdigest()[:12]
    return f"doc-{label.value.lower()}-{digest}"


async def _resolve_or_create_entity_id(
    cur: psycopg.AsyncCursor, label: NodeLabel, name: str, *, graph_name: str | None = None
) -> str:
    existing = await find_node_id_by_name(cur, label, name, graph_name=graph_name)
    return existing or _generate_document_entity_id(label, name)


async def merge_extraction_into_graph(
    conn: GraphConnection,
    document: Document,
    chunk_id: str,
    result: ExtractionResult,
    *,
    graph_name: str | None = None,
) -> dict[str, int]:
    stats = {"entities": 0, "relations": 0, "skipped_relations": 0}

    async with conn.cursor() as cur:
        await upsert_node_raw(
            cur, NodeLabel.DOCUMENT, document.id, document.properties(), graph_name=graph_name
        )

        name_to_id: dict[str, str] = {}
        name_to_label: dict[str, NodeLabel] = {}
        for entity in result.entities:
            if entity.label not in EXTRACTABLE_NODE_LABELS:
                logger.warning("Skipping disallowed extracted label %s for %r", entity.label, entity.name)
                continue

            entity_id = await _resolve_or_create_entity_id(
                cur, entity.label, entity.name, graph_name=graph_name
            )
            props = {
                **entity.properties,
                "name": entity.name,
                "source": "document",
                "document_id": document.id,
            }
            await upsert_node_raw(cur, entity.label, entity_id, props, graph_name=graph_name)
            name_to_id[entity.name] = entity_id
            name_to_label[entity.name] = entity.label
            stats["entities"] += 1

            await upsert_edge_raw(
                cur,
                EdgeLabel.MENTIONS,
                NodeLabel.DOCUMENT,
                document.id,
                entity.label,
                entity_id,
                {"chunk_id": chunk_id, "source": "document"},
                graph_name=graph_name,
            )

        for relation in result.relations:
            src_id = name_to_id.get(relation.source_name)
            dst_id = name_to_id.get(relation.target_name)
            if not src_id or not dst_id:
                stats["skipped_relations"] += 1
                logger.warning(
                    "Skipping relation %s: unresolved endpoint(s) %r -> %r",
                    relation.label,
                    relation.source_name,
                    relation.target_name,
                )
                continue
            await upsert_edge_raw(
                cur,
                relation.label,
                name_to_label[relation.source_name],
                src_id,
                name_to_label[relation.target_name],
                dst_id,
                {"source": "document", "document_id": document.id, "chunk_id": chunk_id},
                graph_name=graph_name,
            )
            stats["relations"] += 1

    logger.info("Merged extraction for document=%s chunk=%s: %s", document.id, chunk_id, stats)
    return stats
