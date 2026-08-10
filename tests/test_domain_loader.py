from pathlib import Path

import pytest

from graphdb.ingest.domain_loader import load_yaml_file, parse_edge, parse_node
from graphdb.models.entities import Company, Department
from graphdb.schema import EdgeLabel, NodeLabel

SAMPLE_FILE = Path(__file__).resolve().parent.parent / "data" / "domain" / "sample_internal_control.yaml"


def test_parse_node_dispatches_to_correct_model():
    node = parse_node({"type": "Company", "id": "co-1", "name": "테스트금융지주"})
    assert isinstance(node, Company)
    assert node.id == "co-1"


def test_parse_node_unknown_type_raises():
    with pytest.raises(ValueError, match="Unknown node type"):
        parse_node({"type": "NotARealType", "id": "x"})


def test_parse_edge():
    edge = parse_edge(
        {
            "label": "BELONGS_TO",
            "start": {"type": "Department", "id": "dept-1"},
            "end": {"type": "Company", "id": "co-1"},
        }
    )
    assert edge.label == EdgeLabel.BELONGS_TO
    assert edge.start_label == NodeLabel.DEPARTMENT
    assert edge.end_label == NodeLabel.COMPANY


def test_load_sample_file_parses_all_nodes_and_edges():
    nodes, edges = load_yaml_file(SAMPLE_FILE)
    assert len(nodes) > 0
    assert len(edges) > 0

    node_ids = {n.id for n in nodes}
    for edge in edges:
        assert edge.start_id in node_ids, f"edge references missing node {edge.start_id}"
        assert edge.end_id in node_ids, f"edge references missing node {edge.end_id}"

    departments = [n for n in nodes if isinstance(n, Department)]
    assert any(d.name == "준법감시부" for d in departments)
