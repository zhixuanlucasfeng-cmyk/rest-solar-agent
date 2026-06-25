import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy import select
from app.db.models import Base, Rule
from app.rag import retriever


@pytest.fixture
async def seed_env(tmp_path, monkeypatch):
    db_url = f"sqlite+aiosqlite:///{tmp_path}/test.db"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("CHROMA_PATH", str(tmp_path / "chroma"))
    retriever._client = None
    retriever._collection = None

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
    assert col.count() == 10
