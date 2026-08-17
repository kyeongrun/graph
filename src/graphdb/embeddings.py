"""Local, self-hosted text embeddings for the RAG query API (OpenSearch
`description_embedding` fields + query-time embedding). CLAUDE.md's
"OpenSearch 스키마" section left the embedding model choice explicitly
unpicked ("임베딩 모델 선정은 미착수... 자체 호스팅 가능한 모델... 우선
검토할 것, OpenAI 등 외부 API 임베딩은... 지양") — this is the first
concrete pick.

Uses `fastembed` (ONNX Runtime under the hood) instead of
sentence-transformers/torch: same self-hosted requirement, much smaller
install and faster CPU inference, which matters here since there's no GPU
in this environment and ~28k entity/relation descriptions need embedding.
`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` is the
concrete model — small (~220MB), decent Korean coverage, good enough for
the "rough v1" retrieval strategy. Swap `EMBEDDING_MODEL_NAME` here later
if a better one is chosen; nothing else in the pipeline should depend on
which model runs, only on `EMBEDDING_DIM` matching the OpenSearch
`knn_vector` mapping dimension.
"""

from __future__ import annotations

from functools import lru_cache

from fastembed import TextEmbedding

EMBEDDING_MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
EMBEDDING_DIM = 384


@lru_cache
def _get_model() -> TextEmbedding:
    return TextEmbedding(model_name=EMBEDDING_MODEL_NAME)


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Batch-embed. Empty strings are embedded as-is (fastembed handles
    them fine); callers with genuinely missing text should filter first."""
    if not texts:
        return []
    return [vec.tolist() for vec in _get_model().embed(texts)]


def embed_text(text: str) -> list[float]:
    return embed_texts([text])[0]
