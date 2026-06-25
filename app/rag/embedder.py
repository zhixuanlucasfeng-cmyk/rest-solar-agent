import os
from functools import lru_cache
from sentence_transformers import SentenceTransformer
from dotenv import load_dotenv

load_dotenv()

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "paraphrase-multilingual-MiniLM-L12-v2")


@lru_cache(maxsize=1)
def _get_model() -> SentenceTransformer:
    """Load model once, cache in memory. Force CPU to avoid MPS backend issues on macOS."""
    return SentenceTransformer(EMBEDDING_MODEL, device="cpu")


def embed(text: str) -> list[float]:
    """Embed a single string. Returns a list of floats (384-dim for MiniLM-L12-v2)."""
    model = _get_model()
    return model.encode(text, convert_to_numpy=True).tolist()


def embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed multiple strings in one batch call (more efficient than calling embed() repeatedly)."""
    model = _get_model()
    return model.encode(texts, convert_to_numpy=True).tolist()
