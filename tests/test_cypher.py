from graphdb.cypher import parse_agtype


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
