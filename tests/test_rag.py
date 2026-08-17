from graphdb.query.rag import _build_context_and_graph, _edge_to_edge, _vertex_to_node


def test_vertex_to_node_extracts_props():
    vertex = {
        "id": 123,
        "label": "Organization",
        "properties": {"id": "uuid-1", "name": "금융위원회", "description": "금융위원회 (Organization)"},
    }
    node = _vertex_to_node(vertex)
    assert node == {
        "id": "uuid-1",
        "name": "금융위원회",
        "label": "Organization",
        "description": "금융위원회 (Organization)",
    }


def test_edge_to_edge_extracts_props():
    edge = {
        "id": 456,
        "label": "APPOINTS",
        "properties": {"id": "rel-1", "source_law": "감사원법", "article_no": 4, "paragraph_no": 1,
                        "modality": "없음", "voice": "능동"},
    }
    e = _edge_to_edge(edge, "src-id", "tgt-id")
    assert e["id"] == "rel-1"
    assert e["source"] == "src-id"
    assert e["target"] == "tgt-id"
    assert e["edge_type"] == "APPOINTS"
    assert e["article_no"] == 4


def test_build_context_and_graph_dedupes_and_formats():
    n = {"id": "n1", "label": "Organization", "properties": {"id": "n1", "name": "대통령"}}
    m = {"id": "n2", "label": "Person", "properties": {"id": "n2", "name": "원장", "role_hint": "원장"}}
    edge = {
        "id": "e1",
        "label": "APPOINTS",
        "properties": {"id": "e1", "source_law": "감사원법", "article_no": 4, "paragraph_no": 1,
                        "modality": "없음", "voice": "능동"},
    }
    rows = [(n, edge, m), (n, edge, m)]  # duplicate row, should collapse to one line/edge

    context, nodes, edges = _build_context_and_graph(rows)

    assert "감사원법 제4조 제1항" in context
    assert "대통령 -[APPOINTS]-> 원장" in context
    assert context.count("APPOINTS") == 1  # deduped, not repeated per row
    assert set(nodes) == {"n1", "n2"}
    assert set(edges) == {"e1"}


def test_build_context_and_graph_handles_multi_edge_list():
    n = {"id": "n1", "label": "Organization", "properties": {"id": "n1", "name": "금융위원회"}}
    m = {"id": "n2", "label": "Organization", "properties": {"id": "n2", "name": "은행"}}
    edge1 = {
        "id": "e1", "label": "SUPERVISES",
        "properties": {"id": "e1", "source_law": "은행법", "article_no": 1, "paragraph_no": None,
                        "modality": "없음", "voice": "능동"},
    }
    edge2 = {
        "id": "e2", "label": "SANCTIONS",
        "properties": {"id": "e2", "source_law": "은행법", "article_no": 2, "paragraph_no": None,
                        "modality": "재량", "voice": "능동"},
    }
    rows = [(n, [edge1, edge2], m)]

    context, nodes, edges = _build_context_and_graph(rows)

    assert set(edges) == {"e1", "e2"}
    assert "SUPERVISES" in context and "SANCTIONS" in context


def test_build_context_and_graph_empty_rows():
    context, nodes, edges = _build_context_and_graph([])
    assert context == ""
    assert nodes == {}
    assert edges == {}
