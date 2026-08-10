from __future__ import annotations

import datetime as dt
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field, model_validator

from graphdb.schema import EdgeLabel, NodeLabel


class Node(BaseModel):
    """Base for every domain node type. Subclasses set `label` and add
    their own typed properties on top of `id`/`name`."""

    label: ClassVar[NodeLabel]
    source: Literal["domain", "document"] = "domain"
    document_id: str | None = None  # set when source == "document"

    id: str
    name: str | None = None

    def properties(self) -> dict[str, Any]:
        data = self.model_dump(exclude_none=True, exclude={"id"})
        return data


class Company(Node):
    label: ClassVar[NodeLabel] = NodeLabel.COMPANY
    name: str
    biz_reg_no: str | None = None  # 사업자등록번호


class Department(Node):
    label: ClassVar[NodeLabel] = NodeLabel.DEPARTMENT
    name: str
    company_id: str | None = None


class Person(Node):
    label: ClassVar[NodeLabel] = NodeLabel.PERSON
    name: str
    title: str | None = None  # 직책
    employee_no: str | None = None


class Regulation(Node):
    label: ClassVar[NodeLabel] = NodeLabel.REGULATION
    name: str
    version: str | None = None
    effective_date: dt.date | None = None
    category: str | None = None  # 준법감시/신용리스크/시장리스크 등


class Law(Node):
    label: ClassVar[NodeLabel] = NodeLabel.LAW
    name: str
    article: str | None = None  # 조문 (e.g. "제24조")


class ControlItem(Node):
    label: ClassVar[NodeLabel] = NodeLabel.CONTROL_ITEM
    name: str
    control_type: str | None = None  # 예방/적발
    frequency: str | None = None  # 상시/일간/월간/분기


class Risk(Node):
    label: ClassVar[NodeLabel] = NodeLabel.RISK
    name: str
    severity: str | None = None  # 상/중/하
    category: str | None = None  # 운영/신용/시장/컴플라이언스


class Process(Node):
    label: ClassVar[NodeLabel] = NodeLabel.PROCESS
    name: str
    description: str | None = None


class Document(Node):
    label: ClassVar[NodeLabel] = NodeLabel.DOCUMENT
    title: str
    doc_type: str | None = None  # 규정집/매뉴얼/공시 등
    published_date: dt.date | None = None

    @model_validator(mode="after")
    def _default_name_to_title(self) -> "Document":
        if self.name is None:
            self.name = self.title
        return self


class Edge(BaseModel):
    """A relationship between two nodes, addressed by (label, id)."""

    label: EdgeLabel
    start_label: NodeLabel
    start_id: str
    end_label: NodeLabel
    end_id: str
    source: Literal["domain", "document"] = "domain"
    document_id: str | None = None
    properties: dict[str, Any] = Field(default_factory=dict)
