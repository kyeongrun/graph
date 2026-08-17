"""LLM disambiguation for the narrow edge_type cases the deterministic
root->edge_type mapping can't resolve alone (CLAUDE.md "5단계" role table):

- needs_context roots (처분/임면 — edge_type_mapping.jsonl already ships a
  default + a 2-way `edge_type_alt`): a closed 2-candidate choice.
- the AMBIGUOUS bucket (하다/이루어지다/... — verb_roots_ambiguous.jsonl,
  no default at all): choose among the fixed 64 EdgeLabel values, or NONE
  if the clause isn't really a graph-worthy relation.
- unmapped roots (2026-08-18 addition): a verb root that's in none of
  action/ambiguous/DEF/REF/STATIVE root lists — i.e. genuinely never seen
  during the original corpus-wide classification. Only possible for
  documents added after that classification (the current 60-file corpus
  has zero of these — see pipeline.py's `resolve_edge_types`); without
  this, such a root would silently be dropped as "not an action" even
  though nobody ever actually checked that. Same closed-candidate choice
  as the AMBIGUOUS bucket, just triggered by "unclassified" instead of
  "known to be ambiguous."

All cases only ever pick from an already-fixed candidate list — never
invent a new edge_type. This mirrors edge_disambiguation's sibling
graphdb.typing.entity_typing, split out because it operates on
EdgeLabel/relations rather than NodeLabel/entities.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from graphdb.llm import chat_json
from graphdb.schema import EdgeLabel

logger = logging.getLogger(__name__)

_ALL_EDGE_TYPES = [e.value for e in EdgeLabel]
_BATCH_SIZE = 50
_NONE = "NONE"


@dataclass
class DisambiguationItem:
    index: int
    agent: str | None
    verb_lemma: str
    patient: str | None
    evidence_text: str


def _clause_desc(item: DisambiguationItem) -> str:
    agent = item.agent or "(생략)"
    patient = item.patient or "(생략)"
    evidence = item.evidence_text[:200]
    return f"[{item.index}] 주어={agent} / 동사={item.verb_lemma} / 목적어={patient} / 원문: {evidence}"


def _classify_batch(
    items: list[DisambiguationItem], candidates: list[str], task_desc: str
) -> dict[int, str]:
    if not items:
        return {}
    schema = {
        "type": "object",
        "properties": {
            "classifications": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "index": {"type": "integer"},
                        "edge_type": {"type": "string", "enum": candidates},
                    },
                    "required": ["index", "edge_type"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["classifications"],
        "additionalProperties": False,
    }
    system = (
        "당신은 대한민국 금융권 법령 문장에서 이미 추출된 (주어, 동사, 목적어) "
        f"절을 보고, {task_desc} 후보 목록에 없는 값은 절대 만들어내지 않는다. "
        "입력에 있던 모든 index에 대해 반드시 하나씩 분류 결과를 낸다."
    )

    results: dict[int, str] = {}
    for start in range(0, len(items), _BATCH_SIZE):
        batch = items[start : start + _BATCH_SIZE]
        batch_user = "\n".join(_clause_desc(item) for item in batch)
        try:
            parsed = chat_json(system, batch_user, schema, schema_name="edge_type_batch")
            for c in parsed["classifications"]:
                if c["edge_type"] in candidates:
                    results[c["index"]] = c["edge_type"]
        except Exception:
            logger.exception(
                "LLM edge_type batch classification failed for %d items (task=%s)",
                len(batch),
                task_desc,
            )
    return results


def disambiguate_needs_context(
    items_by_root: dict[str, list[DisambiguationItem]],
    alt_by_root: dict[str, list[str]],
    default_by_root: dict[str, str],
) -> dict[int, str]:
    resolved: dict[int, str] = {}
    for root, items in items_by_root.items():
        candidates = [default_by_root[root], *alt_by_root[root]]
        task = f"'{root}하다'가 이 문맥에서 정확히 어떤 관계(edge_type)에 해당하는지 아래"
        resolved.update(_classify_batch(items, candidates, task))
    return resolved


def disambiguate_unmapped_root(items: list[DisambiguationItem]) -> dict[int, str]:
    """For verb roots not present in ANY of the corpus's root
    classifications (action/ambiguous/DEF/REF/STATIVE) — see module
    docstring. Only reachable for documents outside the original 60-file
    corpus."""
    candidates = [*_ALL_EDGE_TYPES, _NONE]
    task = (
        "이 동사 어근은 기존 어근 분류 사전(정상 행위 동사/모호 동사/정의·참조·"
        "상태 표현)에 전혀 없는, 처음 보는 어근이다. 문맥(주어/목적어/원문)을 "
        "보고 이게 실제 행위/관계를 나타내는 문장인지 판단하라. 실제 관계라면 "
        "가장 가까운 edge_type을 64개 중에서 고르고, 정의/참조/단순 상태 서술 "
        "등 관계가 아니라고 판단되면 'NONE'을 선택한다. 아래"
    )
    return _classify_batch(items, candidates, task)


def disambiguate_ambiguous(items: list[DisambiguationItem]) -> dict[int, str]:
    candidates = [*_ALL_EDGE_TYPES, _NONE]
    task = (
        "동사가 전부 대동사 '하다'(또는 '이루어지다'/'아니하다' 등 의미가 "
        "빈 대동사)라서 동사 표면형만으로는 edge_type을 못 고르는 절들이다. "
        "'목적어를 하다' 패턴(예: '감사를 하다', '결산검사를 하다', "
        "'지원을 하다', '결정을 하다')은 목적어 명사가 곧 실질 행위를 "
        "나타내므로 대부분 실질 관계다 — 이때는 그 목적어가 뜻하는 행위에 "
        "가장 가까운 edge_type을 64개 중에서 고른다(예: '감사를 하다'는 "
        "SUPERVISES나 REVIEWS, '지원을 하다'는 SUPPORTS, '결정을 하다'는 "
        "DELIBERATES). 목적어 명사에 대응하는 edge_type이 애매하면 "
        "가장 근접한 것을 고르되, 목적어 자체가 구체적 행위/사물을 "
        "가리키지 않는 경우(형식적 지시대명사, 순수 존재/상태 서술, "
        "단순 예시/열거 표지 등)에만 'NONE'을 선택한다. 아래"
    )
    return _classify_batch(items, candidates, task)
