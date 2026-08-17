from collections import Counter

import graphdb.pipeline as pipeline
from graphdb.pipeline import LawDocument, RawRelation, resolve_edge_types


def _doc() -> LawDocument:
    return LawDocument(
        source_law="테스트법",
        doc_type="법률",
        law_mst=None,
        promulgation_date=None,
        enforcement_date=None,
        competent_ministry=None,
        file_path="test.md",
        raw_text="",
    )


def _unmapped_raw() -> RawRelation:
    # "테스트없는동사" isn't in edge_type_mapping.jsonl, verb_roots_ambiguous,
    # or any of the verb_roots_{def,ref,stative}.jsonl files -- simulates a
    # root only a future/unseen document could produce.
    return RawRelation(
        document=_doc(),
        article_no=1,
        paragraph_no=1,
        agent="갑",
        patient="을",
        verb_lemma="테스트없는동사하다",
        verb_root="테스트없는동사",
        modality="없음",
        voice="능동",
        evidence_text="갑이 을을 테스트없는동사한다.",
    )


def test_unmapped_root_goes_through_llm_fallback(monkeypatch):
    monkeypatch.setattr(pipeline, "disambiguate_unmapped_root", lambda items: {0: "PERFORMS"})
    stats: Counter = Counter()
    resolved = resolve_edge_types([_unmapped_raw()], stats)
    assert len(resolved) == 1
    assert resolved[0].edge_type == "PERFORMS"
    assert resolved[0].extraction_method == "llm_disambiguation"
    assert stats["llm_disambiguation_unmapped_root"] == 1


def test_unmapped_root_none_verdict_is_skipped(monkeypatch):
    monkeypatch.setattr(pipeline, "disambiguate_unmapped_root", lambda items: {0: "NONE"})
    stats: Counter = Counter()
    resolved = resolve_edge_types([_unmapped_raw()], stats)
    assert resolved == []
    assert stats["skipped_llm_none"] == 1


def test_unmapped_root_llm_failure_is_skipped_not_crashed(monkeypatch):
    monkeypatch.setattr(pipeline, "disambiguate_unmapped_root", lambda items: {})
    stats: Counter = Counter()
    resolved = resolve_edge_types([_unmapped_raw()], stats)
    assert resolved == []
    assert stats["skipped_llm_disambiguation_failed"] == 1


def test_known_non_action_root_never_reaches_llm_fallback(monkeypatch):
    non_action_roots = pipeline.load_non_action_roots()
    some_root = next(iter(non_action_roots))
    raw = RawRelation(
        document=_doc(),
        article_no=1,
        paragraph_no=1,
        agent="갑",
        patient="을",
        verb_lemma=f"{some_root}하다",
        verb_root=some_root,
        modality="없음",
        voice="능동",
        evidence_text="...",
    )
    calls = []
    monkeypatch.setattr(
        pipeline, "disambiguate_unmapped_root", lambda items: calls.append(items) or {}
    )
    stats: Counter = Counter()
    resolved = resolve_edge_types([raw], stats)
    assert resolved == []
    assert stats["skipped_non_action_root"] == 1
    assert calls == []  # LLM fallback never invoked for an already-classified root


def test_load_non_action_roots_nonempty():
    roots = pipeline.load_non_action_roots()
    assert len(roots) > 100  # 22 DEF + 47 REF + 138 STATIVE per CLAUDE.md
