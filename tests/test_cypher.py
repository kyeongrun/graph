import pytest

from graphdb.cypher import map_literal, parse_agtype


def test_parse_agtype_none():
    assert parse_agtype(None) is None


def test_parse_agtype_scalar_string():
    assert parse_agtype('"hello"') == "hello"


def test_parse_agtype_plain_number_passthrough():
    assert parse_agtype(42) == 42


def test_parse_agtype_list():
    assert parse_agtype("[1, 2, 3]") == [1, 2, 3]


def test_parse_agtype_vertex():
    raw = (
        '{"id": 844424930131969, "label": "Company", '
        '"properties": {"name": "한국금융지주"}}::vertex'
    )
    parsed = parse_agtype(raw)
    assert parsed["_agtype"] == "vertex"
    assert parsed["label"] == "Company"
    assert parsed["properties"]["name"] == "한국금융지주"


def test_parse_agtype_edge():
    raw = (
        '{"id": 1125899906842625, "label": "BELONGS_TO", '
        '"start_id": 1, "end_id": 2, "properties": {}}::edge'
    )
    parsed = parse_agtype(raw)
    assert parsed["_agtype"] == "edge"
    assert parsed["label"] == "BELONGS_TO"


def test_parse_agtype_unparseable_returns_raw():
    assert parse_agtype("not json at all") == "not json at all"


def test_parse_agtype_list_of_tagged_edges():
    # How AGE actually serializes a `-[r*1..N]-` variable-length-path column
    # even for a single hop: individually-tagged elements inside an outer
    # list with no tag of its own (json.loads on the whole string fails
    # because `::edge` isn't valid JSON syntax).
    raw = (
        '[{"id": 1, "label": "APPOINTS", "end_id": 2, "start_id": 3, '
        '"properties": {"id": "rel-1"}}::edge]'
    )
    parsed = parse_agtype(raw)
    assert isinstance(parsed, list)
    assert len(parsed) == 1
    assert parsed[0]["_agtype"] == "edge"
    assert parsed[0]["label"] == "APPOINTS"
    assert parsed[0]["properties"]["id"] == "rel-1"


def test_parse_agtype_list_of_multiple_tagged_edges():
    raw = (
        '[{"id": 1, "label": "A", "properties": {}}::edge, '
        '{"id": 2, "label": "B", "properties": {}}::edge]'
    )
    parsed = parse_agtype(raw)
    assert [e["label"] for e in parsed] == ["A", "B"]
    assert all(e["_agtype"] == "edge" for e in parsed)


def test_parse_agtype_list_of_tagged_vertices():
    raw = '[{"id": 1, "label": "Organization", "properties": {"name": "x"}}::vertex]'
    parsed = parse_agtype(raw)
    assert parsed[0]["_agtype"] == "vertex"


def test_parse_agtype_empty_tagged_list():
    assert parse_agtype("[]") == []


def test_map_literal_builds_placeholder_map_and_params():
    literal, params = map_literal({"id": "x1", "article_no": 4})
    assert literal == "{id: $p_id, article_no: $p_article_no}"
    assert params == {"p_id": "x1", "p_article_no": 4}


def test_map_literal_rejects_unsafe_key():
    with pytest.raises(ValueError):
        map_literal({"bad key; DROP": 1})
