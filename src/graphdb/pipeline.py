"""Orchestrates the deterministic law_structure.py + svo.py pipeline over
`data/laws/raw/**/*.md`, resolves each SVO record's verb_root to an
EdgeLabel (rule lookup, with LLM disambiguation only for the two narrow
cases the mapping can't resolve alone), and types the resulting agent/
patient mentions into NodeLabel entities — producing the flat list of
(entity, relation) records the RDB/AGE/OpenSearch loaders write out.

CLAUDE.md "5단계 > 절대 원칙": svo.py's agent/patient/voice/modality are
used as-is — nothing here re-interprets or reverses them. EdgeLabel/
NodeLabel are never extended; anything that can't be resolved is either
skipped (with a stats counter) or handed to the narrowly-scoped LLM calls
in edge_disambiguation.py / typing/entity_typing.py.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from graphdb.edge_disambiguation import (
    DisambiguationItem,
    disambiguate_ambiguous,
    disambiguate_needs_context,
    disambiguate_unmapped_root,
)
from graphdb.nlp.law_structure import Article, parse_articles
from graphdb.nlp.svo import extract_svo
from graphdb.typing.dictionaries import resolve_alias
from graphdb.typing.entity_typing import EntityType, type_entities

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent.parent
DATA_LAWS = ROOT / "data" / "laws"
EDGE_TYPE_MAPPING_PATH = DATA_LAWS / "edge_type_mapping.jsonl"
AMBIGUOUS_ROOTS_PATH = DATA_LAWS / "verb_roots_ambiguous.jsonl"
NON_ACTION_ROOTS_PATHS = (
    DATA_LAWS / "verb_roots_def.jsonl",
    DATA_LAWS / "verb_roots_ref.jsonl",
    DATA_LAWS / "verb_roots_stative.jsonl",
)
MANIFEST_PATH = DATA_LAWS / "manifest.json"


# ---------------------------------------------------------------------------
# Root -> edge_type mapping (rule, fixed — see CLAUDE.md "5단계" role table)
# ---------------------------------------------------------------------------


@dataclass
class RootMappingEntry:
    edge_type: str
    edge_type_alt: list[str] = field(default_factory=list)
    needs_context: bool = False


def load_edge_type_mapping() -> dict[str, RootMappingEntry]:
    mapping: dict[str, RootMappingEntry] = {}
    for line in EDGE_TYPE_MAPPING_PATH.read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)
        mapping[rec["root"]] = RootMappingEntry(
            edge_type=rec["edge_type"],
            edge_type_alt=rec.get("edge_type_alt", []),
            needs_context=rec.get("needs_context", False),
        )
    return mapping


def load_ambiguous_roots() -> set[str]:
    roots = set()
    for line in AMBIGUOUS_ROOTS_PATH.read_text(encoding="utf-8").splitlines():
        roots.add(json.loads(line)["root"])
    return roots


def load_non_action_roots() -> set[str]:
    """DEF/REF/STATIVE roots — already classified (during the original
    corpus-wide analysis) as not being action relations at all, so a root
    landing here should stay skipped rather than going to the "unmapped"
    LLM fallback (see `resolve_edge_types`'s final `else` branch)."""
    roots: set[str] = set()
    for path in NON_ACTION_ROOTS_PATHS:
        for line in path.read_text(encoding="utf-8").splitlines():
            roots.add(json.loads(line)["root"])
    return roots


# ---------------------------------------------------------------------------
# Document loading (data/laws/raw + manifest.json — no API client yet, see
# CLAUDE.md "5단계 스코프": read the local files directly for now)
# ---------------------------------------------------------------------------


@dataclass
class LawDocument:
    source_law: str
    doc_type: str
    law_mst: str | None
    promulgation_date: str | None
    enforcement_date: str | None
    competent_ministry: str | None
    file_path: str
    raw_text: str


def load_documents() -> list[LawDocument]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    docs: list[LawDocument] = []
    for law in manifest["laws"]:
        matched_dir = law["matched_dir"]
        for f in law["files"]:
            rel_path = f"data/laws/raw/{matched_dir}/{f['file']}"
            abs_path = ROOT / rel_path
            text = abs_path.read_text(encoding="utf-8")
            ministries = f.get("소관부처") or []
            docs.append(
                LawDocument(
                    source_law=matched_dir,
                    doc_type=f.get("법령구분", "") or "",
                    law_mst=str(f["법령MST"]) if f.get("법령MST") is not None else None,
                    promulgation_date=f.get("공포일자"),
                    enforcement_date=f.get("시행일자"),
                    competent_ministry=", ".join(ministries) if ministries else None,
                    file_path=rel_path,
                    raw_text=text,
                )
            )
    return docs


# ---------------------------------------------------------------------------
# SVO extraction with per-article pro-drop subject inheritance across
# paragraphs/items (svo.py explicitly leaves this to the caller — see its
# module docstring "extract_svo 밖에서 ParagraphContext.inherited_subject").
# ---------------------------------------------------------------------------


@dataclass
class RawRelation:
    document: LawDocument
    article_no: int
    paragraph_no: int | None
    agent: str
    patient: str
    verb_lemma: str
    verb_root: str
    modality: str
    voice: str
    evidence_text: str


def _paragraph_units(article: Article) -> list[tuple[int | None, str]]:
    """(paragraph_no, text) for the paragraph head and each of its 호/목
    item bodies, in document order. Items share their parent paragraph's
    paragraph_no — the finalized RDB/AGE schema has no item-level column
    (CLAUDE.md "그래프 구조": provenance lives on article_no/paragraph_no
    only)."""
    units: list[tuple[int | None, str]] = []
    for p in article.paragraphs:
        if p.text:
            units.append((p.number, p.text))
        for item in p.items:
            if item.body:
                units.append((p.number, item.body))
    return units


def extract_raw_relations(doc: LawDocument) -> list[RawRelation]:
    articles = parse_articles(doc.raw_text)
    out: list[RawRelation] = []
    for article in articles:
        inherited_subject: str | None = None
        for paragraph_no, text in _paragraph_units(article):
            records = extract_svo(text, inherited_subject=inherited_subject)
            for rec in records:
                if rec.agent and rec.patient:
                    out.append(
                        RawRelation(
                            document=doc,
                            article_no=article.number,
                            paragraph_no=paragraph_no,
                            agent=rec.agent,
                            patient=rec.patient,
                            verb_lemma=rec.verb_lemma,
                            verb_root=rec.verb_root,
                            modality=rec.modality.value,
                            voice=rec.voice.value,
                            evidence_text=text.strip(),
                        )
                    )

            # Only a directly-observed subject (JKS/TOPIC) is trustworthy to
            # carry forward — see svo.py _backfill_forward_subject's own
            # reasoning for excluding INHERITED/순방향유추/NONE sources.
            for rec in reversed(records):
                if rec.agent_source in ("JKS", "TOPIC"):
                    inherited_subject = rec.agent
                    break
    return out


# ---------------------------------------------------------------------------
# edge_type resolution: rule lookup + narrow LLM disambiguation
# ---------------------------------------------------------------------------


@dataclass
class ResolvedRelation:
    raw: RawRelation
    edge_type: str
    extraction_method: str  # 'rule' | 'llm_disambiguation' | 'llm_fallback'


def resolve_edge_types(
    raw_relations: list[RawRelation], stats: Counter
) -> list[ResolvedRelation]:
    mapping = load_edge_type_mapping()
    ambiguous_roots = load_ambiguous_roots()
    non_action_roots = load_non_action_roots()

    resolved: list[ResolvedRelation] = []
    needs_context_items: dict[str, list[DisambiguationItem]] = {}
    needs_context_alt: dict[str, list[str]] = {}
    needs_context_default: dict[str, str] = {}
    needs_context_raw: dict[str, list[RawRelation]] = {}
    ambiguous_items: list[DisambiguationItem] = []
    ambiguous_raw: list[RawRelation] = []
    unmapped_items: list[DisambiguationItem] = []
    unmapped_raw: list[RawRelation] = []

    for raw in raw_relations:
        entry = mapping.get(raw.verb_root)
        if entry is not None and not entry.needs_context:
            resolved.append(ResolvedRelation(raw, entry.edge_type, "rule"))
            stats["rule"] += 1
        elif entry is not None and entry.needs_context:
            idx = len(needs_context_items.setdefault(raw.verb_root, []))
            needs_context_items[raw.verb_root].append(
                DisambiguationItem(idx, raw.agent, raw.verb_lemma, raw.patient, raw.evidence_text)
            )
            needs_context_alt[raw.verb_root] = entry.edge_type_alt
            needs_context_default[raw.verb_root] = entry.edge_type
            needs_context_raw.setdefault(raw.verb_root, []).append(raw)
        elif raw.verb_root in ambiguous_roots:
            idx = len(ambiguous_items)
            ambiguous_items.append(
                DisambiguationItem(idx, raw.agent, raw.verb_lemma, raw.patient, raw.evidence_text)
            )
            ambiguous_raw.append(raw)
        elif raw.verb_root in non_action_roots:
            # DEF/REF/STATIVE root: not an action relation by design (see
            # edge_type_taxonomy_draft.md "0. 사전 분리") — already
            # classified during the original corpus-wide pass, no need to
            # ask an LLM about something that's already known.
            stats["skipped_non_action_root"] += 1
        else:
            # Genuinely never classified (only possible for documents
            # outside the original 60-file corpus — see
            # disambiguate_unmapped_root's docstring). LLM fallback
            # instead of silently dropping, so a real new action verb
            # doesn't vanish just because nobody classified it yet.
            idx = len(unmapped_items)
            unmapped_items.append(
                DisambiguationItem(idx, raw.agent, raw.verb_lemma, raw.patient, raw.evidence_text)
            )
            unmapped_raw.append(raw)

    if needs_context_items:
        nc_resolved = disambiguate_needs_context(needs_context_items, needs_context_alt, needs_context_default)
        for root, items in needs_context_items.items():
            raws = needs_context_raw[root]
            for item, raw in zip(items, raws):
                edge_type = nc_resolved.get(item.index)
                if edge_type is not None:
                    resolved.append(ResolvedRelation(raw, edge_type, "llm_disambiguation"))
                    stats["llm_disambiguation"] += 1
                else:
                    # LLM call failed outright — fall back to the mapping's
                    # recorded default rather than dropping the relation.
                    resolved.append(ResolvedRelation(raw, needs_context_default[root], "rule"))
                    stats["rule"] += 1
                    stats["llm_disambiguation_fallback"] += 1

    if ambiguous_items:
        amb_resolved = disambiguate_ambiguous(ambiguous_items)
        for item, raw in zip(ambiguous_items, ambiguous_raw):
            edge_type = amb_resolved.get(item.index)
            if edge_type is None:
                stats["skipped_llm_disambiguation_failed"] += 1
            elif edge_type == "NONE":
                stats["skipped_llm_none"] += 1
            else:
                resolved.append(ResolvedRelation(raw, edge_type, "llm_disambiguation"))
                stats["llm_disambiguation"] += 1

    if unmapped_items:
        unmapped_resolved = disambiguate_unmapped_root(unmapped_items)
        for item, raw in zip(unmapped_items, unmapped_raw):
            edge_type = unmapped_resolved.get(item.index)
            if edge_type is None:
                stats["skipped_llm_disambiguation_failed"] += 1
            elif edge_type == "NONE":
                stats["skipped_llm_none"] += 1
            else:
                resolved.append(ResolvedRelation(raw, edge_type, "llm_disambiguation"))
                stats["llm_disambiguation_unmapped_root"] += 1

    return resolved


# ---------------------------------------------------------------------------
# Entity typing over the surviving relations' agent/patient mentions
# ---------------------------------------------------------------------------


@dataclass
class PipelineResult:
    documents: list[LawDocument]
    relations: list[ResolvedRelation]
    entity_types: dict[str, EntityType]  # keyed by resolve_alias(mention)
    stats: Counter


def run_pipeline(documents: list[LawDocument] | None = None) -> PipelineResult:
    documents = documents if documents is not None else load_documents()
    stats: Counter = Counter()

    all_raw: list[RawRelation] = []
    for doc in documents:
        raw = extract_raw_relations(doc)
        all_raw.extend(raw)
    stats["raw_svo_records_with_both_endpoints"] = len(all_raw)

    relations = resolve_edge_types(all_raw, stats)
    stats["relations_total"] = len(relations)

    mentions: set[str] = set()
    for r in relations:
        mentions.add(resolve_alias(r.raw.agent))
        mentions.add(resolve_alias(r.raw.patient))
    entity_types = type_entities(list(mentions))
    stats["entities_total"] = len(entity_types)

    return PipelineResult(documents=documents, relations=relations, entity_types=entity_types, stats=stats)
