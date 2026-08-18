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
async def test_products_full_fields_and_images(authed_client):
    from pathlib import Path
    created_files = [
        Path("static/product_images/INV-TEST-1.jpg"),
        Path("static/product_images/INV-TEST-1_1.jpg"),
        Path("static/product_images/INV-TEST-1_2.jpg"),
    ]

    resp = await authed_client.post(
        "/admin/products",
        data={
            "name": "Test Inverter", "sku": "INV-TEST-1", "category": "inverters",
            "subcategory": "hybrid", "model": "X1", "wattage": "5000W",
            "price_cny": "800", "price_xaf": "72000", "stock": "5", "featured": "true",
            "features": "MPPT\nWiFi monitoring",
        },
        files=[
            ("primary_image", ("main.jpg", b"fakeimgbytes", "image/jpeg")),
            ("gallery_images", ("g1.jpg", b"fakeimg1", "image/jpeg")),
            ("gallery_images", ("g2.jpg", b"fakeimg2", "image/jpeg")),
        ],
        follow_redirects=True,
    )
    try:
        assert resp.status_code == 200

        list_resp = await authed_client.get("/admin/products")
        assert b"INV-TEST-1" in list_resp.content
        assert b"+2 photos" in list_resp.content

        for f in created_files:
            assert f.exists(), f"expected {f} to have been saved"

        import re
        m = re.search(rb'/admin/products/(\d+)/edit"', list_resp.content)
        assert m, "could not find product id for INV-TEST-1"
        pid = m.group(1).decode()

        edit_page = await authed_client.get(f"/admin/products/{pid}/edit")
        assert edit_page.status_code == 200
        assert b"Test Inverter" in edit_page.content
        assert b"Gallery (2)" in edit_page.content

        update_resp = await authed_client.post(
            f"/admin/products/{pid}/edit",
            data={
                "name": "Test Inverter v2", "sku": "INV-TEST-1", "category": "inverters",
                "price_cny": "850", "price_xaf": "76000", "stock": "3",
            },
            follow_redirects=True,
        )
        assert update_resp.status_code == 200
        assert b"Test Inverter v2" in (await authed_client.get("/admin/products")).content

        edit_page2 = await authed_client.get(f"/admin/products/{pid}/edit")
        img_id_match = re.search(rb'/admin/products/\d+/images/(\d+)/delete', edit_page2.content)
        assert img_id_match
        img_id = img_id_match.group(1).decode()

        del_resp = await authed_client.post(
            f"/admin/products/{pid}/images/{img_id}/delete", follow_redirects=True
        )
        assert del_resp.status_code == 200
        edit_page3 = await authed_client.get(f"/admin/products/{pid}/edit")
        assert b"Gallery (1)" in edit_page3.content
    finally:
        for f in created_files:
            f.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_rules_crud(authed_client):
    resp = await authed_client.post("/admin/rules", data={
        "name": "Test Rule", "trigger": "test keyword", "body": "Test response", "priority": "10"
    }, follow_redirects=True)
    assert resp.status_code == 200
