import pytest
from app.rag.embedder import embed
from app.rag import retriever


@pytest.fixture(autouse=True)
def isolated_chroma(tmp_path, monkeypatch):
    monkeypatch.setenv("CHROMA_PATH", str(tmp_path / "chroma"))
    retriever._client = None
    retriever._collection = None
    yield
    retriever._client = None
    retriever._collection = None


def test_upsert_and_query():
    text = "We sell solar panels from 50W to 550W."
    vec = embed(text)
    retriever.upsert("doc1", text, vec, {"source_file": "test.txt", "language": "en", "chunk_index": 0})

    results = retriever.query(vec, n_results=1)
    assert len(results) == 1
    assert results[0]["text"] == text
    assert results[0]["distance"] < 0.01


def test_query_returns_closest():
    panel_text = "Solar panels convert sunlight to electricity."
    battery_text = "Lithium batteries store solar energy."
    retriever.upsert("p1", panel_text, embed(panel_text), {"source_file": "f", "language": "en", "chunk_index": 0})
    retriever.upsert("b1", battery_text, embed(battery_text), {"source_file": "f", "language": "en", "chunk_index": 1})

    results = retriever.query(embed("solar panel watts"), n_results=2)
    assert len(results) == 2
    assert results[0]["text"] == panel_text


def test_empty_collection_returns_empty():
    results = retriever.query([0.0] * 384, n_results=3)
    assert results == []
