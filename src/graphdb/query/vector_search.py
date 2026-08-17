"""kNN similarity search against the OpenSearch entity/relation indices
(CLAUDE.md "5단계 > OpenSearch 스키마" `description_embedding`). Used by
`graphdb.query.rag` to turn a natural-language question into a set of seed
entities for graph traversal.
"""

from __future__ import annotations

from opensearchpy import OpenSearch

from graphdb.ingest.opensearch_loader import ENTITY_INDEX, RELATION_INDEX


def knn_search_entities(client: OpenSearch, query_vector: list[float], k: int = 5) -> list[dict]:
    body = {
        "size": k,
        "query": {"knn": {"description_embedding": {"vector": query_vector, "k": k}}},
    }
    resp = client.search(index=ENTITY_INDEX, body=body)
    return [
        {
            "id": hit["_source"]["id"],
            "name": hit["_source"]["name"],
            "label": hit["_source"]["label"],
            "description": hit["_source"]["description"],
            "score": hit["_score"],
        }
        for hit in resp["hits"]["hits"]
    ]


def knn_search_relations(client: OpenSearch, query_vector: list[float], k: int = 5) -> list[dict]:
    body = {
        "size": k,
        "query": {"knn": {"description_embedding": {"vector": query_vector, "k": k}}},
    }
    resp = client.search(index=RELATION_INDEX, body=body)
    return [
        {
            "id": hit["_source"]["id"],
            "edge_type": hit["_source"]["edge_type"],
            "source_entity_id": hit["_source"]["source_entity_id"],
            "target_entity_id": hit["_source"]["target_entity_id"],
            "description": hit["_source"]["description"],
            "score": hit["_score"],
        }
        for hit in resp["hits"]["hits"]
    ]
