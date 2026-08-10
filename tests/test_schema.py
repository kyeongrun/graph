import pytest
from pydantic import ValidationError

from graphdb.models.entities import ControlItem, Document, Edge, Risk
from graphdb.schema import EdgeLabel, NodeLabel


def test_control_item_properties_excludes_id_and_none():
    item = ControlItem(id="ctrl-1", name="분기별 접근권한 검토", frequency="분기")
    props = item.properties()
    assert "id" not in props
    assert props["name"] == "분기별 접근권한 검토"
    assert props["frequency"] == "분기"
    assert "control_type" not in props  # excluded because None


def test_risk_requires_name():
    with pytest.raises(ValidationError):
        Risk(id="risk-1")  # type: ignore[call-arg]


def test_document_defaults_name_to_title():
    doc = Document(id="doc-1", title="내부통제기준 2025")
    assert doc.name == "내부통제기준 2025"


def test_edge_default_source_is_domain():
    edge = Edge(
        label=EdgeLabel.MITIGATES,
        start_label=NodeLabel.CONTROL_ITEM,
        start_id="ctrl-1",
        end_label=NodeLabel.RISK,
        end_id="risk-1",
    )
    assert edge.source == "domain"
    assert edge.properties == {}
