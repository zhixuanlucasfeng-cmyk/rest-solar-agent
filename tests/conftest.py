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
