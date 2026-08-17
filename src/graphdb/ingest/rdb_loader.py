"""RDB (PostgreSQL) loader — the SSOT that issues document/entity/relation
UUIDs (CLAUDE.md "5단계 > ID 스킴"). AGE and OpenSearch reuse the ids handed
back here; they never mint their own.

A plain synchronous psycopg connection is enough for a one-shot batch load
(no pooling needed — this isn't a long-lived service). See CLAUDE.md
"인프라 준비물": the async `GraphConnection` in connection.py is AGE-only
and not reused here on purpose.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

import psycopg

from graphdb.config import get_rdb_settings
from graphdb.pipeline import PipelineResult
from graphdb.typing.dictionaries import resolve_alias

logger = logging.getLogger(__name__)

_SUBTYPE_COLUMN = {
    "Organization": "category",
    "Person": "role_hint",
    "LegalDocument": "doc_type",
    "Concept": "concept_type",
}


def _entity_description(name: str, label: str, subtype: str | None) -> str:
    return f"{name} ({label}: {subtype})" if subtype else f"{name} ({label})"


@dataclass
class LoadedEntity:
    id: str
    label: str
    name: str
    subtype: str | None
    description: str


@dataclass
class LoadedRelation:
    id: str
    edge_type: str
    source_entity_id: str
    target_entity_id: str
    source_law: str
    article_no: int
    paragraph_no: int | None
    modality: str
    voice: str
    description_parts: tuple[str, str]  # (agent name, patient name) for description templating


@dataclass
class RDBLoadResult:
    document_ids: dict[str, str]
    entities: list[LoadedEntity]
    relations: list[LoadedRelation]


def read_rdb_load_result() -> RDBLoadResult:
    """Reconstruct an RDBLoadResult from what's already in RDB, so AGE/
    OpenSearch can be (re)loaded without re-running the SVO/LLM pipeline —
    e.g. after `truncate_age()` cleans up a stale/partial AGE graph left
    over from an earlier run whose RDB rows were since replaced."""
    settings = get_rdb_settings()
    with psycopg.connect(settings.dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT file_path, id FROM document")
            document_ids = {row[0]: str(row[1]) for row in cur.fetchall()}

            cur.execute(
                "SELECT id, label, name, category, role_hint, doc_type, concept_type, description FROM entity"
            )
            entities = [
                LoadedEntity(
                    id=str(row[0]),
                    label=row[1],
                    name=row[2],
                    subtype=row[3] or row[4] or row[5] or row[6],
                    description=row[7],
                )
                for row in cur.fetchall()
            ]

            cur.execute(
                """
                SELECT r.id, r.edge_type, r.source_entity_id, r.target_entity_id, r.source_law,
                       r.article_no, r.paragraph_no, r.modality, r.voice, e1.name, e2.name
                FROM relation r
                JOIN entity e1 ON r.source_entity_id = e1.id
                JOIN entity e2 ON r.target_entity_id = e2.id
                """
            )
            relations = [
                LoadedRelation(
                    id=str(row[0]),
                    edge_type=row[1],
                    source_entity_id=str(row[2]),
                    target_entity_id=str(row[3]),
                    source_law=row[4],
                    article_no=row[5][0] if row[5] else None,
                    paragraph_no=row[6],
                    modality=row[7],
                    voice=row[8],
                    description_parts=(row[9], row[10]),
                )
                for row in cur.fetchall()
            ]

    return RDBLoadResult(document_ids=document_ids, entities=entities, relations=relations)


def truncate_rdb() -> None:
    settings = get_rdb_settings()
    with psycopg.connect(settings.dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE relation, entity, document RESTART IDENTITY CASCADE")
        conn.commit()


def load_to_rdb(result: PipelineResult) -> RDBLoadResult:
    settings = get_rdb_settings()
    document_ids: dict[str, str] = {}
    entity_ids: dict[str, str] = {}  # "{label}:{name}" -> id
    loaded_entities: list[LoadedEntity] = []
    loaded_relations: list[LoadedRelation] = []

    with psycopg.connect(settings.dsn) as conn:
        with conn.cursor() as cur:
            for doc in result.documents:
                cur.execute(
                    """
                    INSERT INTO document
                        (source_law, doc_type, law_mst, promulgation_date,
                         enforcement_date, competent_ministry, file_path, raw_text)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (file_path) DO UPDATE SET raw_text = EXCLUDED.raw_text
                    RETURNING id
                    """,
                    (
                        doc.source_law,
                        doc.doc_type,
                        doc.law_mst,
                        doc.promulgation_date,
                        doc.enforcement_date,
                        doc.competent_ministry,
                        doc.file_path,
                        doc.raw_text,
                    ),
                )
                row = cur.fetchone()
                assert row is not None
                document_ids[doc.file_path] = str(row[0])

            def get_entity_id(name: str) -> str:
                et = result.entity_types[name]
                label = et.label.value
                key = f"{label}:{name}"
                cached = entity_ids.get(key)
                if cached is not None:
                    return cached

                cur.execute(
                    "SELECT id FROM entity WHERE label = %s AND name = %s LIMIT 1",
                    (label, name),
                )
                found = cur.fetchone()
                if found is not None:
                    entity_ids[key] = str(found[0])
                    return entity_ids[key]

                subtype_col = _SUBTYPE_COLUMN[label]
                description = _entity_description(name, label, et.subtype)
                columns = ["label", "name", subtype_col, "description"]
                values = [label, name, et.subtype, description]
                cur.execute(
                    f"INSERT INTO entity ({', '.join(columns)}) VALUES ({', '.join(['%s'] * len(values))}) "
                    "RETURNING id",
                    values,
                )
                new_row = cur.fetchone()
                assert new_row is not None
                new_id = str(new_row[0])
                entity_ids[key] = new_id
                loaded_entities.append(LoadedEntity(new_id, label, name, et.subtype, description))
                return new_id

            for rel in result.relations:
                raw = rel.raw
                agent_name = resolve_alias(raw.agent)
                patient_name = resolve_alias(raw.patient)
                source_id = get_entity_id(agent_name)
                target_id = get_entity_id(patient_name)
                document_id = document_ids[raw.document.file_path]
                relation_id = str(uuid.uuid4())

                cur.execute(
                    """
                    INSERT INTO relation
                        (id, edge_type, source_entity_id, target_entity_id, document_id,
                         source_law, article_no, paragraph_no, condition, modality, voice,
                         evidence_text, extraction_method)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        relation_id,
                        rel.edge_type,
                        source_id,
                        target_id,
                        document_id,
                        raw.document.source_law,
                        [raw.article_no],
                        raw.paragraph_no,
                        None,
                        raw.modality,
                        raw.voice,
                        raw.evidence_text[:2000],
                        rel.extraction_method,
                    ),
                )
                loaded_relations.append(
                    LoadedRelation(
                        id=relation_id,
                        edge_type=rel.edge_type,
                        source_entity_id=source_id,
                        target_entity_id=target_id,
                        source_law=raw.document.source_law,
                        article_no=raw.article_no,
                        paragraph_no=raw.paragraph_no,
                        modality=raw.modality,
                        voice=raw.voice,
                        description_parts=(agent_name, patient_name),
                    )
                )
        conn.commit()

    logger.info(
        "RDB load done: %d documents, %d entities, %d relations",
        len(document_ids),
        len(loaded_entities),
        len(loaded_relations),
    )
    return RDBLoadResult(document_ids=document_ids, entities=loaded_entities, relations=loaded_relations)
