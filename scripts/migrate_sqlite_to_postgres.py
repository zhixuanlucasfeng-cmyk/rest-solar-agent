"""One-time data migration: copy every row from the local SQLite DB into a
fresh Postgres database, table by table, preserving primary keys so
foreign keys (messages -> conversations, product_images -> products, etc.)
stay correct.

Run: python3 scripts/migrate_sqlite_to_postgres.py "postgresql://user:pass@host/db"

Safe to re-run: skips tables that already have rows in the target DB.
"""
import asyncio
import sys

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from app.db.models import (
    Base, Conversation, Message, Rule, Product, ProductImage, Order, Ticket, AdminUser,
)

SQLITE_URL = "sqlite+aiosqlite:///./data/rest_solar.db"

# Order matters: parents before children (foreign key dependencies).
TABLES_IN_ORDER = [Conversation, Rule, Product, ProductImage, Order, Ticket, AdminUser, Message]


async def migrate(postgres_url: str) -> None:
    if postgres_url.startswith("postgres://"):
        postgres_url = "postgresql+asyncpg://" + postgres_url[len("postgres://"):]
    elif postgres_url.startswith("postgresql://"):
        postgres_url = "postgresql+asyncpg://" + postgres_url[len("postgresql://"):]

    sqlite_engine = create_async_engine(SQLITE_URL)
    pg_engine = create_async_engine(postgres_url)

    # The source sqlite file may predate a model added after it was last
    # touched by the running app (create_all only adds missing tables, so
    # this is a no-op for tables that already exist).
    async with sqlite_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with pg_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    SqliteSession = async_sessionmaker(sqlite_engine, expire_on_commit=False)
    PgSession = async_sessionmaker(pg_engine, expire_on_commit=False)

    async with SqliteSession() as src, PgSession() as dst:
        for model in TABLES_IN_ORDER:
            existing = await dst.scalar(select(func.count()).select_from(model))
            if existing:
                print(f"Skipping {model.__tablename__}: already has {existing} rows in target")
                continue

            rows = (await src.execute(select(model))).scalars().all()
            for row in rows:
                data = {c.name: getattr(row, c.name) for c in model.__table__.columns}
                dst.add(model(**data))
            await dst.commit()
            print(f"Copied {len(rows)} rows into {model.__tablename__}")

    await sqlite_engine.dispose()
    await pg_engine.dispose()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 scripts/migrate_sqlite_to_postgres.py <postgres_url>")
        sys.exit(1)
    asyncio.run(migrate(sys.argv[1]))
