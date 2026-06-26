import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.db.models import Base, Order
from app.tools.order import OrderTool


@pytest.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        session.add(Order(order_number="ORD-2024-001", customer_name="Marie Nguema", status="shipped"))
        await session.commit()
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_order_found(db_session):
    tool = OrderTool(db_session)
    result = await tool.call({"order_number": "ORD-2024-001"})
    assert result["order_number"] == "ORD-2024-001"
    assert result["status"] == "shipped"
    assert result["customer_name"] == "Marie Nguema"
    assert "created_at" in result


@pytest.mark.asyncio
async def test_order_not_found(db_session):
    tool = OrderTool(db_session)
    result = await tool.call({"order_number": "NONEXISTENT"})
    assert "error" in result


def test_definition():
    import asyncio
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async def _run():
        async with Session() as s:
            tool = OrderTool(s)
            defn = tool.definition()
            assert defn["function"]["name"] == "get_order_status"
    asyncio.run(_run())
