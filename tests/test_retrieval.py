from graphdb.query.retrieval import _pattern


def test_pattern_both_direction():
    assert _pattern("r*1..1", "both") == "(n {id: $id})-[r*1..1]-(m)"


def test_pattern_out_direction():
    assert _pattern("r*1..1", "out") == "(n {id: $id})-[r*1..1]->(m)"


def test_pattern_in_direction():
    assert _pattern("r*1..1", "in") == "(n {id: $id})<-[r*1..1]-(m)"
