"""Graph schema for the law knowledge graph (entity_schema_draft.md v4 +
edge_type_taxonomy_draft.md v3 — both finalized by the deterministic NLP
pipeline in data/laws/).

Entities connect directly to each other; there is no Article/Relation/
Assertion node. Provenance (source_law, article_no, paragraph_no,
condition, modality, voice) lives on the edge as properties, not as a
graph structure to traverse. See CLAUDE.md "그래프 구조" section for the
full rationale (three redesigns before landing here).

NodeLabel is the closed 4-label set from entity_schema_draft.md — an open
vocabulary of noun types was rejected in favor of one label per ontological
kind, with role/subtype variation absorbed into a property (category /
role_hint / doc_type / concept_type) instead of new labels.

EdgeLabel is EDGE_TYPE_ROOTS from scripts/build_edge_type_mapping.py,
mirrored here as the single source of truth for graph-facing code (that
script owns the root->edge_type mapping used to derive it; keep the two in
sync by hand until an orchestration script generates this file). Opposite
polarity pairs (APPOINTS/DISMISSES, PAYS/BORROWS, RESTRICTS/EXEMPTS, ...)
are kept as separate members on purpose — collapsing them would make the
edge label alone insufficient to tell direction/valence apart, which is
what forced the v1->v2->v3 verb_groups and edge_type redesigns.
"""

from __future__ import annotations

from enum import StrEnum


class NodeLabel(StrEnum):
    ORGANIZATION = "Organization"  # + category (금융회사/정부기관/규제기관 등)
    PERSON = "Person"  # + role_hint (감사위원/공익신고자 등)
    LEGAL_DOCUMENT = "LegalDocument"  # + doc_type (법률/대통령령/총리령/고시 등)
    CONCEPT = "Concept"  # + concept_type (금융상품/내부통제 등)


class EdgeLabel(StrEnum):
    # 1. 인사/직위
    APPOINTS = "APPOINTS"
    DISMISSES = "DISMISSES"
    RESIGNS = "RESIGNS"
    WORKS_AT = "WORKS_AT"
    DELEGATES_TO = "DELEGATES_TO"
    # 2. 설립/폐지/조직변경
    ESTABLISHES = "ESTABLISHES"
    DISSOLVES = "DISSOLVES"
    MERGES_WITH = "MERGES_WITH"
    DIVIDES_INTO = "DIVIDES_INTO"
    CONVERTS_TO = "CONVERTS_TO"
    # 3. 소통/보고/공시
    NOTIFIES = "NOTIFIES"
    SUBMITS = "SUBMITS"
    DISCLOSES = "DISCLOSES"
    REGISTERS = "REGISTERS"
    REQUESTS = "REQUESTS"
    RECORDS = "RECORDS"
    # 4. 승인/결정
    APPROVES = "APPROVES"
    REJECTS = "REJECTS"
    DELIBERATES = "DELIBERATES"
    # 5. 위반/제재
    VIOLATES = "VIOLATES"
    COMPLIES = "COMPLIES"
    SANCTIONS = "SANCTIONS"
    RESTRICTS = "RESTRICTS"
    EXEMPTS = "EXEMPTS"
    # 6. 재산/거래/자금
    ACQUIRES = "ACQUIRES"
    DISPOSES = "DISPOSES"
    HOLDS = "HOLDS"
    INVESTS = "INVESTS"
    ISSUES = "ISSUES"
    TRANSACTS_WITH = "TRANSACTS_WITH"
    PAYS = "PAYS"
    BORROWS = "BORROWS"
    LENDS = "LENDS"
    GUARANTEES = "GUARANTEES"
    ENTRUSTS_ASSET = "ENTRUSTS_ASSET"
    CALCULATES = "CALCULATES"
    # 7. 관리/운영/수행
    MANAGES = "MANAGES"
    USES = "USES"
    PERFORMS = "PERFORMS"
    PROTECTS = "PROTECTS"
    SUPPORTS = "SUPPORTS"
    # 8. 판단/심사/감독
    REVIEWS = "REVIEWS"
    SUPERVISES = "SUPERVISES"
    EVALUATES = "EVALUATES"
    # 9. 법제/규정
    PRESCRIBES = "PRESCRIBES"
    ENACTS = "ENACTS"
    AMENDS = "AMENDS"
    ENFORCES = "ENFORCES"
    APPLIES_LAW = "APPLIES_LAW"
    EXCLUDES = "EXCLUDES"
    DELETES_PROVISION = "DELETES_PROVISION"
    # 10. 상태 전이
    OCCURS = "OCCURS"
    EXPIRES = "EXPIRES"
    TERMINATES = "TERMINATES"
    COMMENCES = "COMMENCES"
    CONTINUES = "CONTINUES"
    # 11. 기준 비교 (v3 신설)
    SATISFIES = "SATISFIES"
    EXCEEDS = "EXCEEDS"
    FALLS_SHORT_OF = "FALLS_SHORT_OF"
    # 12. 기타 저빈도 개념 (v3 신설, 기존 대분류로 흡수하면 의미가 뭉개져 분리)
    AFFECTS = "AFFECTS"
    DENIES = "DENIES"
    CONVENES = "CONVENES"
    GRANTS = "GRANTS"
    LOSES = "LOSES"


# Required edge properties per the finalized structure (CLAUDE.md "최종 확정
# 구조"). article_no/paragraph_no can be multi-valued after citation
# propagation (준용/적용), so callers should treat them as lists at the
# storage layer even though a single extraction yields one value each.
EDGE_PROPERTY_KEYS: tuple[str, ...] = (
    "source_law",
    "article_no",
    "paragraph_no",
    "condition",
    "modality",  # "의무" | "금지" | "재량" | "없음"
    "voice",  # "능동" | "피동"
)
