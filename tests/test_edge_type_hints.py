import graphdb.query.edge_type_hints as edge_type_hints
from graphdb.query.edge_type_hints import infer_edge_types, infer_edge_types_llm, refine_edge_types_llm
from graphdb.schema import EdgeLabel


def test_infer_edge_types_matches_keyword():
    types = infer_edge_types("감사원장은 어떻게 임명되나요?")
    assert types is not None
    assert EdgeLabel.APPOINTS in types
    assert EdgeLabel.DISMISSES in types


def test_infer_edge_types_unions_multiple_keywords():
    types = infer_edge_types("위반하면 어떤 제재를 받나요?")
    assert types is not None
    assert EdgeLabel.VIOLATES in types
    assert EdgeLabel.SANCTIONS in types


def test_infer_edge_types_no_match_returns_none():
    assert infer_edge_types("오늘 날씨가 어때요?") is None


def test_edge_type_categories_cover_all_64_edge_types_exactly():
    covered = {t for types in edge_type_hints._EDGE_TYPE_CATEGORIES.values() for t in types}
    assert covered == set(EdgeLabel)
    assert sum(len(v) for v in edge_type_hints._EDGE_TYPE_CATEGORIES.values()) == 64


def test_infer_edge_types_llm_parses_valid_response(monkeypatch):
    monkeypatch.setattr(edge_type_hints, "chat_json", lambda *a, **k: {"categories": ["인사/직위"]})
    result = infer_edge_types_llm("아무 질문")
    assert result == sorted(
        edge_type_hints._EDGE_TYPE_CATEGORIES["인사/직위"], key=lambda t: t.value
    )


def test_infer_edge_types_llm_empty_list_returns_none(monkeypatch):
    monkeypatch.setattr(edge_type_hints, "chat_json", lambda *a, **k: {"categories": []})
    assert infer_edge_types_llm("아무 질문") is None


def test_infer_edge_types_llm_exception_returns_none(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("vLLM unreachable")

    monkeypatch.setattr(edge_type_hints, "chat_json", boom)
    assert infer_edge_types_llm("아무 질문") is None


def test_refine_edge_types_llm_empty_candidates_returns_empty():
    assert refine_edge_types_llm("아무 질문", []) == []


def test_refine_edge_types_llm_narrows_to_subset(monkeypatch):
    candidates = [EdgeLabel.APPOINTS, EdgeLabel.DISMISSES, EdgeLabel.RESIGNS]
    monkeypatch.setattr(edge_type_hints, "chat_json", lambda *a, **k: {"edge_types": ["APPOINTS"]})
    assert refine_edge_types_llm("임명 관련 질문", candidates) == [EdgeLabel.APPOINTS]


def test_refine_edge_types_llm_ignores_values_outside_candidates(monkeypatch):
    candidates = [EdgeLabel.APPOINTS, EdgeLabel.DISMISSES]
    # LLM defensively proposing something outside the candidate enum should
    # never happen under strict structured output, but if it did, it must
    # not leak a type the caller didn't offer as a choice.
    monkeypatch.setattr(
        edge_type_hints, "chat_json", lambda *a, **k: {"edge_types": ["APPOINTS", "SANCTIONS"]}
    )
    assert refine_edge_types_llm("질문", candidates) == [EdgeLabel.APPOINTS]


def test_refine_edge_types_llm_empty_response_keeps_candidates(monkeypatch):
    candidates = [EdgeLabel.APPOINTS, EdgeLabel.DISMISSES]
    monkeypatch.setattr(edge_type_hints, "chat_json", lambda *a, **k: {"edge_types": []})
    assert refine_edge_types_llm("질문", candidates) == candidates


def test_refine_edge_types_llm_exception_keeps_candidates(monkeypatch):
    candidates = [EdgeLabel.APPOINTS, EdgeLabel.DISMISSES]

    def boom(*a, **k):
        raise RuntimeError("vLLM unreachable")

    monkeypatch.setattr(edge_type_hints, "chat_json", boom)
    assert refine_edge_types_llm("질문", candidates) == candidates
