"""
One-time migration: recreate the `products` table with the extended 2026
catalog schema. Safe to run because the table is empty in production as of
this migration (0 rows) — verified before writing this script. Does not
touch conversations/messages/tickets/orders/rules/admin_users.

Run: python scripts/migrate_products_2026.py
"""
import asyncio
from sqlalchemy import text
from app.db.session import engine
from app.db.models import Base


async def migrate():
    async with engine.begin() as conn:
        result = await conn.execute(text("SELECT COUNT(*) FROM products"))
        count = result.scalar()
        if count and count > 0:
            raise RuntimeError(
                f"products table has {count} existing rows — refusing to drop. "
                "Back up and migrate manually."
            )
        await conn.execute(text("DROP TABLE IF EXISTS products"))
        await conn.run_sync(Base.metadata.create_all)
    print("products table recreated with 2026 catalog schema")


if __name__ == "__main__":
    asyncio.run(migrate())
