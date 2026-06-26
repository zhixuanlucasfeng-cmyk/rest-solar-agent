import pytest
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.db.models import Base, Product, Order, Ticket, AdminUser


@pytest.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.mark.asyncio
async def test_product_model(engine):
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        p = Product(name="Solar Panel 400W", sku="SP-400", price_cny=1200.0, price_xaf=108000.0, weight_kg=22.0, stock=50)
        s.add(p)
        await s.commit()
        await s.refresh(p)
    assert p.id is not None
    assert p.duty_rate == 0.30
    assert p.vat_rate == 0.1925


@pytest.mark.asyncio
async def test_order_model(engine):
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        o = Order(order_number="ORD-001", customer_name="Jean Dupont")
        s.add(o)
        await s.commit()
        await s.refresh(o)
    assert o.id is not None
    assert o.status == "pending"


@pytest.mark.asyncio
async def test_ticket_model(engine):
    from app.db.models import Conversation
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        conv = Conversation(session_id="test-sess", language="fr")
        s.add(conv)
        await s.flush()
        t = Ticket(conversation_id=conv.id, subject="Issue", body="Details here")
        s.add(t)
        await s.commit()
        await s.refresh(t)
    assert t.id is not None
    assert t.status == "open"


@pytest.mark.asyncio
async def test_admin_user_model(engine):
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        u = AdminUser(email="admin@test.com", password_hash="hashed", role="superadmin")
        s.add(u)
        await s.commit()
        await s.refresh(u)
    assert u.id is not None
    assert u.role == "superadmin"
