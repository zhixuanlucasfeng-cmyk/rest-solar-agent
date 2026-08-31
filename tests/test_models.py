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


# Task 2 tests (append)
from sqlalchemy import select
from app.db.models import Conversation, ProductImage, MediaAsset


@pytest.mark.asyncio
async def test_country_columns_default_null(db):
    u = AdminUser(email="a@b.c", password_hash="x", role="superadmin")
    c = Conversation(session_id="s1", language="en")
    p = Product(name="Panel", sku="ZZ-1")
    db.add_all([u, c, p])
    await db.commit()
    assert u.country is None
    assert c.country is None
    assert p.country is None
    assert p.image_asset_id is None


@pytest.mark.asyncio
async def test_media_asset_roundtrips_bytes(db):
    m = MediaAsset(kind="image", content_type="image/jpeg", data=b"\xff\xd8\xff", filename="x.jpg")
    db.add(m)
    await db.commit()
    got = (await db.execute(select(MediaAsset).where(MediaAsset.id == m.id))).scalar_one()
    assert got.data == b"\xff\xd8\xff"
    assert got.content_type == "image/jpeg"


@pytest.mark.asyncio
async def test_order_has_country_and_new_fields(db):
    o = Order(
        order_number="NG-20260830-001", country="NG", customer_name="Ada",
        contact="+234...", items="2x ZZ-1", notes="urgent", total_xaf=None,
    )
    db.add(o)
    await db.commit()
    got = (await db.execute(select(Order).where(Order.order_number == "NG-20260830-001"))).scalar_one()
    assert got.country == "NG"
    assert got.status == "pending"
    assert got.items == "2x ZZ-1"
    assert got.conversation_id is None


@pytest.mark.asyncio
async def test_product_image_asset_id_nullable(db):
    p = Product(name="P", sku="ZZ-2")
    db.add(p)
    await db.flush()
    img = ProductImage(product_id=p.id, path="static/x.jpg", sort_order=0)
    db.add(img)
    await db.commit()
    assert img.asset_id is None
