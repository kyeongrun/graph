"""Keyword -> EdgeLabel hints for narrowing RAG query-time graph traversal
to question-relevant relation types, with an LLM fallback for questions the
keyword table misses.

Scope note: this is query-time retrieval routing, not extraction. It never
touches what edge_type an already-extracted relation was assigned (svo.py's
output stays untouched, per CLAUDE.md's rule/LLM boundary for the 5단계
pipeline) — it only decides which already-stored edge types a traversal
follows when searching for an answer.

Two-tier, dict-first-LLM-fallback — the same shape as the 5단계 pipeline's
own rule/LLM split (entity typing, edge_type disambiguation):
1. `infer_edge_types`: deliberately dumb substring matching over the
   question text, not NLP. Free, instant, good enough as a first pass.
2. `infer_edge_types_llm`: only called when (1) finds nothing. Picks zero
   or more types from the closed 64-value `EdgeLabel` enum via structured
   output (same "closed candidates only, never invents a new category"
   constraint used elsewhere in this codebase) — never free-form.

Callers must still be prepared for a false negative from either tier (a
real match phrased without any listed keyword, or the LLM guessing wrong)
— see `graphdb.query.rag`'s fallback-to-unfiltered-if-empty behavior, which
applies uniformly regardless of which tier produced the filter.
"""

from __future__ import annotations

import logging

from graphdb.llm import chat_json
from graphdb.schema import EdgeLabel

logger = logging.getLogger(__name__)

KEYWORD_EDGE_TYPES: dict[str, tuple[EdgeLabel, ...]] = {
    # 인사/직위
    "임명": (EdgeLabel.APPOINTS, EdgeLabel.DISMISSES, EdgeLabel.WORKS_AT, EdgeLabel.DELEGATES_TO),
    "선임": (EdgeLabel.APPOINTS, EdgeLabel.DISMISSES),
    "해임": (EdgeLabel.DISMISSES, EdgeLabel.APPOINTS, EdgeLabel.RESIGNS),
    "사임": (EdgeLabel.RESIGNS, EdgeLabel.DISMISSES),
    "위임": (EdgeLabel.DELEGATES_TO, EdgeLabel.APPOINTS),
    "위탁": (EdgeLabel.DELEGATES_TO, EdgeLabel.ENTRUSTS_ASSET),
    "재직": (EdgeLabel.WORKS_AT,),
    "근무": (EdgeLabel.WORKS_AT,),
    # 설립/폐지
    "설립": (EdgeLabel.ESTABLISHES, EdgeLabel.DISSOLVES),
    "해산": (EdgeLabel.DISSOLVES, EdgeLabel.ESTABLISHES),
    "합병": (EdgeLabel.MERGES_WITH,),
    "분할": (EdgeLabel.DIVIDES_INTO,),
    "전환": (EdgeLabel.CONVERTS_TO,),
    # 소통/보고
    "보고": (EdgeLabel.NOTIFIES, EdgeLabel.SUBMITS, EdgeLabel.RECORDS),
    "통지": (EdgeLabel.NOTIFIES,),
    "제출": (EdgeLabel.SUBMITS, EdgeLabel.NOTIFIES, EdgeLabel.RECORDS),
    "공시": (EdgeLabel.DISCLOSES,),
    "공고": (EdgeLabel.DISCLOSES,),
    "신고": (EdgeLabel.REGISTERS, EdgeLabel.NOTIFIES),
    "등록": (EdgeLabel.REGISTERS,),
    "요청": (EdgeLabel.REQUESTS,),
    "요구": (EdgeLabel.REQUESTS,),
    "기재": (EdgeLabel.RECORDS,),
    # 승인/결정
    "승인": (EdgeLabel.APPROVES, EdgeLabel.REJECTS),
    "인가": (EdgeLabel.APPROVES, EdgeLabel.REJECTS),
    "거부": (EdgeLabel.REJECTS, EdgeLabel.APPROVES),
    "거절": (EdgeLabel.REJECTS,),
    "의결": (EdgeLabel.DELIBERATES, EdgeLabel.APPROVES),
    "심의": (EdgeLabel.DELIBERATES,),
    "결정": (EdgeLabel.DELIBERATES,),
    # 위반/제재
    "위반": (EdgeLabel.VIOLATES, EdgeLabel.COMPLIES, EdgeLabel.SANCTIONS),
    "준수": (EdgeLabel.COMPLIES, EdgeLabel.VIOLATES),
    "제재": (EdgeLabel.SANCTIONS, EdgeLabel.RESTRICTS, EdgeLabel.VIOLATES),
    "처분": (EdgeLabel.SANCTIONS, EdgeLabel.DISPOSES),
    "금지": (EdgeLabel.RESTRICTS, EdgeLabel.EXEMPTS),
    "제한": (EdgeLabel.RESTRICTS, EdgeLabel.EXEMPTS),
    "면제": (EdgeLabel.EXEMPTS, EdgeLabel.RESTRICTS),
    # 재산/거래/자금
    "취득": (EdgeLabel.ACQUIRES, EdgeLabel.DISPOSES),
    "매도": (EdgeLabel.DISPOSES, EdgeLabel.ACQUIRES),
    "양도": (EdgeLabel.DISPOSES,),
    "보유": (EdgeLabel.HOLDS, EdgeLabel.INVESTS),
    "소유": (EdgeLabel.HOLDS,),
    "투자": (EdgeLabel.INVESTS, EdgeLabel.ACQUIRES),
    "출자": (EdgeLabel.INVESTS,),
    "발행": (EdgeLabel.ISSUES,),
    "상장": (EdgeLabel.ISSUES,),
    "거래": (EdgeLabel.TRANSACTS_WITH,),
    "매매": (EdgeLabel.TRANSACTS_WITH,),
    "지급": (EdgeLabel.PAYS,),
    "납부": (EdgeLabel.PAYS,),
    "차입": (EdgeLabel.BORROWS, EdgeLabel.LENDS),
    "대출": (EdgeLabel.LENDS, EdgeLabel.BORROWS),
    "여신": (EdgeLabel.LENDS,),
    "보증": (EdgeLabel.GUARANTEES,),
    "신탁": (EdgeLabel.ENTRUSTS_ASSET,),
    "예탁": (EdgeLabel.ENTRUSTS_ASSET,),
    "산정": (EdgeLabel.CALCULATES,),
    "계산": (EdgeLabel.CALCULATES,),
    # 관리/운영/수행
    "관리": (EdgeLabel.MANAGES, EdgeLabel.SUPERVISES),
    "운영": (EdgeLabel.MANAGES, EdgeLabel.USES),
    "경영": (EdgeLabel.MANAGES,),
    "이용": (EdgeLabel.USES,),
    "수행": (EdgeLabel.PERFORMS,),
    "이행": (EdgeLabel.PERFORMS,),
    "보호": (EdgeLabel.PROTECTS,),
    "방지": (EdgeLabel.PROTECTS,),
    "지원": (EdgeLabel.SUPPORTS,),
    # 판단/심사/감독
    "검토": (EdgeLabel.REVIEWS,),
    "심사": (EdgeLabel.REVIEWS, EdgeLabel.DELIBERATES),
    "조사": (EdgeLabel.REVIEWS,),
    "검사": (EdgeLabel.REVIEWS, EdgeLabel.SUPERVISES),
    "감독": (EdgeLabel.SUPERVISES,),
    "감사": (EdgeLabel.SUPERVISES, EdgeLabel.REVIEWS),
    "평가": (EdgeLabel.EVALUATES,),
    "인정": (EdgeLabel.EVALUATES,),
    # 법제/규정
    "규정": (EdgeLabel.PRESCRIBES,),
    "정한다": (EdgeLabel.PRESCRIBES,),
    "제정": (EdgeLabel.ENACTS,),
    "개정": (EdgeLabel.AMENDS,),
    "시행": (EdgeLabel.ENFORCES,),
    "적용": (EdgeLabel.APPLIES_LAW, EdgeLabel.EXCLUDES),
    "제외": (EdgeLabel.EXCLUDES, EdgeLabel.APPLIES_LAW),
    "삭제": (EdgeLabel.DELETES_PROVISION,),
    # 상태 전이
    "발생": (EdgeLabel.OCCURS,),
    "만료": (EdgeLabel.EXPIRES,),
    "종료": (EdgeLabel.TERMINATES,),
    "해지": (EdgeLabel.TERMINATES,),
    "개시": (EdgeLabel.COMMENCES,),
    "계속": (EdgeLabel.CONTINUES,),
    # 기준 비교
    "충족": (EdgeLabel.SATISFIES, EdgeLabel.FALLS_SHORT_OF),
    "초과": (EdgeLabel.EXCEEDS,),
    "미달": (EdgeLabel.FALLS_SHORT_OF,),
    # 기타
    "소집": (EdgeLabel.CONVENES,),
    "개최": (EdgeLabel.CONVENES,),
    "부여": (EdgeLabel.GRANTS,),
    "상실": (EdgeLabel.LOSES,),
}


def infer_edge_types(question: str) -> list[EdgeLabel] | None:
    """Union of EdgeLabel values hinted at by keyword matches in `question`.
    Returns None if nothing matched, so callers can fall back to
    `infer_edge_types_llm` (or, if that also finds nothing, an unrestricted
    traversal)."""
    matched: set[EdgeLabel] = set()
    for keyword, types in KEYWORD_EDGE_TYPES.items():
        if keyword in question:
            matched.update(types)
    return sorted(matched, key=lambda t: t.value) if matched else None


# Category grouping mirrors schema.py's own numbered comment groups
# (EdgeLabel's "1. 인사/직위" ... "12. 기타 저빈도 개념" sections) — reused
# here, not redefined independently, so the two stay in sync by construction
# rather than by hand-maintained duplication.
_EDGE_TYPE_CATEGORIES: dict[str, tuple[EdgeLabel, ...]] = {
    "인사/직위": (EdgeLabel.APPOINTS, EdgeLabel.DISMISSES, EdgeLabel.RESIGNS, EdgeLabel.WORKS_AT, EdgeLabel.DELEGATES_TO),
    "설립/폐지/조직변경": (EdgeLabel.ESTABLISHES, EdgeLabel.DISSOLVES, EdgeLabel.MERGES_WITH, EdgeLabel.DIVIDES_INTO, EdgeLabel.CONVERTS_TO),
    "소통/보고/공시": (EdgeLabel.NOTIFIES, EdgeLabel.SUBMITS, EdgeLabel.DISCLOSES, EdgeLabel.REGISTERS, EdgeLabel.REQUESTS, EdgeLabel.RECORDS),
    "승인/결정": (EdgeLabel.APPROVES, EdgeLabel.REJECTS, EdgeLabel.DELIBERATES),
    "위반/제재": (EdgeLabel.VIOLATES, EdgeLabel.COMPLIES, EdgeLabel.SANCTIONS, EdgeLabel.RESTRICTS, EdgeLabel.EXEMPTS),
    "재산/거래/자금": (
        EdgeLabel.ACQUIRES, EdgeLabel.DISPOSES, EdgeLabel.HOLDS, EdgeLabel.INVESTS, EdgeLabel.ISSUES,
        EdgeLabel.TRANSACTS_WITH, EdgeLabel.PAYS, EdgeLabel.BORROWS, EdgeLabel.LENDS, EdgeLabel.GUARANTEES,
        EdgeLabel.ENTRUSTS_ASSET, EdgeLabel.CALCULATES,
    ),
    "관리/운영/수행": (EdgeLabel.MANAGES, EdgeLabel.USES, EdgeLabel.PERFORMS, EdgeLabel.PROTECTS, EdgeLabel.SUPPORTS),
    "판단/심사/감독": (EdgeLabel.REVIEWS, EdgeLabel.SUPERVISES, EdgeLabel.EVALUATES),
    "법제/규정": (
        EdgeLabel.PRESCRIBES, EdgeLabel.ENACTS, EdgeLabel.AMENDS, EdgeLabel.ENFORCES,
        EdgeLabel.APPLIES_LAW, EdgeLabel.EXCLUDES, EdgeLabel.DELETES_PROVISION,
    ),
    "상태전이": (EdgeLabel.OCCURS, EdgeLabel.EXPIRES, EdgeLabel.TERMINATES, EdgeLabel.COMMENCES, EdgeLabel.CONTINUES),
    "기준비교": (EdgeLabel.SATISFIES, EdgeLabel.EXCEEDS, EdgeLabel.FALLS_SHORT_OF),
    "기타": (EdgeLabel.AFFECTS, EdgeLabel.DENIES, EdgeLabel.CONVENES, EdgeLabel.GRANTS, EdgeLabel.LOSES),
}

# A 64-item enum embedded directly in the JSON schema was unreliable in
# practice — live-verified 2026-08-16: the model's structured output broke
# mid-string (`JSONDecodeError: Unterminated string`) on a real question,
# silently falling back to unrestricted every time this path was hit. A
# 12-item category enum is a much smaller/simpler decoding target; picking
# a category and expanding it to its member EdgeLabels client-side is
# coarser than picking individual types, but still closed-candidate (never
# invents a new edge_type or category) and reliable, which a broken
# response isn't.
_LLM_SCHEMA = {
    "type": "object",
    "properties": {
        "categories": {
            "type": "array",
            "items": {"type": "string", "enum": list(_EDGE_TYPE_CATEGORIES)},
            "maxItems": len(_EDGE_TYPE_CATEGORIES),
        }
    },
    "required": ["categories"],
    "additionalProperties": False,
}

_SYSTEM = (
    "당신은 대한민국 금융권 법령 지식그래프에서 질문에 답하기 위해 어떤 종류의 "
    "관계를 따라가야 할지 고르는 라우터다. 관계는 아래 12개 카테고리로 미리 "
    "분류되어 있다 (예: '인사/직위'=임명/해임/재직/위임, '위반/제재'=위반/제재/금지/면제, "
    "'재산/거래/자금'=취득/처분/보유/투자/지급/차입 등). 이 질문에 답하는 데 관련 있을 "
    "만한 카테고리를 0개 이상 골라라. 확신이 없거나 질문이 특정 카테고리와 무관해 "
    "보이면 빈 배열을 반환하라. 목록에 없는 새로운 카테고리를 만들어내지 마라."
)


def infer_edge_types_llm(question: str) -> list[EdgeLabel] | None:
    """LLM fallback for when `infer_edge_types` finds no keyword match.
    Picks zero or more of the 12 category groups above via structured
    output (never free-form, never an individual edge_type not in a chosen
    category), then expands to those categories' member EdgeLabels.
    Returns None (not an empty list) both when the LLM picks nothing and
    when the call fails, so callers can treat both the same way (fall
    through to an unrestricted traversal)."""
    try:
        parsed = chat_json(_SYSTEM, question, _LLM_SCHEMA, schema_name="edge_type_routing")
        categories = parsed.get("categories", [])
        types: set[EdgeLabel] = set()
        for c in categories:
            types.update(_EDGE_TYPE_CATEGORIES.get(c, ()))
        return sorted(types, key=lambda t: t.value) if types else None
    except Exception:
        logger.exception("LLM edge_type routing failed for question, falling back to unrestricted")
        return None


_REFINE_SYSTEM = (
    "당신은 대한민국 금융권 법령 지식그래프에서 질문에 답하기 위해 어떤 관계를 "
    "따라가야 할지 좁히는 라우터다. 이미 대분류로 후보 edge_type이 추려져 있다. "
    "이 후보들 중에서 이 질문에 실제로 관련 있을 만한 것만 골라라 — 후보 전체가 "
    "다 관련 있으면 전체를 반환해도 되고, 일부만 관련 있으면 그것만 반환하라. "
    "확신이 없으면 후보 전체를 그대로 반환하라. 후보 목록에 없는 edge_type을 "
    "만들어내지 마라."
)


def refine_edge_types_llm(question: str, candidates: list[EdgeLabel]) -> list[EdgeLabel]:
    """Second-stage narrowing within an already-narrowed candidate set
    (from `infer_edge_types` or `infer_edge_types_llm`) — deeper hop counts
    (3/4-hop traversals) multiply how much a too-broad category costs, so
    this exists to cut a category's full member list down to just what the
    question actually needs.

    Candidate set is always small (bounded by the largest category, 12),
    unlike the 64-item call in `infer_edge_types_llm` that hit a repetition
    failure (model looped on one enum value until it hit `max_tokens`,
    live-verified 2026-08-17) — this schema also sets `maxItems` as a hard
    backstop against the same failure mode, on top of already having a
    much smaller candidate pool. (`uniqueItems` was tried too but this
    vLLM server's guided-JSON grammar engine rejects it outright —
    `400 Grammar error: Unimplemented keys: ["uniqueItems"]`, live-verified
    2026-08-17 — so duplicates in the response are still possible; handled
    by deduping via `set()` below instead of the schema.)

    Unlike the two functions above, this does NOT return None on failure —
    `candidates` is already a decent narrowing from an earlier stage, so a
    failed refinement should keep that rather than throw it away. Returns
    `candidates` unchanged if the LLM call fails, returns nothing usable,
    or (defensively) proposes anything outside the candidate set.
    """
    if not candidates:
        return candidates

    schema = {
        "type": "object",
        "properties": {
            "edge_types": {
                "type": "array",
                "items": {"type": "string", "enum": [t.value for t in candidates]},
                "maxItems": len(candidates),
            }
        },
        "required": ["edge_types"],
        "additionalProperties": False,
    }
    try:
        parsed = chat_json(_REFINE_SYSTEM, question, schema, schema_name="edge_type_refine")
        values = parsed.get("edge_types", [])
        candidate_values = {t.value for t in candidates}
        # dedupe ourselves since `uniqueItems` isn't enforced (see above)
        seen: set[str] = set()
        types: list[EdgeLabel] = []
        for v in values:
            if v in candidate_values and v not in seen:
                seen.add(v)
                types.append(EdgeLabel(v))
        return types or candidates
    except Exception:
        logger.exception("LLM edge_type refinement failed, keeping unrefined candidate set")
        return candidates
