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


# --- Task 9: create_order tool ---

from sqlalchemy import select as _select
from app.db.models import Conversation
from app.tools.order import CreateOrderTool, next_order_number


@pytest.mark.asyncio
async def test_create_order_inherits_conversation_country(db):
    conv = Conversation(session_id="s-sd", language="en", country="SD")
    db.add(conv)
    await db.flush()

    tool = CreateOrderTool(db, conv)
    result = await tool.call({
        "customer_name": "Omar", "contact": "+249...", "items": "2x INV-1", "notes": "roof job",
    })
    await db.commit()

    order = (await db.execute(_select(Order))).scalars().one()
    assert order.country == "SD"
    assert order.conversation_id == conv.id
    assert order.status == "pending"
    assert order.order_number.startswith("SD-")
    assert result["order_number"] == order.order_number
    assert "confirmation" in result


@pytest.mark.asyncio
async def test_next_order_number_increments_per_country_per_day(db):
    conv = Conversation(session_id="s", language="en", country="NG")
    db.add(conv)
    await db.flush()
    n1 = await next_order_number(db, "NG")
    db.add(Order(order_number=n1, country="NG", items=""))
    await db.flush()
    n2 = await next_order_number(db, "NG")
    assert n1.endswith("-001")
    assert n2.endswith("-002")
    assert n1.startswith("NG-")


@pytest.mark.asyncio
async def test_create_order_defaults_country_when_no_conversation(db):
    tool = CreateOrderTool(db, None)
    result = await tool.call({"customer_name": "A", "contact": "x", "items": "1x BAT"})
    await db.commit()
    order = (await db.execute(_select(Order))).scalars().one()
    assert order.country == "CM"
    assert order.conversation_id is None
    assert result["order_number"].startswith("CM-")


def test_create_order_tool_in_definition():
    from app.tools import get_tools
    names = {t.name for t in get_tools(db=None, conversation=None)}
    assert "create_order" in names
