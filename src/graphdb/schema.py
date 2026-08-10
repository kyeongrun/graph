"""Domain graph schema for the internal control system.

Two kinds of nodes/edges share the same graph:

- Explicit domain entities (org structure, regulations, controls, risks, ...)
  loaded from structured sources via ``ingest.domain_loader``. These carry
  ``source="domain"``.
- Entities/relations extracted by an LLM from source documents via
  ``ingest.document_extractor``. These carry ``source="document"`` plus
  provenance (``document_id``, ``chunk_id``) so extracted claims can be
  traced back to the text they came from and re-verified.

Keeping both in one graph lets GraphRAG retrieval traverse from a
structured control item straight into the raw document text that
justifies it, and vice versa.
"""

from __future__ import annotations

from enum import StrEnum


class NodeLabel(StrEnum):
    COMPANY = "Company"  # 회사/계열사
    DEPARTMENT = "Department"  # 부서/조직
    PERSON = "Person"  # 담당자/책임자
    REGULATION = "Regulation"  # 내부 규정/정책
    LAW = "Law"  # 외부 법규 (근거 법령)
    CONTROL_ITEM = "ControlItem"  # 통제항목
    RISK = "Risk"  # 리스크
    PROCESS = "Process"  # 업무 프로세스
    DOCUMENT = "Document"  # 원문 문서 (extraction의 출처)


class EdgeLabel(StrEnum):
    BELONGS_TO = "BELONGS_TO"  # Department -> Company
    MEMBER_OF = "MEMBER_OF"  # Person -> Department
    RESPONSIBLE_FOR = "RESPONSIBLE_FOR"  # Person -> ControlItem
    OWNS = "OWNS"  # Department -> Process
    PART_OF = "PART_OF"  # ControlItem -> Process
    MITIGATES = "MITIGATES"  # ControlItem -> Risk
    IMPLEMENTS = "IMPLEMENTS"  # ControlItem -> Regulation
    BASED_ON = "BASED_ON"  # Regulation -> Law
    AFFECTS = "AFFECTS"  # Risk -> Process | Department
    MENTIONS = "MENTIONS"  # Document -> any node (extraction provenance)
    RELATED_TO = "RELATED_TO"  # generic fallback for LLM-extracted relations


# Node labels an LLM extractor is allowed to attach to a Document via MENTIONS.
# ControlItem/Risk/Regulation/Process are the entity types most internal
# control filings talk about; org/person nodes are expected to come from the
# structured domain loader, not free-text extraction, to avoid noisy
# duplicate people/department nodes.
EXTRACTABLE_NODE_LABELS: tuple[NodeLabel, ...] = (
    NodeLabel.REGULATION,
    NodeLabel.LAW,
    NodeLabel.CONTROL_ITEM,
    NodeLabel.RISK,
    NodeLabel.PROCESS,
)

REQUIRED_NODE_PROPERTIES: dict[NodeLabel, tuple[str, ...]] = {
    NodeLabel.COMPANY: ("id", "name"),
    NodeLabel.DEPARTMENT: ("id", "name"),
    NodeLabel.PERSON: ("id", "name"),
    NodeLabel.REGULATION: ("id", "name"),
    NodeLabel.LAW: ("id", "name"),
    NodeLabel.CONTROL_ITEM: ("id", "name"),
    NodeLabel.RISK: ("id", "name"),
    NodeLabel.PROCESS: ("id", "name"),
    NodeLabel.DOCUMENT: ("id", "title"),
}
