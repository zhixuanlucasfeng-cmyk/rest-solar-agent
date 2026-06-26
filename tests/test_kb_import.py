from pathlib import Path
import importlib.util
import sys
import pytest
from app.rag import retriever


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


def test_import_txt_file(tmp_path):
    txt = tmp_path / "test.txt"
    txt.write_text("Solar panel specifications.\n\nBattery warranty information.", encoding="utf-8")
    _run_import(txt)
    col = retriever._get_collection()
    assert col.count() >= 1


def test_import_creates_chunks_with_metadata(tmp_path):
    txt = tmp_path / "info.txt"
    txt.write_text("Rest Solar delivers across Cameroon. " * 30, encoding="utf-8")
    _run_import(txt)
    col = retriever._get_collection()
    results = col.get(include=["metadatas"])
    assert any(m["source_file"] == "info.txt" for m in results["metadatas"])
