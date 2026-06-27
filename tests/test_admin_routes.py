import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.main import app
from app.db.models import Base, AdminUser
from app.admin.auth import hash_password, create_access_token


@pytest.fixture
async def authed_client():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        user = AdminUser(email="admin@test.com", password_hash=hash_password("pass"), role="superadmin")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        token = create_access_token({"sub": str(user.id), "role": user.role})

    # Override the DB dependency to use the in-memory DB
    from app.db.session import get_db
    async def override_get_db():
        async with Session() as s:
            yield s
    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test",
                           cookies={"admin_token": token}) as client:
        yield client

    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_dashboard_requires_auth():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/admin/dashboard", follow_redirects=False)
    assert resp.status_code in (302, 303)


@pytest.mark.asyncio
async def test_dashboard_with_auth(authed_client):
    resp = await authed_client.get("/admin/dashboard")
    assert resp.status_code == 200
    assert b"Dashboard" in resp.content


@pytest.mark.asyncio
async def test_conversations_page(authed_client):
    resp = await authed_client.get("/admin/conversations")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_products_crud(authed_client):
    resp = await authed_client.post("/admin/products", data={
        "name": "Solar Panel 400W", "sku": "SP-400",
        "price_cny": "1200", "price_xaf": "108000",
        "duty_rate": "0.30", "vat_rate": "0.1925",
        "weight_kg": "22", "stock": "10",
    }, follow_redirects=True)
    assert resp.status_code == 200

    resp2 = await authed_client.get("/admin/products")
    assert b"SP-400" in resp2.content


@pytest.mark.asyncio
async def test_rules_crud(authed_client):
    resp = await authed_client.post("/admin/rules", data={
        "name": "Test Rule", "trigger": "test keyword", "body": "Test response", "priority": "10"
    }, follow_redirects=True)
    assert resp.status_code == 200
