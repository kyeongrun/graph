"""OpenSearch loader — entity/relation indices (CLAUDE.md "5단계 >
OpenSearch 스키마"). `description_embedding` is populated via
`graphdb.embeddings` (local ONNX model — see that module's docstring for why
it was picked once CLAUDE.md's "임베딩 모델 선정은 미착수" was resolved for
the RAG query API). Reuses the RDB-issued ids as `_id` (CLAUDE.md "5단계 >
ID 스킴").

`relation` docs also carry `source_entity_id`/`target_entity_id` (+ names) —
not in CLAUDE.md's original relation-index spec, which only listed
`id`/`edge_type`/`description`/`description_embedding`. Added so a
kNN-matched relation can seed a graph traversal from its endpoints (the RAG
query pipeline in `graphdb.query.rag` needs an entity id to hand AGE, and a
relation hit alone doesn't give you one otherwise).
"""

from __future__ import annotations

import logging

from opensearchpy import OpenSearch, helpers

from graphdb.config import get_opensearch_settings
from graphdb.embeddings import EMBEDDING_DIM, embed_texts
from graphdb.ingest.rdb_loader import RDBLoadResult

logger = logging.getLogger(__name__)

ENTITY_INDEX = "entity"
RELATION_INDEX = "relation"

_KNN_VECTOR_FIELD = {
    "type": "knn_vector",
    "dimension": EMBEDDING_DIM,
    "method": {"name": "hnsw", "space_type": "cosinesimil", "engine": "lucene"},
}

_ENTITY_MAPPING = {
    "settings": {"index": {"knn": True}},
    "mappings": {
        "properties": {
            "id": {"type": "keyword"},
            "name": {"type": "text"},
            "label": {"type": "keyword"},
            "description": {"type": "text"},
            "description_embedding": _KNN_VECTOR_FIELD,
        }
    },
}

_RELATION_MAPPING = {
    "settings": {"index": {"knn": True}},
    "mappings": {
        "properties": {
            "id": {"type": "keyword"},
            "edge_type": {"type": "keyword"},
            "source_entity_id": {"type": "keyword"},
            "target_entity_id": {"type": "keyword"},
            "source_entity_name": {"type": "text"},
            "target_entity_name": {"type": "text"},
            "description": {"type": "text"},
            "description_embedding": _KNN_VECTOR_FIELD,
        }
    },
}


def get_client() -> OpenSearch:
    settings = get_opensearch_settings()
    return OpenSearch(
        hosts=[{"host": settings.host, "port": settings.port}],
        http_auth=(settings.user, settings.password) if settings.user else None,
        use_ssl=settings.use_ssl,
        verify_certs=settings.verify_certs,
    )


def ensure_indices(client: OpenSearch) -> None:
    if not client.indices.exists(ENTITY_INDEX):
        client.indices.create(ENTITY_INDEX, body=_ENTITY_MAPPING)
    if not client.indices.exists(RELATION_INDEX):
        client.indices.create(RELATION_INDEX, body=_RELATION_MAPPING)


def _relation_description(r) -> str:
    agent_name, patient_name = r.description_parts
    article = f"{r.source_law} 제{r.article_no}조"
    if r.paragraph_no:
        article += f" 제{r.paragraph_no}항"
    return f"{article}: {agent_name} -[{r.edge_type}]-> {patient_name} (modality={r.modality}, voice={r.voice})"


_EMBED_BATCH_SIZE = 256


def _embed_all(texts: list[str]) -> list[list[float]]:
    """Batched so one call doesn't hold ~28k texts' tokenized state in
    memory at once; fastembed batches internally too but this keeps peak
    memory bounded regardless of corpus size."""
    vectors: list[list[float]] = []
    for start in range(0, len(texts), _EMBED_BATCH_SIZE):
        vectors.extend(embed_texts(texts[start : start + _EMBED_BATCH_SIZE]))
    return vectors


def load_to_opensearch(result: RDBLoadResult) -> None:
    client = get_client()
    ensure_indices(client)

    entity_vectors = _embed_all([e.description for e in result.entities])
    entity_actions = [
        {
            "_index": ENTITY_INDEX,
            "_id": e.id,
            "_source": {
                "id": e.id,
                "name": e.name,
                "label": e.label,
                "description": e.description,
                "description_embedding": vec,
            },
        }
        for e, vec in zip(result.entities, entity_vectors)
    ]

    relation_descriptions = [_relation_description(r) for r in result.relations]
    relation_vectors = _embed_all(relation_descriptions)
    relation_actions = [
        {
            "_index": RELATION_INDEX,
            "_id": r.id,
            "_source": {
                "id": r.id,
                "edge_type": r.edge_type,
                "source_entity_id": r.source_entity_id,
                "target_entity_id": r.target_entity_id,
                "source_entity_name": r.description_parts[0],
                "target_entity_name": r.description_parts[1],
                "description": desc,
                "description_embedding": vec,
            },
        }
        for r, desc, vec in zip(result.relations, relation_descriptions, relation_vectors)
    ]

    if entity_actions:
        helpers.bulk(client, entity_actions)
    if relation_actions:
        helpers.bulk(client, relation_actions)
    client.indices.refresh(index=f"{ENTITY_INDEX},{RELATION_INDEX}")

    logger.info(
        "OpenSearch load done: %d entity docs, %d relation docs",
        len(entity_actions),
        len(relation_actions),
    )


def truncate_opensearch() -> None:
    client = get_client()
    for index in (ENTITY_INDEX, RELATION_INDEX):
        if client.indices.exists(index):
            client.indices.delete(index)
