import pytest
from app.rag.embedder import embed, embed_batch


@pytest.mark.slow
def test_embed_returns_floats():
    result = embed("What solar panels do you sell?")
    assert isinstance(result, list)
    assert len(result) == 384   # MiniLM-L12-v2 dimension
    assert all(isinstance(x, float) for x in result)


@pytest.mark.slow
def test_embed_batch_same_as_individual():
    texts = ["Hello", "Bonjour"]
    batch = embed_batch(texts)
    assert len(batch) == 2
    single = embed("Hello")
    # Batch and single encoding may differ by tiny float precision amounts
    assert len(batch[0]) == len(single)
    assert all(abs(a - b) < 1e-4 for a, b in zip(batch[0], single))


@pytest.mark.slow
def test_different_texts_produce_different_embeddings():
    a = embed("solar panel warranty")
    b = embed("delivery time Cameroon")
    assert a != b
