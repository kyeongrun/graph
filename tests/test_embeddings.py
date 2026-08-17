from graphdb.embeddings import EMBEDDING_DIM, embed_text, embed_texts


def test_embed_text_returns_expected_dim():
    vec = embed_text("금융위원회는 은행을 감독한다")
    assert len(vec) == EMBEDDING_DIM
    assert all(isinstance(x, float) for x in vec)


def test_embed_texts_batch_matches_single():
    vecs = embed_texts(["금융위원회", "감사원장"])
    assert len(vecs) == 2
    assert all(len(v) == EMBEDDING_DIM for v in vecs)


def test_embed_texts_empty_list():
    assert embed_texts([]) == []
