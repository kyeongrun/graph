"""Entity typing: surface text (an SVO agent/patient mention) -> NodeLabel +
the label-specific subtype property (category/role_hint/doc_type/
concept_type). Dictionary-first, LLM fills in only what the dictionary
can't resolve — CLAUDE.md "5단계" role table: "고유명사·정부기관은 사전
매칭 우선, '해당 기관'/'소속 금융회사' 같은 문맥 의존 표현만 LLM".

Unlike edge_type (a closed 64-value set), category/role_hint/doc_type/
concept_type are explicitly open vocabularies (entity_schema_draft.md: "값
목록은 아직 확정 안 함") — so the LLM here proposes free-text subtype
values instead of choosing from an enum. NodeLabel itself (4 values) is
still constrained.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from graphdb.llm import chat_json
from graphdb.schema import NodeLabel
from graphdb.typing.dictionaries import (
    CONCEPT_KEYWORDS_SUFFIXES,
    ORG_SUFFIXES,
    PERSON_ROLE_SUFFIXES,
    looks_like_law_instrument,
    resolve_alias,
)

logger = logging.getLogger(__name__)

_BATCH_SIZE = 50


@dataclass
class EntityType:
    label: NodeLabel
    subtype: str | None  # category/role_hint/doc_type/concept_type depending on label
    method: str  # "dict" | "llm" | "llm_fallback_default"


def _dict_lookup(name: str) -> EntityType | None:
    if looks_like_law_instrument(name):
        return EntityType(NodeLabel.LEGAL_DOCUMENT, "법령", "dict")
    for suf in PERSON_ROLE_SUFFIXES:
        if name.endswith(suf):
            return EntityType(NodeLabel.PERSON, suf, "dict")
    for suf in ORG_SUFFIXES:
        if name.endswith(suf):
            return EntityType(NodeLabel.ORGANIZATION, suf, "dict")
    for suf in CONCEPT_KEYWORDS_SUFFIXES:
        if name.endswith(suf):
            return EntityType(NodeLabel.CONCEPT, suf, "dict")
    return None


_LLM_SCHEMA = {
    "type": "object",
    "properties": {
        "classifications": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "label": {
                        "type": "string",
                        "enum": ["Organization", "Person", "LegalDocument", "Concept"],
                    },
                    "subtype": {"type": "string"},
                },
                "required": ["index", "label", "subtype"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["classifications"],
    "additionalProperties": False,
}

_SYSTEM = (
    "당신은 대한민국 금융권 법령 문장에서 추출된 개체명(사람이 아니라 표면 "
    "텍스트)을 4개의 카테고리 중 하나로 분류한다: "
    "Organization(회사/기관/조직/직위-기관 자체), "
    "Person(자연인 또는 사람의 역할/신분), "
    "LegalDocument(법률/시행령/시행규칙/고시 등 법령 문서 자체), "
    "Concept(금융상품/제도/기준 등 추상 개념). "
    "각 항목에 대해 가장 적합한 label 하나와, 그 label에 어울리는 "
    "간단한 subtype(예: Organization이면 '정부기관'/'금융회사' 등, "
    "Person이면 '임원'/'소비자' 등, LegalDocument면 '법률'/'대통령령' 등, "
    "Concept이면 '금융상품'/'내부통제' 등)을 한국어 짧은 명사로 제시한다."
)


def _llm_type_batch(names: list[str]) -> dict[str, EntityType]:
    if not names:
        return {}
    resolved: dict[str, EntityType] = {}
    for start in range(0, len(names), _BATCH_SIZE):
        batch = names[start : start + _BATCH_SIZE]
        user = "\n".join(f"[{i}] {name}" for i, name in enumerate(batch))
        try:
            parsed = chat_json(_SYSTEM, user, _LLM_SCHEMA, schema_name="entity_typing_batch")
            for c in parsed["classifications"]:
                idx = c["index"]
                if 0 <= idx < len(batch):
                    resolved[batch[idx]] = EntityType(NodeLabel(c["label"]), c["subtype"], "llm")
        except Exception:
            logger.exception("LLM entity typing batch failed for %d names", len(batch))
    return resolved


def type_entities(names: list[str]) -> dict[str, EntityType]:
    """Resolve every distinct mention text in `names` to an EntityType.
    Returns a dict keyed by the ORIGINAL (pre-alias) name so callers can
    look up by whatever text they extracted; alias resolution is a
    separate, orthogonal step (see dictionaries.resolve_alias)."""
    unique = sorted(set(names))
    results: dict[str, EntityType] = {}
    unresolved: list[str] = []
    for name in unique:
        hit = _dict_lookup(resolve_alias(name))
        if hit is not None:
            results[name] = hit
        else:
            unresolved.append(name)

    llm_results = _llm_type_batch(unresolved)
    for name in unresolved:
        results[name] = llm_results.get(
            name, EntityType(NodeLabel.CONCEPT, None, "llm_fallback_default")
        )
    return results
