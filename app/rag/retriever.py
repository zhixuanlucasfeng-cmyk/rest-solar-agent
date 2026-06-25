import os
import chromadb
from dotenv import load_dotenv

load_dotenv()

COLLECTION_NAME = "knowledge_base"

_client = None
_collection = None


def _get_collection():
    global _client, _collection
    if _collection is None:
        path = os.getenv("CHROMA_PATH", "./data/chroma_db")
        _client = chromadb.PersistentClient(path=path)
        _collection = _client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
    return _collection


def upsert(doc_id: str, text: str, embedding: list[float], metadata: dict) -> None:
    col = _get_collection()
    col.upsert(
        ids=[doc_id],
        embeddings=[embedding],
        documents=[text],
        metadatas=[metadata],
    )


def query(embedding: list[float], n_results: int = 3) -> list[dict]:
    col = _get_collection()
    count = col.count()
    if count == 0:
        return []
    n = min(n_results, count)
    results = col.query(
        query_embeddings=[embedding],
        n_results=n,
        include=["documents", "distances", "metadatas"],
    )
    return [
        {"text": doc, "distance": dist, "metadata": meta}
        for doc, dist, meta in zip(
            results["documents"][0],
            results["distances"][0],
            results["metadatas"][0],
        )
    ]
