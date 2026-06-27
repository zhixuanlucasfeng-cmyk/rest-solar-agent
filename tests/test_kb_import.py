from pathlib import Path
import importlib.util
import sys
import pytest
from app.rag import retriever
from scripts.kb_import import chunk_text


@pytest.fixture(autouse=True)
def isolated_chroma(tmp_path, monkeypatch):
    monkeypatch.setenv("CHROMA_PATH", str(tmp_path / "chroma"))
    retriever._client = None
    retriever._collection = None
    yield
    retriever._client = None
    retriever._collection = None


def _run_import(path: Path):
    spec = importlib.util.spec_from_file_location("kb_import", "scripts/kb_import.py")
    mod = importlib.util.module_from_spec(spec)
    sys.argv = ["kb_import.py", str(path)]
    spec.loader.exec_module(mod)
    mod.main(str(path))


def test_chunk_text_short_input_no_infinite_loop():
    # text shorter than CHUNK_OVERLAP (80) previously caused infinite loop
    short = "Solar panel specs. Battery info."
    chunks = chunk_text(short)
    assert len(chunks) == 1
    assert chunks[0] == short


def test_chunk_text_empty_input():
    assert chunk_text("") == []


def test_chunk_text_long_input_produces_multiple_chunks():
    long = "Word. " * 200  # ~1200 chars, > CHUNK_SIZE=500
    chunks = chunk_text(long)
    assert len(chunks) >= 2


@pytest.mark.slow
@pytest.mark.timeout(60)
def test_import_txt_file(tmp_path):
    txt = tmp_path / "test.txt"
    txt.write_text("Solar panel specifications.\n\nBattery warranty information.", encoding="utf-8")
    _run_import(txt)
    col = retriever._get_collection()
    assert col.count() >= 1


@pytest.mark.slow
@pytest.mark.timeout(60)
def test_import_creates_chunks_with_metadata(tmp_path):
    txt = tmp_path / "info.txt"
    txt.write_text("Rest Solar delivers across Cameroon. " * 30, encoding="utf-8")
    _run_import(txt)
    col = retriever._get_collection()
    results = col.get(include=["metadatas"])
    assert any(m["source_file"] == "info.txt" for m in results["metadatas"])
