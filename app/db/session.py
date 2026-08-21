import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from dotenv import load_dotenv

load_dotenv()


def _normalize_database_url(url: str) -> str:
    """Render's Postgres connection strings come as plain postgres://
    or postgresql://, which psycopg2 understands but SQLAlchemy's async
    engine does not — it needs the asyncpg dialect spelled out."""
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url[len("postgresql://"):]
    return url


DATABASE_URL = _normalize_database_url(
    os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./data/rest_solar.db")
)

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db():
    """FastAPI dependency: yields an AsyncSession, commits on exit."""
    async with AsyncSessionLocal() as session:
        yield session
