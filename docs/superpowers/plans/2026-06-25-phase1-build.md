# Rest Solar Agent — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a working bilingual (EN/FR) AI customer-service demo for Rest Solar: FastAPI backend with RAG, rule-based guardrails, CNY↔XAF currency tool, and an embeddable chat widget — all runnable locally with no Docker.

**Architecture:** Customer messages flow through a 4-layer pipeline: Rule Engine (hard guardrails from SQLite) → RAG Retriever (ChromaDB PersistentClient, in-process) → LLM Orchestrator (OpenAI-compat client, OpenRouter by default, swappable to Ollama via `.env`) → Tool Dispatcher (CurrencyTool in Phase 1). Everything runs server-side; the API key never reaches the browser.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy + aiosqlite (SQLite), ChromaDB PersistentClient, sentence-transformers (`paraphrase-multilingual-MiniLM-L12-v2`, 420 MB, CPU), `openai` Python client (OpenAI-compat protocol), Jinja2 templates, vanilla JS widget.

## Global Constraints

- Python version: **3.12** exactly (install via `brew install python@3.12` if missing)
- DB: SQLite + `create_all()` only — no Alembic in Phase 1
- Vector DB: ChromaDB **PersistentClient** only — no Docker, no HTTP server
- Embeddings: `paraphrase-multilingual-MiniLM-L12-v2` local — first run downloads ~420 MB to `~/.cache/huggingface/`
- LLM provider: fully swappable via `LLM_BASE_URL` + `LLM_MODEL` + `LLM_API_KEY` in `.env`
- No keys hardcoded anywhere — all secrets from `.env` via `python-dotenv`
- Language: detect EN vs FR per message; reply in the same language
- Anti-hallucination: never invent a price, duty rate, or spec not in the KB

---

## File Map

```
rest-solar-agent/
├── app/
│   ├── __init__.py
│   ├── main.py                    # FastAPI app — mounts router, serves templates
│   ├── api/
│   │   ├── __init__.py
│   │   └── chat.py                # POST /api/chat   GET /chat
│   ├── agent/
│   │   ├── __init__.py
│   │   ├── orchestrator.py        # 8-step pipeline — calls all other layers
│   │   ├── rule_engine.py         # query rules table by trigger keyword
│   │   └── language_detector.py   # langdetect + regex fallback → "en"|"fr"
│   ├── rag/
│   │   ├── __init__.py
│   │   ├── embedder.py            # sentence-transformers; embed(str) → list[float]
│   │   └── retriever.py           # ChromaDB PersistentClient; upsert + query
│   ├── llm/
│   │   ├── __init__.py
│   │   └── client.py              # AsyncOpenAI wrapper; reads LLM_* env vars
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── base.py                # BaseTool ABC
│   │   └── currency.py            # CurrencyTool: CNY↔XAF
│   └── db/
│       ├── __init__.py
│       ├── models.py              # SQLAlchemy: Conversation, Message, Rule
│       └── session.py             # async engine + get_db() FastAPI dependency
├── data/
│   ├── seeds/
│   │   ├── faqs_en.txt            # 5 English Q&A blocks (double-newline separated)
│   │   └── faqs_fr.txt            # 5 French Q&A blocks
│   └── chroma_db/                 # auto-created by ChromaDB (gitignored)
├── scripts/
│   └── kb_import.py               # CLI: python scripts/kb_import.py <file>
├── static/
│   └── widget.js                  # embeddable chat widget (vanilla JS)
├── templates/
│   └── chat.html                  # Jinja2 demo chat page
├── tests/
│   ├── conftest.py                # pytest fixtures: in-memory DB, tmp chroma dir
│   ├── test_db.py
│   ├── test_embedder.py
│   ├── test_retriever.py
│   ├── test_llm_client.py
│   ├── test_rule_engine.py
│   ├── test_language_detector.py
│   ├── test_currency_tool.py
│   ├── test_orchestrator.py
│   ├── test_chat_api.py
│   └── test_kb_import.py
├── seed.py                        # python seed.py — creates tables + seeds DB + ChromaDB
├── pytest.ini
├── .env                           # real secrets (gitignored)
├── .env.example                   # template committed to git
├── .gitignore
└── requirements.txt
```

---

## Task 1: Python 3.12, project scaffold, and tooling

**Files:**
- Create: `requirements.txt`
- Create: `.env.example`
- Create: `.gitignore`
- Create: `pytest.ini`
- Create: all `__init__.py` files
- Create: `data/seeds/faqs_en.txt`
- Create: `data/seeds/faqs_fr.txt`

**Interfaces:**
- Produces: runnable `python3.12 -m pytest` with zero test failures (no tests yet = pass)

- [ ] **Step 1: Install Python 3.12 via Homebrew**

```bash
brew install python@3.12
python3.12 --version
# Expected: Python 3.12.x
```

- [ ] **Step 2: Create and activate virtual environment**

```bash
cd ~/rest-solar-agent
python3.12 -m venv .venv
source .venv/bin/activate
python --version
# Expected: Python 3.12.x
```

- [ ] **Step 3: Create `requirements.txt`**

```
fastapi>=0.111.0
uvicorn[standard]>=0.29.0
python-dotenv>=1.0.0
openai>=1.30.0
chromadb>=0.5.0
sentence-transformers>=3.0.0
langdetect>=1.0.9
sqlalchemy[asyncio]>=2.0.0
aiosqlite>=0.20.0
httpx>=0.27.0
pypdf>=3.0.0
openpyxl>=3.1.0
jinja2>=3.1.0
python-multipart>=0.0.9
beautifulsoup4>=4.12.0
pytest>=8.0.0
pytest-asyncio>=0.23.0
```

- [ ] **Step 4: Install dependencies**

```bash
pip install -r requirements.txt
```

Expected: all packages install without errors. Note: `sentence-transformers` will download ~420 MB on first model load (not here — happens in Task 3).

- [ ] **Step 5: Create `pytest.ini`**

```ini
[pytest]
asyncio_mode = auto
```

- [ ] **Step 6: Create `.env.example`**

```
# LLM provider — swap base_url+model to use Ollama locally
LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_API_KEY=sk-or-your-key-here
LLM_MODEL=google/gemini-3.1-flash-lite

# Embedding provider
EMBEDDING_PROVIDER=local
EMBEDDING_MODEL=paraphrase-multilingual-MiniLM-L12-v2

# Currency API (optional — leave blank for static rate 1 CNY = 90 XAF)
CURRENCY_API_KEY=

# Paths
DATABASE_URL=sqlite+aiosqlite:///./data/rest_solar.db
CHROMA_PATH=./data/chroma_db
```

- [ ] **Step 7: Copy `.env.example` to `.env` and fill in your real `LLM_API_KEY`**

```bash
cp .env.example .env
# Edit .env and set LLM_API_KEY to your real OpenRouter key
```

- [ ] **Step 8: Create `.gitignore`**

```
.venv/
.env
__pycache__/
*.pyc
data/chroma_db/
data/rest_solar.db
.pytest_cache/
*.egg-info/
dist/
```

- [ ] **Step 9: Create all package directories and `__init__.py` files**

```bash
mkdir -p app/api app/agent app/rag app/llm app/tools app/db
mkdir -p data/seeds data/chroma_db scripts static templates tests
touch app/__init__.py app/api/__init__.py app/agent/__init__.py \
      app/rag/__init__.py app/llm/__init__.py app/tools/__init__.py \
      app/db/__init__.py
```

- [ ] **Step 10: Create `data/seeds/faqs_en.txt`**

```
Q: What solar panel sizes do you sell?
A: We stock monocrystalline solar panels ranging from 50W to 550W. Our most popular sizes for homes are the 200W and 330W panels, while the 450W and 550W panels are preferred for businesses and borehole pumping systems.

Q: What warranty do your batteries come with?
A: Our lithium LiFePO4 batteries carry a 2-year warranty against manufacturing defects. Tubular gel batteries carry a 1-year warranty. All warranty claims must be accompanied by proof of purchase and installation documentation.

Q: Do you deliver to cities outside Douala?
A: Yes, we deliver across Cameroon including Yaoundé, Bafoussam, Bamenda, Garoua, Maroua, Bertoua, and all major cities. Delivery times and costs vary by location. Contact us for a quote specific to your area.

Q: How long does a shipment from China take?
A: Sea freight from our factory in China to Douala port typically takes 30 to 45 days, depending on vessel schedules and port clearance. We also offer faster air freight for urgent orders, which takes 7 to 10 days at higher cost.

Q: What is the Cameroon import duty on solar panels?
A: As of our most recent information, solar panels are classified under HS code 8541.40 and attract a 10% import duty plus 19.25% VAT on the CIF value. These rates can change — always verify with a licensed customs broker before importing.
```

- [ ] **Step 11: Create `data/seeds/faqs_fr.txt`**

```
Q: Quelles tailles de panneaux solaires vendez-vous ?
R: Nous proposons des panneaux solaires monocristallins de 50W à 550W. Les tailles les plus populaires pour les foyers sont les panneaux 200W et 330W, tandis que les panneaux 450W et 550W sont privilégiés pour les entreprises et les systèmes de pompage de forage.

Q: Quelle garantie offrez-vous sur les batteries ?
R: Nos batteries lithium LiFePO4 bénéficient d'une garantie de 2 ans contre les défauts de fabrication. Les batteries tubulaires gel bénéficient d'une garantie d'un an. Toute demande de garantie doit être accompagnée d'un justificatif d'achat et d'une documentation d'installation.

Q: Livrez-vous en dehors de Douala ?
R: Oui, nous livrons partout au Cameroun, notamment à Yaoundé, Bafoussam, Bamenda, Garoua, Maroua, Bertoua et dans toutes les grandes villes. Les délais et frais de livraison varient selon la localisation. Contactez-nous pour un devis adapté à votre zone.

Q: Combien de temps prend une expédition depuis la Chine ?
R: Le fret maritime depuis notre usine en Chine jusqu'au port de Douala prend généralement 30 à 45 jours, selon les plannings des navires et le dédouanement. Nous proposons également le fret aérien pour les commandes urgentes, avec un délai de 7 à 10 jours, à un coût plus élevé.

Q: Quels sont les droits d'importation au Cameroun pour les panneaux solaires ?
R: Selon nos dernières informations, les panneaux solaires sont classés sous le code SH 8541.40 et sont soumis à 10 % de droits d'importation plus 19,25 % de TVA sur la valeur CAF. Ces taux peuvent évoluer — vérifiez toujours auprès d'un transitaire agréé avant toute importation.
```

- [ ] **Step 12: Verify pytest runs (zero tests = pass)**

```bash
pytest
# Expected: "no tests ran" or "0 passed" — no errors
```

- [ ] **Step 13: Commit**

```bash
git add requirements.txt .env.example .gitignore pytest.ini \
        app/ data/seeds/ scripts/ static/ templates/ tests/
git commit -m "feat: project scaffold — Python 3.12, venv, directory structure"
```

---

## Task 2: Database models and session

**Files:**
- Create: `app/db/models.py`
- Create: `app/db/session.py`
- Create: `tests/conftest.py`
- Create: `tests/test_db.py`

**Interfaces:**
- Produces:
  - `Base` (DeclarativeBase) — imported by `seed.py` and `session.py`
  - `Conversation`, `Message`, `Rule` — SQLAlchemy mapped classes
  - `engine` — AsyncEngine, used by `seed.py` for `create_all()`
  - `AsyncSessionLocal` — async_sessionmaker, used by `seed.py`
  - `get_db()` — async FastAPI dependency yielding `AsyncSession`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_db.py
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.db.models import Base, Conversation, Message, Rule

TEST_URL = "sqlite+aiosqlite:///:memory:"

@pytest.fixture
async def db():
    eng = create_async_engine(TEST_URL)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(eng, expire_on_commit=False)
    async with Session() as session:
        yield session
    await eng.dispose()

async def test_create_rule(db: AsyncSession):
    rule = Rule(name="test_rule", trigger="price", body="Never invent prices.", priority=1)
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    assert rule.id is not None
    assert rule.active is True

async def test_create_conversation_and_message(db: AsyncSession):
    conv = Conversation(session_id="abc-123", language="en")
    db.add(conv)
    await db.flush()
    msg = Message(conversation_id=conv.id, role="user", content="Hello")
    db.add(msg)
    await db.commit()
    assert msg.id is not None
    assert msg.tool_name is None
```

- [ ] **Step 2: Run to confirm it fails**

```bash
pytest tests/test_db.py -v
# Expected: ImportError — app.db.models not found
```

- [ ] **Step 3: Write `app/db/models.py`**

```python
from datetime import datetime
from sqlalchemy import Integer, String, Text, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(36), index=True)
    language: Mapped[str] = mapped_column(String(2), default="en")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    messages: Mapped[list["Message"]] = relationship("Message", back_populates="conversation")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"))
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    tool_name: Mapped[str | None] = mapped_column(String(50), nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    conversation: Mapped["Conversation"] = relationship("Conversation", back_populates="messages")


class Rule(Base):
    __tablename__ = "rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    trigger: Mapped[str] = mapped_column(String(200), default="")
    body: Mapped[str] = mapped_column(Text)
    priority: Mapped[int] = mapped_column(Integer, default=10)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
```

- [ ] **Step 4: Write `app/db/session.py`**

```python
import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./data/rest_solar.db")

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db():
    """FastAPI dependency: yields an AsyncSession, commits on exit."""
    async with AsyncSessionLocal() as session:
        yield session
```

- [ ] **Step 5: Add shared DB fixture to `tests/conftest.py`**

```python
# tests/conftest.py
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.db.models import Base

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture
async def db() -> AsyncSession:
    eng = create_async_engine(TEST_DB_URL)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(eng, expire_on_commit=False)
    async with Session() as session:
        yield session
    await eng.dispose()
```

- [ ] **Step 6: Remove the local `db` fixture from `tests/test_db.py` (now in conftest)**

Update `tests/test_db.py` — remove the `@pytest.fixture async def db()` block; the import of `AsyncSession` stays for type hints:

```python
# tests/test_db.py
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import Conversation, Message, Rule


async def test_create_rule(db: AsyncSession):
    rule = Rule(name="test_rule", trigger="price", body="Never invent prices.", priority=1)
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    assert rule.id is not None
    assert rule.active is True


async def test_create_conversation_and_message(db: AsyncSession):
    conv = Conversation(session_id="abc-123", language="en")
    db.add(conv)
    await db.flush()
    msg = Message(conversation_id=conv.id, role="user", content="Hello")
    db.add(msg)
    await db.commit()
    assert msg.id is not None
    assert msg.tool_name is None
```

- [ ] **Step 7: Run tests**

```bash
pytest tests/test_db.py -v
# Expected: 2 passed
```

- [ ] **Step 8: Commit**

```bash
git add app/db/ tests/conftest.py tests/test_db.py
git commit -m "feat: SQLAlchemy models (Conversation, Message, Rule) + async session"
```

---

## Task 3: Embedder (sentence-transformers, local CPU)

**Files:**
- Create: `app/rag/embedder.py`
- Create: `tests/test_embedder.py`

**Interfaces:**
- Produces:
  - `embed(text: str) -> list[float]` — embed a single string
  - `embed_batch(texts: list[str]) -> list[list[float]]` — embed multiple strings
- Consumes: `EMBEDDING_MODEL` env var (default `paraphrase-multilingual-MiniLM-L12-v2`)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_embedder.py
from app.rag.embedder import embed, embed_batch


def test_embed_returns_floats():
    result = embed("What solar panels do you sell?")
    assert isinstance(result, list)
    assert len(result) == 384   # MiniLM-L12-v2 dimension
    assert all(isinstance(x, float) for x in result)


def test_embed_batch_same_as_individual():
    texts = ["Hello", "Bonjour"]
    batch = embed_batch(texts)
    assert len(batch) == 2
    single = embed("Hello")
    # Vectors should be identical (same model, deterministic)
    assert batch[0] == single


def test_different_texts_produce_different_embeddings():
    a = embed("solar panel warranty")
    b = embed("delivery time Cameroon")
    assert a != b
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_embedder.py -v
# Expected: ImportError — app.rag.embedder not found
# Note: first run after implementing will download the model (~420 MB).
```

- [ ] **Step 3: Write `app/rag/embedder.py`**

```python
import os
from functools import lru_cache
from sentence_transformers import SentenceTransformer
from dotenv import load_dotenv

load_dotenv()

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "paraphrase-multilingual-MiniLM-L12-v2")


@lru_cache(maxsize=1)
def _get_model() -> SentenceTransformer:
    """Load model once, cache in memory for the process lifetime."""
    return SentenceTransformer(EMBEDDING_MODEL)


def embed(text: str) -> list[float]:
    """Embed a single string. Returns a list of floats (384-dim for MiniLM-L12-v2)."""
    model = _get_model()
    return model.encode(text, convert_to_numpy=True).tolist()


def embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed multiple strings in one batch call (more efficient than calling embed() repeatedly)."""
    model = _get_model()
    return model.encode(texts, convert_to_numpy=True).tolist()
```

- [ ] **Step 4: Run tests (first run downloads the model — takes a few minutes)**

```bash
pytest tests/test_embedder.py -v
# Expected: 3 passed
# First run will print: "Downloading paraphrase-multilingual-MiniLM-L12-v2 (~420 MB)..."
```

- [ ] **Step 5: Commit**

```bash
git add app/rag/embedder.py tests/test_embedder.py
git commit -m "feat: local sentence-transformers embedder (paraphrase-multilingual-MiniLM-L12-v2)"
```

---

## Task 4: ChromaDB retriever (PersistentClient, embedded)

**Files:**
- Create: `app/rag/retriever.py`
- Create: `tests/test_retriever.py`

**Interfaces:**
- Produces:
  - `upsert(doc_id: str, text: str, embedding: list[float], metadata: dict) -> None`
  - `query(embedding: list[float], n_results: int = 3) -> list[dict]`
    - Each dict: `{"text": str, "distance": float, "metadata": dict}`
- Consumes: `embed()` from `app.rag.embedder`, `CHROMA_PATH` env var

- [ ] **Step 1: Write the failing test**

```python
# tests/test_retriever.py
import tempfile
import os
import pytest
from app.rag.embedder import embed
from app.rag import retriever


@pytest.fixture
def tmp_retriever(tmp_path, monkeypatch):
    """Give each test its own isolated ChromaDB directory."""
    monkeypatch.setenv("CHROMA_PATH", str(tmp_path / "chroma"))
    retriever._client = None   # reset singleton
    retriever._collection = None
    yield
    retriever._client = None
    retriever._collection = None


def test_upsert_and_query(tmp_retriever):
    text = "We sell solar panels from 50W to 550W."
    vec = embed(text)
    retriever.upsert("doc1", text, vec, {"source_file": "test.txt", "language": "en", "chunk_index": 0})

    results = retriever.query(vec, n_results=1)
    assert len(results) == 1
    assert results[0]["text"] == text
    assert results[0]["distance"] < 0.01   # identical vector → near-zero distance


def test_query_returns_closest(tmp_retriever):
    panel_text = "Solar panels convert sunlight to electricity."
    battery_text = "Lithium batteries store solar energy."
    retriever.upsert("p1", panel_text, embed(panel_text), {"source_file": "f", "language": "en", "chunk_index": 0})
    retriever.upsert("b1", battery_text, embed(battery_text), {"source_file": "f", "language": "en", "chunk_index": 1})

    results = retriever.query(embed("solar panel watts"), n_results=2)
    assert len(results) == 2
    # Panel text should be closer to "solar panel watts" than battery text
    assert results[0]["text"] == panel_text
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_retriever.py -v
# Expected: ImportError — app.rag.retriever not found
```

- [ ] **Step 3: Write `app/rag/retriever.py`**

```python
import os
import chromadb
from dotenv import load_dotenv

load_dotenv()

CHROMA_PATH = os.getenv("CHROMA_PATH", "./data/chroma_db")
COLLECTION_NAME = "knowledge_base"

# Module-level singletons — reset to None in tests via monkeypatch
_client: chromadb.PersistentClient | None = None
_collection = None


def _get_collection():
    global _client, _collection
    if _collection is None:
        _client = chromadb.PersistentClient(path=CHROMA_PATH)
        _collection = _client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},  # cosine distance
        )
    return _collection


def upsert(doc_id: str, text: str, embedding: list[float], metadata: dict) -> None:
    """Insert or overwrite a document chunk in the knowledge base."""
    col = _get_collection()
    col.upsert(
        ids=[doc_id],
        embeddings=[embedding],
        documents=[text],
        metadatas=[metadata],
    )


def query(embedding: list[float], n_results: int = 3) -> list[dict]:
    """Return top-n chunks closest to the query embedding.

    Each result dict: {"text": str, "distance": float, "metadata": dict}
    Distance is cosine distance: 0 = identical, 2 = opposite.
    """
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
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_retriever.py -v
# Expected: 2 passed
```

- [ ] **Step 5: Commit**

```bash
git add app/rag/retriever.py tests/test_retriever.py
git commit -m "feat: ChromaDB PersistentClient retriever (upsert + cosine query)"
```

---

## Task 5: Seed script — rules + FAQs

**Files:**
- Create: `seed.py`
- Create: `tests/test_seed.py`

**Interfaces:**
- Consumes: `Base`, `Rule`, `engine`, `AsyncSessionLocal` from `app.db`; `embed()` from `app.rag.embedder`; `upsert()` from `app.rag.retriever`
- Produces: `python seed.py` loads 3 rules into SQLite and 10 FAQ chunks into ChromaDB

- [ ] **Step 1: Write the failing test**

```python
# tests/test_seed.py
import tempfile
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy import select
from app.db.models import Base, Rule
from app.rag import retriever


@pytest.fixture
async def seed_env(tmp_path, monkeypatch):
    """Isolated DB + ChromaDB for seed test."""
    db_url = f"sqlite+aiosqlite:///{tmp_path}/test.db"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("CHROMA_PATH", str(tmp_path / "chroma"))
    retriever._client = None
    retriever._collection = None

    # Patch session module to use test DB
    import app.db.session as sess
    sess.engine = create_async_engine(db_url)
    sess.AsyncSessionLocal = async_sessionmaker(sess.engine, expire_on_commit=False)

    yield sess

    retriever._client = None
    retriever._collection = None


async def test_seed_inserts_rules(seed_env):
    import importlib
    import seed as seed_module
    importlib.reload(seed_module)
    await seed_module.seed()

    async with seed_env.AsyncSessionLocal() as db:
        result = await db.execute(select(Rule))
        rules = result.scalars().all()
    assert len(rules) == 3
    names = {r.name for r in rules}
    assert "no_invented_prices" in names
    assert "cameroon_vat" in names
    assert "low_score_fallback" in names


async def test_seed_inserts_faq_chunks(seed_env):
    import importlib
    import seed as seed_module
    importlib.reload(seed_module)
    await seed_module.seed()

    col = retriever._get_collection()
    assert col.count() == 10   # 5 EN + 5 FR
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_seed.py -v
# Expected: ModuleNotFoundError — seed not found
```

- [ ] **Step 3: Write `seed.py`**

```python
"""
Run once to populate the database and knowledge base:
    python seed.py
"""
import asyncio
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from app.db.session import engine, AsyncSessionLocal
from app.db.models import Base, Rule
from app.rag.embedder import embed_batch
from app.rag.retriever import upsert

RULES = [
    {
        "name": "low_score_fallback",
        "trigger": "",   # empty trigger = always active (checked by priority 0)
        "body": (
            "If no relevant knowledge-base chunks were retrieved "
            "(cosine distance > 0.5), do not attempt to answer from general "
            "knowledge. Say you do not have specific information and offer to "
            "raise a support ticket."
        ),
        "priority": 0,
    },
    {
        "name": "no_invented_prices",
        "trigger": "price/tariff/duty/vat/prix/taxe/cost/coût",
        "body": (
            "You MUST only quote prices and duties from the retrieved "
            "knowledge-base chunks. If no price is found in context, say you "
            "do not have that information and offer a support ticket. "
            "Never invent a number."
        ),
        "priority": 1,
    },
    {
        "name": "cameroon_vat",
        "trigger": "vat/tax/taxe/tva/duty/droit",
        "body": (
            "Cameroon VAT is 19.25%. Never state a different rate unless a "
            "knowledge-base chunk explicitly overrides it."
        ),
        "priority": 2,
    },
]


async def seed():
    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("✓ Tables created")

    # Insert rules (skip if already exist)
    async with AsyncSessionLocal() as db:
        from sqlalchemy import select
        existing = (await db.execute(select(Rule.name))).scalars().all()
        for r in RULES:
            if r["name"] not in existing:
                db.add(Rule(**r))
        await db.commit()
    print(f"✓ {len(RULES)} rules seeded into SQLite")

    # Load FAQ files and embed
    seeds_dir = Path("data/seeds")
    for faq_file in sorted(seeds_dir.glob("faqs_*.txt")):
        lang = faq_file.stem.split("_")[1]   # "en" or "fr"
        raw = faq_file.read_text(encoding="utf-8").strip()
        blocks = [b.strip() for b in raw.split("\n\n") if b.strip()]
        texts = blocks
        embeddings = embed_batch(texts)
        for i, (text, vec) in enumerate(zip(texts, embeddings)):
            doc_id = f"{faq_file.stem}_{i}"
            upsert(doc_id, text, vec, {
                "source_file": faq_file.name,
                "language": lang,
                "chunk_index": i,
            })
        print(f"✓ {len(blocks)} FAQ chunks seeded from {faq_file.name}")


if __name__ == "__main__":
    asyncio.run(seed())
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_seed.py -v
# Expected: 2 passed
```

- [ ] **Step 5: Run the seed for real**

```bash
python seed.py
# Expected:
# ✓ Tables created
# ✓ 3 rules seeded into SQLite
# ✓ 5 FAQ chunks seeded from faqs_en.txt
# ✓ 5 FAQ chunks seeded from faqs_fr.txt
```

- [ ] **Step 6: Commit**

```bash
git add seed.py tests/test_seed.py
git commit -m "feat: seed script — 3 rules + 10 bilingual FAQ chunks"
```

---

## Task 6: LLM client (OpenAI-compat, reads from .env)

**Files:**
- Create: `app/llm/client.py`
- Create: `tests/test_llm_client.py`

**Interfaces:**
- Produces:
  - `get_client() -> openai.AsyncOpenAI` — configured from env vars
  - `chat_complete(messages: list[dict], tools: list[dict] | None = None)` — returns `openai.types.chat.ChatCompletionMessage`
  - `LLM_MODEL: str` — module-level constant read from `LLM_MODEL` env var

- [ ] **Step 1: Write the failing test**

```python
# tests/test_llm_client.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.llm.client import chat_complete, get_client, LLM_MODEL


def test_llm_model_has_value():
    assert isinstance(LLM_MODEL, str)
    assert len(LLM_MODEL) > 0


@pytest.mark.asyncio
async def test_chat_complete_calls_api():
    fake_message = MagicMock()
    fake_message.content = "Solar panels available from 50W to 550W."
    fake_message.tool_calls = None

    fake_response = MagicMock()
    fake_response.choices = [MagicMock(message=fake_message)]

    with patch("app.llm.client.get_client") as mock_get:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=fake_response)
        mock_get.return_value = mock_client

        messages = [{"role": "user", "content": "What panels do you sell?"}]
        result = await chat_complete(messages)

    assert result.content == "Solar panels available from 50W to 550W."


@pytest.mark.asyncio
async def test_chat_complete_passes_tools():
    fake_message = MagicMock()
    fake_message.content = None
    fake_message.tool_calls = [MagicMock()]

    fake_response = MagicMock()
    fake_response.choices = [MagicMock(message=fake_message)]

    with patch("app.llm.client.get_client") as mock_get:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=fake_response)
        mock_get.return_value = mock_client

        tools = [{"type": "function", "function": {"name": "currency_convert", "parameters": {}}}]
        result = await chat_complete([{"role": "user", "content": "hi"}], tools=tools)
        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert "tools" in call_kwargs
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_llm_client.py -v
# Expected: ImportError
```

- [ ] **Step 3: Write `app/llm/client.py`**

```python
import os
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()

LLM_MODEL: str = os.getenv("LLM_MODEL", "google/gemini-3.1-flash-lite")


def get_client() -> AsyncOpenAI:
    """Build an AsyncOpenAI client from env vars.

    To use Ollama locally:
        LLM_BASE_URL=http://localhost:11434/v1
        LLM_API_KEY=ollama
        LLM_MODEL=gemma4
    """
    return AsyncOpenAI(
        base_url=os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1"),
        api_key=os.getenv("LLM_API_KEY", ""),
    )


async def chat_complete(messages: list[dict], tools: list[dict] | None = None):
    """Call the LLM and return the assistant ChatCompletionMessage.

    If tools is provided, the LLM may return a tool_call instead of text.
    Caller must check response.tool_calls before reading response.content.
    """
    client = get_client()
    kwargs: dict = {"model": LLM_MODEL, "messages": messages}
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"
    response = await client.chat.completions.create(**kwargs)
    return response.choices[0].message
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_llm_client.py -v
# Expected: 3 passed
```

- [ ] **Step 5: Commit**

```bash
git add app/llm/client.py tests/test_llm_client.py
git commit -m "feat: OpenAI-compat LLM client (OpenRouter default, Ollama-swappable)"
```

---

## Task 7: Rule engine + language detector

**Files:**
- Create: `app/agent/rule_engine.py`
- Create: `app/agent/language_detector.py`
- Create: `tests/test_rule_engine.py`
- Create: `tests/test_language_detector.py`

**Interfaces:**
- Produces:
  - `get_matching_rules(text: str, db: AsyncSession) -> list[str]` — matched rule bodies, priority-ordered
  - `detect_language(text: str) -> str` — returns `"en"` or `"fr"`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_rule_engine.py
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import Rule
from app.agent.rule_engine import get_matching_rules


async def test_matches_trigger_keyword(db: AsyncSession):
    db.add(Rule(name="r1", trigger="price/prix", body="Never invent prices.", priority=1))
    await db.commit()
    result = await get_matching_rules("What is the price of a 200W panel?", db)
    assert "Never invent prices." in result


async def test_no_match_returns_empty(db: AsyncSession):
    db.add(Rule(name="r2", trigger="warranty/garantie", body="Warranty policy.", priority=1))
    await db.commit()
    result = await get_matching_rules("Tell me about delivery time.", db)
    assert result == []


async def test_always_active_rule_matches_everything(db: AsyncSession):
    """A rule with empty trigger should always match."""
    db.add(Rule(name="fallback", trigger="", body="Always active rule.", priority=0))
    await db.commit()
    result = await get_matching_rules("anything at all", db)
    assert "Always active rule." in result


async def test_priority_order(db: AsyncSession):
    db.add(Rule(name="low_pri", trigger="solar", body="Low priority body.", priority=10))
    db.add(Rule(name="high_pri", trigger="solar", body="High priority body.", priority=1))
    await db.commit()
    result = await get_matching_rules("solar panel", db)
    assert result[0] == "High priority body."
```

```python
# tests/test_language_detector.py
from app.agent.language_detector import detect_language


def test_detects_english():
    assert detect_language("What solar panels do you sell?") == "en"


def test_detects_french():
    assert detect_language("Quels panneaux solaires vendez-vous ?") == "fr"


def test_short_french_message():
    assert detect_language("Bonjour") == "fr"


def test_short_english_message():
    assert detect_language("Hello") == "en"


def test_mixed_defaults_to_detected():
    # French sentence with some English words
    result = detect_language("Je veux buy solar panels")
    assert result in ("en", "fr")   # either is acceptable; just must not raise
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_rule_engine.py tests/test_language_detector.py -v
# Expected: ImportError for both modules
```

- [ ] **Step 3: Write `app/agent/rule_engine.py`**

```python
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.models import Rule


async def get_matching_rules(text: str, db: AsyncSession) -> list[str]:
    """Return body text of active rules whose trigger keyword appears in text.

    Rules are sorted by priority (lower number = higher priority).
    A rule with an empty trigger always matches.
    Trigger field stores slash-separated keywords: "price/tariff/duty".
    """
    stmt = select(Rule).where(Rule.active.is_(True)).order_by(Rule.priority)
    result = await db.execute(stmt)
    rules = result.scalars().all()

    text_lower = text.lower()
    matched: list[str] = []

    for rule in rules:
        if not rule.trigger:          # empty trigger = always active
            matched.append(rule.body)
            continue
        keywords = [kw.strip() for kw in rule.trigger.split("/") if kw.strip()]
        if any(kw in text_lower for kw in keywords):
            matched.append(rule.body)

    return matched
```

- [ ] **Step 4: Write `app/agent/language_detector.py`**

```python
import re
from langdetect import detect, LangDetectException

# French vocabulary heuristic — catches short messages langdetect struggles with
_FR_RE = re.compile(
    r"\b(bonjour|bonsoir|merci|oui|non|votre|notre|vous|nous|est|les|des"
    r"|une|pour|avec|sur|dans|que|qui|quoi|quand|où|comment|combien|quel"
    r"|quelle|prix|panneau|solaire|batterie|onduleur|livraison|garantie"
    r"|achat|vouloir|voudrais|avez|avons|sommes|êtes|avez|panneau)\b",
    re.IGNORECASE,
)


def detect_language(text: str) -> str:
    """Return 'fr' or 'en'. Uses langdetect with regex fallback for short messages."""
    try:
        lang = detect(text)
        if lang in ("fr", "en"):
            return lang
    except LangDetectException:
        pass
    return "fr" if _FR_RE.search(text) else "en"
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_rule_engine.py tests/test_language_detector.py -v
# Expected: all pass
```

- [ ] **Step 6: Commit**

```bash
git add app/agent/rule_engine.py app/agent/language_detector.py \
        tests/test_rule_engine.py tests/test_language_detector.py
git commit -m "feat: rule engine (trigger-keyword matching) + language detector (EN/FR)"
```

---

## Task 8: CurrencyTool (CNY ↔ XAF)

**Files:**
- Create: `app/tools/base.py`
- Create: `app/tools/currency.py`
- Create: `tests/test_currency_tool.py`

**Interfaces:**
- Produces:
  - `BaseTool` — ABC with `definition() -> dict` and `async call(params: dict) -> dict`
  - `CurrencyTool` — subclass; `name = "currency_convert"`
  - `TOOLS: list[BaseTool]` — module-level list in `app/tools/currency.py`, imported by orchestrator
  - `TOOL_MAP: dict[str, BaseTool]` — `{tool.name: tool}`, imported by orchestrator

- [ ] **Step 1: Write the failing test**

```python
# tests/test_currency_tool.py
import pytest
from app.tools.currency import CurrencyTool

tool = CurrencyTool()


def test_definition_schema():
    defn = tool.definition()
    assert defn["type"] == "function"
    assert defn["function"]["name"] == "currency_convert"
    params = defn["function"]["parameters"]["properties"]
    assert "amount" in params
    assert "from_currency" in params
    assert "to_currency" in params


async def test_cny_to_xaf_static_rate():
    result = await tool.call({"amount": 100, "from_currency": "CNY", "to_currency": "XAF"})
    assert result["from"] == "CNY"
    assert result["to"] == "XAF"
    assert result["result"] == pytest.approx(9000.0, rel=0.01)   # 100 * 90


async def test_xaf_to_cny_static_rate():
    result = await tool.call({"amount": 900, "from_currency": "XAF", "to_currency": "CNY"})
    assert result["result"] == pytest.approx(10.0, rel=0.01)    # 900 / 90


async def test_rate_field_present():
    result = await tool.call({"amount": 1, "from_currency": "CNY", "to_currency": "XAF"})
    assert "rate" in result
    assert isinstance(result["rate"], float)
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_currency_tool.py -v
# Expected: ImportError
```

- [ ] **Step 3: Write `app/tools/base.py`**

```python
from abc import ABC, abstractmethod


class BaseTool(ABC):
    name: str
    description: str

    @abstractmethod
    def definition(self) -> dict:
        """Return OpenAI-compatible tool schema for function calling."""
        ...

    @abstractmethod
    async def call(self, params: dict) -> dict:
        """Execute the tool and return a result dict."""
        ...
```

- [ ] **Step 4: Write `app/tools/currency.py`**

```python
import os
import httpx
from app.tools.base import BaseTool
from dotenv import load_dotenv

load_dotenv()

STATIC_RATE_CNY_TO_XAF = 90.0   # 1 CNY ≈ 90 XAF — update manually if no API key


class CurrencyTool(BaseTool):
    name = "currency_convert"
    description = "Convert between CNY (Chinese Yuan Renminbi) and XAF (West African CFA franc)."

    def definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "amount": {
                            "type": "number",
                            "description": "Amount to convert (must be positive)",
                        },
                        "from_currency": {
                            "type": "string",
                            "enum": ["CNY", "XAF"],
                            "description": "Source currency",
                        },
                        "to_currency": {
                            "type": "string",
                            "enum": ["CNY", "XAF"],
                            "description": "Target currency",
                        },
                    },
                    "required": ["amount", "from_currency", "to_currency"],
                },
            },
        }

    async def call(self, params: dict) -> dict:
        amount = float(params["amount"])
        from_c = params["from_currency"].upper()
        to_c = params["to_currency"].upper()

        rate = await self._get_rate_cny_to_xaf()

        if from_c == "CNY" and to_c == "XAF":
            converted = round(amount * rate, 2)
        elif from_c == "XAF" and to_c == "CNY":
            converted = round(amount / rate, 2)
        else:
            return {"error": f"Unsupported pair: {from_c}/{to_c}"}

        return {
            "amount": amount,
            "from": from_c,
            "to": to_c,
            "rate": rate,
            "result": converted,
        }

    async def _get_rate_cny_to_xaf(self) -> float:
        """Fetch live CNY→XAF rate from exchangerate-api.com if key is set."""
        api_key = os.getenv("CURRENCY_API_KEY", "").strip()
        if not api_key:
            return STATIC_RATE_CNY_TO_XAF
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    f"https://v6.exchangerate-api.com/v6/{api_key}/pair/CNY/XAF"
                )
                data = resp.json()
                if data.get("result") == "success":
                    return float(data["conversion_rate"])
        except Exception:
            pass
        return STATIC_RATE_CNY_TO_XAF


# All Phase 1 tools registered here — orchestrator imports these two names
TOOLS: list[BaseTool] = [CurrencyTool()]
TOOL_MAP: dict[str, BaseTool] = {t.name: t for t in TOOLS}
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_currency_tool.py -v
# Expected: 4 passed
```

- [ ] **Step 6: Commit**

```bash
git add app/tools/base.py app/tools/currency.py tests/test_currency_tool.py
git commit -m "feat: CurrencyTool CNY<->XAF with static fallback + BaseTool ABC"
```

---

## Task 9: Agent Squad orchestrator (3 specialized agents)

**Overview:** Replace the hand-rolled pipeline with [Agent Squad](https://github.com/awslabs/agent-squad) (v1.0.2, the official successor to `multi-agent-orchestrator`). Agent Squad classifies incoming intent and routes to a specialist agent. Three agents handle the three domains: product FAQs (RAG-grounded), currency conversion (CurrencyTool), and general fallback. The public `run()` interface is unchanged so Tasks 10-12 need no edits.

**Files:**
- Create: `app/agent/squad.py` — builds and caches the AgentSquad singleton
- Create: `app/agent/orchestrator.py` — thin `run()` wrapper calling squad + SQLite persist
- Create: `tests/test_orchestrator.py`

**Interfaces:**
- Consumes:
  - `detect_language(text: str) -> str` from `app.agent.language_detector`
  - `get_matching_rules(text, db) -> list[str]` from `app.agent.rule_engine`
  - `embed(text: str) -> list[float]` from `app.rag.embedder`
  - `query(embedding, n_results) -> list[dict]` from `app.rag.retriever`
  - `CurrencyTool` from `app.tools.currency`
  - `Conversation, Message` from `app.db.models`
  - `AgentSquad, OpenAIClassifier, OpenAIAgent` from `agent_squad`
- Produces:
  - `async run(message: str, session_id: str, db: AsyncSession) -> dict`
    - Returns: `{"reply": str, "language": "en"|"fr"}`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_orchestrator.py
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import Rule
from app.agent.orchestrator import run


@pytest.fixture
async def db_with_rules(db: AsyncSession):
    db.add(Rule(
        name="low_score_fallback", trigger="", priority=0,
        body="If no KB chunks found, decline and offer a ticket."
    ))
    await db.commit()
    return db


async def _make_llm_text_response(content: str):
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = None
    return msg


async def _make_llm_tool_response(tool_name: str, args: dict, call_id: str = "call_1"):
    tc = MagicMock()
    tc.id = call_id
    tc.function.name = tool_name
    tc.function.arguments = json.dumps(args)

    msg = MagicMock()
    msg.content = None
    msg.tool_calls = [tc]
    return msg


@patch("app.agent.orchestrator.chat_complete")
@patch("app.agent.orchestrator.query", return_value=[
    {"text": "We sell panels from 50W to 550W.", "distance": 0.2, "metadata": {}}
])
@patch("app.agent.orchestrator.embed", return_value=[0.1] * 384)
async def test_plain_text_response(mock_embed, mock_query, mock_llm, db_with_rules):
    mock_llm.return_value = await _make_llm_text_response("We sell 50W to 550W panels.")
    result = await run("What panels do you sell?", "session-1", db_with_rules)
    assert result["reply"] == "We sell 50W to 550W panels."
    assert result["language"] == "en"


@patch("app.agent.orchestrator.chat_complete")
@patch("app.agent.orchestrator.query", return_value=[])
@patch("app.agent.orchestrator.embed", return_value=[0.1] * 384)
async def test_tool_call_currency(mock_embed, mock_query, mock_llm, db_with_rules):
    # First LLM call returns a tool_call; second returns the final answer
    tool_resp = await _make_llm_tool_response(
        "currency_convert",
        {"amount": 500, "from_currency": "CNY", "to_currency": "XAF"},
    )
    text_resp = await _make_llm_text_response("500 CNY = 45000 XAF at today's rate.")
    mock_llm.side_effect = [tool_resp, text_resp]

    result = await run("Convert 500 CNY to XAF", "session-2", db_with_rules)
    assert "45000" in result["reply"] or "XAF" in result["reply"]
    assert mock_llm.call_count == 2   # tool call + final answer


@patch("app.agent.orchestrator.chat_complete")
@patch("app.agent.orchestrator.query", return_value=[
    {"text": "Nous vendons des panneaux de 50W à 550W.", "distance": 0.3, "metadata": {}}
])
@patch("app.agent.orchestrator.embed", return_value=[0.1] * 384)
async def test_french_input_detected(mock_embed, mock_query, mock_llm, db_with_rules):
    mock_llm.return_value = await _make_llm_text_response("Nous vendons des panneaux solaires.")
    result = await run("Quels panneaux vendez-vous ?", "session-3", db_with_rules)
    assert result["language"] == "fr"
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_orchestrator.py -v
# Expected: ImportError — app.agent.orchestrator not found
```

- [ ] **Step 3: Write `app/agent/orchestrator.py`**

```python
import json
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.agent.language_detector import detect_language
from app.agent.rule_engine import get_matching_rules
from app.rag.embedder import embed
from app.rag.retriever import query
from app.llm.client import chat_complete, LLM_MODEL
from app.tools.currency import TOOLS, TOOL_MAP
from app.db.models import Conversation, Message

DISTANCE_THRESHOLD = 0.5   # cosine distance; lower = more similar
HISTORY_LIMIT = 10

_SYSTEM_TEMPLATE = """You are a helpful bilingual customer-service agent for Restar Solar, \
a solar energy company supplying products from China to Cameroon.

Reply language: {reply_language}. Always reply in the same language the customer used.

Business rules (follow these exactly):
{rules_text}

Be honest. If you lack specific information, say so clearly and offer to raise a support ticket."""


async def run(message: str, session_id: str, db: AsyncSession) -> dict:
    """Run the full 8-step agent pipeline. Returns {"reply": str, "language": str}."""

    # Step 1: detect language
    lang = detect_language(message)

    # Step 2: get or create conversation row
    result = await db.execute(
        select(Conversation).where(Conversation.session_id == session_id)
    )
    conv = result.scalar_one_or_none()
    if not conv:
        conv = Conversation(session_id=session_id, language=lang)
        db.add(conv)
        await db.flush()   # assign conv.id without committing

    # Step 3: load matching rules
    rule_bodies = await get_matching_rules(message, db)
    rules_text = "\n".join(f"- {body}" for body in rule_bodies) if rule_bodies else "None."

    # Step 4: RAG retrieval
    query_vec = embed(message)
    chunks = query(query_vec, n_results=3)
    relevant = [c for c in chunks if c["distance"] < DISTANCE_THRESHOLD]

    context_block = ""
    if relevant:
        context_block = "Relevant information from our knowledge base:\n" + "\n---\n".join(
            c["text"] for c in relevant
        )

    # Step 5: build messages list
    system_content = _SYSTEM_TEMPLATE.format(
        reply_language="French" if lang == "fr" else "English",
        rules_text=rules_text,
    )

    hist_result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conv.id)
        .order_by(Message.created_at.desc())
        .limit(HISTORY_LIMIT)
    )
    history = list(reversed(hist_result.scalars().all()))

    messages: list[dict] = [{"role": "system", "content": system_content}]
    for m in history:
        # tool role messages don't map cleanly to all providers — store as assistant
        role = m.role if m.role in ("user", "assistant") else "assistant"
        messages.append({"role": role, "content": m.content})

    user_content = message
    if context_block:
        user_content = f"{context_block}\n\nCustomer question: {message}"
    messages.append({"role": "user", "content": user_content})

    # Step 6: call LLM
    tool_defs = [t.definition() for t in TOOLS]
    llm_msg = await chat_complete(messages, tools=tool_defs)

    # Step 7: tool dispatch (at most one round-trip per message)
    final_reply: str
    if llm_msg.tool_calls:
        tc = llm_msg.tool_calls[0]
        tool_name = tc.function.name
        tool_params = json.loads(tc.function.arguments)

        tool = TOOL_MAP.get(tool_name)
        if tool:
            tool_result = await tool.call(tool_params)

            # Rebuild messages with assistant + tool result, re-call LLM
            messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tool_name, "arguments": tc.function.arguments},
                }],
            })
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(tool_result),
            })
            final_msg = await chat_complete(messages)
            final_reply = final_msg.content or ""

            db.add(Message(
                conversation_id=conv.id,
                role="tool",
                content=json.dumps(tool_result),
                tool_name=tool_name,
            ))
        else:
            final_reply = f"[Tool '{tool_name}' not available]"
    else:
        final_reply = llm_msg.content or ""

    # Step 8: persist user + assistant messages
    db.add(Message(conversation_id=conv.id, role="user", content=message))
    db.add(Message(conversation_id=conv.id, role="assistant", content=final_reply))
    await db.commit()

    return {"reply": final_reply, "language": lang}
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_orchestrator.py -v
# Expected: 3 passed
```

- [ ] **Step 5: Commit**

```bash
git add app/agent/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: agent orchestrator — 8-step pipeline (detect→rules→RAG→LLM→tools→persist)"
```

---

## Task 10: FastAPI app + chat endpoint

**Files:**
- Create: `app/main.py`
- Create: `app/api/chat.py`
- Create: `tests/test_chat_api.py`

**Interfaces:**
- Consumes: `run()` from `app.agent.orchestrator`; `get_db()` from `app.db.session`
- Produces:
  - `POST /api/chat` body: `{"message": str, "session_id": str}` → `{"reply": str, "language": str}`
  - `GET /chat` → HTML demo page

- [ ] **Step 1: Write the failing test**

```python
# tests/test_chat_api.py
import pytest
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


@patch("app.api.chat.run", new_callable=AsyncMock,
       return_value={"reply": "We sell 50W to 550W panels.", "language": "en"})
async def test_post_chat_returns_reply(mock_run, client):
    resp = await client.post("/api/chat", json={
        "message": "What panels do you sell?",
        "session_id": "test-session-1"
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["reply"] == "We sell 50W to 550W panels."
    assert data["language"] == "en"


@patch("app.api.chat.run", new_callable=AsyncMock,
       return_value={"reply": "Nous vendons des panneaux.", "language": "fr"})
async def test_post_chat_french(mock_run, client):
    resp = await client.post("/api/chat", json={
        "message": "Quels panneaux vendez-vous ?",
        "session_id": "test-session-2"
    })
    assert resp.status_code == 200
    assert resp.json()["language"] == "fr"


async def test_post_chat_missing_field(client):
    resp = await client.post("/api/chat", json={"session_id": "x"})
    assert resp.status_code == 422   # FastAPI validation error


async def test_get_chat_page(client):
    resp = await client.get("/chat")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_chat_api.py -v
# Expected: ImportError — app.main not found
```

- [ ] **Step 3: Write `app/api/chat.py`**

```python
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.agent.orchestrator import run

router = APIRouter()


class ChatRequest(BaseModel):
    message: str
    session_id: str


class ChatResponse(BaseModel):
    reply: str
    language: str


@router.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, db: AsyncSession = Depends(get_db)):
    result = await run(req.message, req.session_id, db)
    return ChatResponse(**result)
```

- [ ] **Step 4: Write `app/main.py`**

```python
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse

from app.api.chat import router as chat_router

app = FastAPI(title="Restar Solar AI Agent")

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

app.include_router(chat_router)


@app.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request):
    return templates.TemplateResponse("chat.html", {"request": request})


@app.get("/health")
async def health():
    return {"status": "ok"}
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_chat_api.py -v
# Expected: 4 passed
```

- [ ] **Step 6: Commit**

```bash
git add app/main.py app/api/chat.py tests/test_chat_api.py
git commit -m "feat: FastAPI app — POST /api/chat + GET /chat + health endpoint"
```

---

## Task 11: Chat page template + embeddable widget

**Files:**
- Create: `templates/chat.html`
- Create: `static/widget.js`

**Interfaces:**
- `templates/chat.html` — calls `POST /api/chat`, displays EN/FR toggle, shows reply
- `static/widget.js` — embeddable on any page with `<script src=".../static/widget.js" data-agent-url="..."></script>`

No unit tests for static files — verified by running the server and opening the browser.

- [ ] **Step 1: Create `templates/chat.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Restar Solar — AI Assistant</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <style>
    body { background: #0f172a; }
    #messages { scroll-behavior: smooth; }
    .bubble-user { background: #1e40af; }
    .bubble-agent { background: #1e293b; }
  </style>
</head>
<body class="min-h-screen flex flex-col items-center justify-center p-4">
  <div class="w-full max-w-lg bg-slate-900 rounded-2xl shadow-2xl overflow-hidden flex flex-col" style="height:90vh">

    <!-- Header -->
    <div class="bg-slate-800 px-4 py-3 flex items-center justify-between">
      <div class="flex items-center gap-2">
        <div class="w-2 h-2 rounded-full bg-green-400"></div>
        <span class="text-white font-semibold text-sm" id="headerTitle">Restar Solar Assistant</span>
      </div>
      <div class="flex gap-1">
        <button onclick="setLang('en')" id="btnEn"
          class="px-2 py-1 text-xs rounded font-mono font-bold bg-amber-400 text-slate-900">EN</button>
        <button onclick="setLang('fr')" id="btnFr"
          class="px-2 py-1 text-xs rounded font-mono font-bold text-slate-400">FR</button>
      </div>
    </div>

    <!-- Messages -->
    <div id="messages" class="flex-1 overflow-y-auto p-4 space-y-3">
      <div class="bubble-agent rounded-2xl rounded-tl-none px-4 py-3 text-slate-200 text-sm max-w-xs">
        <span id="welcomeMsg">Hello! I'm your Restar Solar assistant. How can I help you today?</span>
      </div>
    </div>

    <!-- Input -->
    <div class="bg-slate-800 p-3 flex gap-2">
      <input id="msgInput" type="text"
        placeholder="Ask about solar panels, prices, delivery…"
        class="flex-1 bg-slate-700 text-white rounded-xl px-4 py-2 text-sm outline-none focus:ring-2 focus:ring-amber-400"
        onkeydown="if(event.key==='Enter')sendMessage()">
      <button onclick="sendMessage()"
        class="bg-amber-400 text-slate-900 font-bold px-4 py-2 rounded-xl text-sm hover:bg-amber-300 transition">
        ➤
      </button>
    </div>
  </div>

<script>
  const SESSION_ID = crypto.randomUUID();
  let lang = 'en';

  const I18N = {
    en: { welcome: "Hello! I'm your Restar Solar assistant. How can I help you today?",
          placeholder: "Ask about solar panels, prices, delivery…",
          thinking: "Thinking…" },
    fr: { welcome: "Bonjour ! Je suis votre assistant Restar Solar. Comment puis-je vous aider ?",
          placeholder: "Posez vos questions sur les panneaux, prix, livraison…",
          thinking: "En train de réfléchir…" },
  };

  function setLang(l) {
    lang = l;
    document.getElementById('btnEn').className =
      l === 'en' ? 'px-2 py-1 text-xs rounded font-mono font-bold bg-amber-400 text-slate-900'
                 : 'px-2 py-1 text-xs rounded font-mono font-bold text-slate-400';
    document.getElementById('btnFr').className =
      l === 'fr' ? 'px-2 py-1 text-xs rounded font-mono font-bold bg-amber-400 text-slate-900'
                 : 'px-2 py-1 text-xs rounded font-mono font-bold text-slate-400';
    document.getElementById('welcomeMsg').textContent = I18N[l].welcome;
    document.getElementById('msgInput').placeholder = I18N[l].placeholder;
  }

  function addBubble(text, role) {
    const div = document.createElement('div');
    div.className = role === 'user'
      ? 'bubble-user rounded-2xl rounded-tr-none px-4 py-3 text-white text-sm max-w-xs ml-auto'
      : 'bubble-agent rounded-2xl rounded-tl-none px-4 py-3 text-slate-200 text-sm max-w-xs';
    div.textContent = text;
    document.getElementById('messages').appendChild(div);
    div.scrollIntoView({ behavior: 'smooth' });
    return div;
  }

  async function sendMessage() {
    const input = document.getElementById('msgInput');
    const text = input.value.trim();
    if (!text) return;
    input.value = '';
    addBubble(text, 'user');
    const thinking = addBubble(I18N[lang].thinking, 'agent');

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, session_id: SESSION_ID }),
      });
      const data = await res.json();
      thinking.textContent = data.reply;
      if (data.language !== lang) setLang(data.language);
    } catch (e) {
      thinking.textContent = '⚠️ Connection error. Please try again.';
    }
  }
</script>
</body>
</html>
```

- [ ] **Step 2: Create `static/widget.js`**

```javascript
/**
 * Restar Solar chat widget.
 * Usage: <script src="/static/widget.js" data-agent-url="https://your-server.com"></script>
 */
(function () {
  const script = document.currentScript;
  const BASE_URL = (script && script.getAttribute('data-agent-url')) || '';
  const SESSION_ID = ([1e7] + -1e3 + -4e3 + -8e3 + -1e11).replace(/[018]/g, c =>
    (c ^ (crypto.getRandomValues(new Uint8Array(1))[0] & (15 >> (c / 4)))).toString(16));

  const CSS = `
    #rs-widget-btn{position:fixed;bottom:24px;right:24px;width:56px;height:56px;
      border-radius:50%;background:#f59e0b;border:none;cursor:pointer;
      box-shadow:0 4px 20px rgba(0,0,0,.4);z-index:9999;font-size:24px}
    #rs-widget-box{position:fixed;bottom:92px;right:24px;width:340px;
      border-radius:16px;overflow:hidden;display:none;flex-direction:column;
      box-shadow:0 8px 40px rgba(0,0,0,.6);z-index:9999;
      background:#0f172a;font-family:system-ui,sans-serif;max-height:500px}
    #rs-widget-box.open{display:flex}
    #rs-whead{background:#1e293b;padding:12px 16px;display:flex;
      align-items:center;justify-content:space-between;color:#fff;font-size:14px;font-weight:600}
    #rs-wmsg{flex:1;overflow-y:auto;padding:12px;display:flex;flex-direction:column;gap:8px}
    .rs-b{padding:10px 14px;border-radius:14px;font-size:13px;line-height:1.5;max-width:80%}
    .rs-b-u{background:#1e40af;color:#fff;align-self:flex-end;border-radius:14px 14px 4px 14px}
    .rs-b-a{background:#1e293b;color:#e2e8f0;border-radius:14px 14px 14px 4px}
    #rs-winput{display:flex;gap:8px;padding:10px;background:#1e293b;border-top:1px solid #334155}
    #rs-winput input{flex:1;background:#0f172a;border:1px solid #334155;color:#fff;
      border-radius:8px;padding:8px 12px;font-size:13px;outline:none}
    #rs-winput button{background:#f59e0b;border:none;color:#000;font-weight:700;
      padding:8px 14px;border-radius:8px;cursor:pointer;font-size:13px}
  `;
  const style = document.createElement('style');
  style.textContent = CSS;
  document.head.appendChild(style);

  document.body.insertAdjacentHTML('beforeend', `
    <button id="rs-widget-btn" aria-label="Chat with Restar Solar">☀️</button>
    <div id="rs-widget-box">
      <div id="rs-whead">
        <span>Restar Solar Assistant</span>
        <button onclick="document.getElementById('rs-widget-box').classList.remove('open')"
          style="background:none;border:none;color:#94a3b8;cursor:pointer;font-size:18px">✕</button>
      </div>
      <div id="rs-wmsg">
        <div class="rs-b rs-b-a">Hello! Ask me about solar panels, prices, or delivery to Cameroon.</div>
      </div>
      <div id="rs-winput">
        <input id="rs-wi" type="text" placeholder="Type your question…">
        <button id="rs-wsend">➤</button>
      </div>
    </div>
  `);

  document.getElementById('rs-widget-btn').onclick = () =>
    document.getElementById('rs-widget-box').classList.toggle('open');

  async function send() {
    const input = document.getElementById('rs-wi');
    const text = input.value.trim();
    if (!text) return;
    input.value = '';

    const msgs = document.getElementById('rs-wmsg');
    const addBubble = (t, cls) => {
      const d = document.createElement('div');
      d.className = `rs-b ${cls}`;
      d.textContent = t;
      msgs.appendChild(d);
      msgs.scrollTop = msgs.scrollHeight;
      return d;
    };

    addBubble(text, 'rs-b-u');
    const thinking = addBubble('…', 'rs-b-a');

    try {
      const res = await fetch(`${BASE_URL}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, session_id: SESSION_ID }),
      });
      const data = await res.json();
      thinking.textContent = data.reply;
    } catch {
      thinking.textContent = '⚠️ Could not connect. Please try again.';
    }
  }

  document.getElementById('rs-wsend').onclick = send;
  document.getElementById('rs-wi').onkeydown = e => { if (e.key === 'Enter') send(); };
})();
```

- [ ] **Step 3: Start the server and verify manually**

```bash
uvicorn app.main:app --reload --port 8000
# Open: http://localhost:8000/chat
# Test:
# 1. Type "What solar panels do you sell?" → should get grounded answer
# 2. Type "Quels panneaux vendez-vous ?" → should reply in French
# 3. Type "Convert 200 CNY to XAF" → should trigger CurrencyTool
# 4. Type "What is the exact price of model X123?" → should refuse and offer ticket
```

- [ ] **Step 4: Commit**

```bash
git add templates/chat.html static/widget.js
git commit -m "feat: bilingual chat UI template + embeddable widget.js"
```

---

## Task 12: KB import CLI

**Files:**
- Create: `scripts/kb_import.py`
- Create: `tests/test_kb_import.py`

**Interfaces:**
- Consumes: `embed()` from `app.rag.embedder`; `upsert()` from `app.rag.retriever`
- Produces: `python scripts/kb_import.py <file_path>` — chunks + embeds + upserts the file into ChromaDB

- [ ] **Step 1: Write the failing test**

```python
# tests/test_kb_import.py
import tempfile
import pytest
from pathlib import Path
from app.rag import retriever
from app.rag.embedder import embed


@pytest.fixture(autouse=True)
def isolated_chroma(tmp_path, monkeypatch):
    monkeypatch.setenv("CHROMA_PATH", str(tmp_path / "chroma"))
    retriever._client = None
    retriever._collection = None
    yield
    retriever._client = None
    retriever._collection = None


def _run_import(path: Path):
    """Run kb_import as a module in the same process."""
    import importlib.util, sys
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
    # Write content long enough to produce at least 1 chunk
    txt.write_text("Restar Solar delivers across Cameroon. " * 30, encoding="utf-8")
    _run_import(txt)
    col = retriever._get_collection()
    results = col.get(include=["metadatas"])
    assert any(m["source_file"] == "info.txt" for m in results["metadatas"])
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_kb_import.py -v
# Expected: ImportError or AttributeError — scripts/kb_import.py not found
```

- [ ] **Step 3: Write `scripts/kb_import.py`**

```python
"""
Import a document into the Restar Solar knowledge base.

Usage:
    python scripts/kb_import.py path/to/file.pdf
    python scripts/kb_import.py path/to/prices.xlsx
    python scripts/kb_import.py path/to/page.html
    python scripts/kb_import.py path/to/notes.txt

Supported: .pdf  .xlsx  .html  .htm  .txt
"""
import sys
import os
import re
from pathlib import Path

# Ensure project root is on sys.path when run directly
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from app.rag.embedder import embed_batch
from app.rag.retriever import upsert

CHUNK_SIZE = 500    # approximate characters per chunk
CHUNK_OVERLAP = 80  # overlap between consecutive chunks


def extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        return "\n\n".join(page.extract_text() or "" for page in reader.pages)
    elif suffix == ".xlsx":
        from openpyxl import load_workbook
        wb = load_workbook(str(path), read_only=True, data_only=True)
        lines = []
        for ws in wb.worksheets:
            for row in ws.iter_rows(values_only=True):
                parts = [str(c) for c in row if c is not None]
                if parts:
                    lines.append("\t".join(parts))
        return "\n".join(lines)
    elif suffix in (".html", ".htm"):
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
        return soup.get_text(separator="\n")
    elif suffix == ".txt":
        return path.read_text(encoding="utf-8")
    else:
        raise ValueError(f"Unsupported file type: {suffix}")


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split text into overlapping chunks by character count."""
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    chunks, start = [], 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        # Try to break at a sentence boundary
        boundary = text.rfind(". ", start, end)
        if boundary != -1 and boundary > start + chunk_size // 2:
            end = boundary + 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = end - overlap
    return chunks


def main(file_path: str):
    path = Path(file_path).resolve()
    if not path.exists():
        print(f"Error: file not found: {path}", file=sys.stderr)
        sys.exit(1)

    print(f"Importing: {path.name}")
    text = extract_text(path)
    if not text.strip():
        print("Warning: no text extracted from file.")
        return

    chunks = chunk_text(text)
    print(f"  → {len(chunks)} chunks")

    embeddings = embed_batch(chunks)
    for i, (chunk, vec) in enumerate(zip(chunks, embeddings)):
        doc_id = f"{path.stem}_{i}"
        upsert(doc_id, chunk, vec, {
            "source_file": path.name,
            "language": "unknown",   # langdetect can be added here later
            "chunk_index": i,
        })

    print(f"✓ Imported {len(chunks)} chunks from {path.name} into ChromaDB")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/kb_import.py <file>", file=sys.stderr)
        sys.exit(1)
    main(sys.argv[1])
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_kb_import.py -v
# Expected: 2 passed
```

- [ ] **Step 5: Run the full test suite**

```bash
pytest -v
# Expected: all tests pass (across all 10 test files)
```

- [ ] **Step 6: Final end-to-end smoke test**

```bash
# In one terminal:
uvicorn app.main:app --reload --port 8000

# In another terminal — verify all 4 Phase 1 acceptance criteria:

# 1. English Q&A grounded in KB
curl -s -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"What solar panels do you sell?","session_id":"smoke-1"}' | python -m json.tool

# 2. French Q&A
curl -s -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"Quels panneaux solaires vendez-vous ?","session_id":"smoke-2"}' | python -m json.tool

# 3. Currency tool
curl -s -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"Convert 500 CNY to XAF","session_id":"smoke-3"}' | python -m json.tool

# 4. Hallucination refusal
curl -s -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"What is the exact price of model XYZ-9900?","session_id":"smoke-4"}' | python -m json.tool
```

- [ ] **Step 7: Commit**

```bash
git add scripts/kb_import.py tests/test_kb_import.py
git commit -m "feat: kb_import CLI — PDF/Excel/HTML/txt → chunk → embed → ChromaDB"
```

- [ ] **Step 8: Final commit — tag Phase 1 complete**

```bash
git tag -a v0.1.0 -m "Phase 1 complete: bilingual RAG agent with currency tool"
```

---

## Self-Review Checklist

- [x] **Spec §1 (Overview):** Phase 1 scope built — FastAPI + RAG + currency tool + bilingual widget ✓
- [x] **Spec §3 (Architecture):** All 4 layers present (Rule→RAG→LLM→Tool) in Task 9 ✓
- [x] **Spec §5 (Pipeline steps 1-8):** All 8 steps implemented in `orchestrator.py` ✓
- [x] **Spec §6 (Data models):** Conversation, Message, Rule in Task 2 ✓
- [x] **Spec §8 (Tools):** CurrencyTool with static fallback in Task 8 ✓
- [x] **Spec §10 (Anti-hallucination rules):** 3 rules seeded in Task 5 ✓
- [x] **Spec §11 (Sample FAQs):** 5 EN + 5 FR seeded in Task 5 ✓
- [x] **Spec §14 (Build order):** All 15 steps from spec covered across 12 tasks ✓
- [x] **Spec §15 (Test checklist):** Smoke tests in Task 12 Step 6 cover all 4 acceptance criteria ✓
- [x] **Python 3.12:** Task 1 installs via Homebrew ✓
- [x] **create_all() only:** No Alembic used anywhere ✓
- [x] **No hardcoded keys:** All secrets via `.env` / `python-dotenv` ✓
- [x] **LLM swappable:** `LLM_BASE_URL + LLM_MODEL` in `.env`, documented in `.env.example` ✓
- [x] **Offline-capable:** sentence-transformers local; ChromaDB in-process; Ollama swap documented ✓
