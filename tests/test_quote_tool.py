import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.db.models import Base, Product
from app.tools.quote import QuoteTool


@pytest.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        session.add(Product(
            name="Solar Panel 400W", sku="SP-400",
            price_cny=1200.0, price_xaf=108000.0,
            duty_rate=0.30, vat_rate=0.1925,
            weight_kg=22.0, stock=10
        ))
        session.add(Product(
            name="RT8I-M 590-610W", sku="SP-012",
            duty_rate=0.30, vat_rate=0.1925, weight_kg=25.0, stock=0,
            # price_cny left unset (None) — the real state of all 169
            # catalog products right now, no China ex-factory cost entered.
        ))
        await session.commit()
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_quote_known_sku(db_session):
    tool = QuoteTool(db_session)
    result = await tool.call({"sku": "SP-400", "quantity": 2})
    assert result["sku"] == "SP-400"
    assert result["quantity"] == 2
    assert result["subtotal_cny"] == pytest.approx(2400.0)
    assert result["duty_cny"] == pytest.approx(720.0)       # 2400 * 0.30
    assert result["vat_cny"] == pytest.approx(462.0)        # 2400 * 0.1925
    assert result["shipping_cny"] == pytest.approx(968.0)   # 22kg * 2 * 22 CNY/kg
    assert "total_cny" in result
    assert "total_xaf" in result


@pytest.mark.asyncio
async def test_quote_unknown_sku(db_session):
    tool = QuoteTool(db_session)
    result = await tool.call({"sku": "UNKNOWN", "quantity": 1})
    assert "error" in result


@pytest.mark.asyncio
async def test_quote_product_with_no_price_cny_returns_error_not_crash(db_session):
    """Live-incident regression: get_quote crashed with
    "TypeError: unsupported operand type(s) for *: 'NoneType' and 'int'"
    (500ing /api/chat) whenever the LLM called it for a product whose
    price_cny is unset — the null-check used to run after the multiplication
    that needed it, and only checked `== 0`, never `is None`."""
    tool = QuoteTool(db_session)
    result = await tool.call({"sku": "SP-012", "quantity": 1})
    assert "error" in result
    assert "total_cny" not in result


def test_definition():
    import asyncio
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async def _run():
        async with Session() as s:
            tool = QuoteTool(s)
            defn = tool.definition()
            assert defn["type"] == "function"
            assert defn["function"]["name"] == "get_quote"
            assert "sku" in defn["function"]["parameters"]["properties"]
            assert "quantity" in defn["function"]["parameters"]["properties"]
    asyncio.run(_run())
