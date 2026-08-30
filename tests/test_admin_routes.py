import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.main import app
from app.db.models import Base, AdminUser, Conversation, Order, Ticket
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
    assert resp.status_code == 200

    list_resp = await authed_client.get("/admin/products")
    assert b"INV-TEST-1" in list_resp.content
    assert b"+2 photos" in list_resp.content

    import re
    # Uploads are now stored as DB blobs served via /media/{id}, not files on disk.
    media_match = re.search(rb'src="(/media/\d+)"', list_resp.content)
    assert media_match, "expected primary image served from /media/{id}"
    media_resp = await authed_client.get(media_match.group(1).decode())
    assert media_resp.status_code == 200
    assert media_resp.content == b"fakeimgbytes"

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


@pytest.mark.asyncio
async def test_rules_crud(authed_client):
    resp = await authed_client.post("/admin/rules", data={
        "name": "Test Rule", "trigger": "test keyword", "body": "Test response", "priority": "10"
    }, follow_redirects=True)
    assert resp.status_code == 200


# --- Task 7: country-scoped conversations / orders / tickets / dashboard ---

@pytest.fixture
async def scoped_env():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        su = AdminUser(email="su@x.c", password_hash=hash_password("p"), role="superadmin", country=None)
        ng = AdminUser(email="ng@x.c", password_hash=hash_password("p"), role="country_admin", country="NG")
        s.add_all([su, ng])
        await s.flush()
        c_ng = Conversation(session_id="c-ng", language="en", country="NG")
        c_ml = Conversation(session_id="c-ml", language="en", country="ML")
        s.add_all([c_ng, c_ml])
        await s.flush()
        s.add_all([
            Order(order_number="NG-1", country="NG", customer_name="A", items=""),
            Order(order_number="ML-1", country="ML", customer_name="B", items=""),
            Ticket(conversation_id=c_ng.id, subject="ng t", body="x", status="open"),
            Ticket(conversation_id=c_ml.id, subject="ml t", body="x", status="open"),
            Ticket(conversation_id=None, subject="orphan t", body="x", status="open"),
        ])
        await s.commit()
        su_tok = create_access_token({"sub": str(su.id), "role": "superadmin"})
        ng_tok = create_access_token({"sub": str(ng.id), "role": "country_admin"})
        ml_conv_id = c_ml.id  # a conversation NOT visible to NG

    from app.db.session import get_db
    async def override_get_db():
        async with Session() as s:
            yield s
    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)

    def client(tok):
        return AsyncClient(transport=transport, base_url="http://test", cookies={"admin_token": tok})

    yield client, su_tok, ng_tok, ml_conv_id
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_country_admin_sees_only_own_orders(scoped_env):
    client, su_tok, ng_tok, _ = scoped_env
    async with client(ng_tok) as c:
        r = await c.get("/admin/orders")
    assert b"NG-1" in r.content and b"ML-1" not in r.content


@pytest.mark.asyncio
async def test_superadmin_sees_all_orders(scoped_env):
    client, su_tok, ng_tok, _ = scoped_env
    async with client(su_tok) as c:
        r = await c.get("/admin/orders")
    assert b"NG-1" in r.content and b"ML-1" in r.content


@pytest.mark.asyncio
async def test_country_admin_sees_only_own_conversations(scoped_env):
    client, su_tok, ng_tok, _ = scoped_env
    async with client(ng_tok) as c:
        r = await c.get("/admin/conversations")
    assert b"c-ng" in r.content and b"c-ml" not in r.content


@pytest.mark.asyncio
async def test_country_admin_conversation_detail_cross_country_404(scoped_env):
    client, su_tok, ng_tok, ml_conv_id = scoped_env
    async with client(ng_tok) as c:
        r = await c.get(f"/admin/conversations/{ml_conv_id}")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_superadmin_conversation_detail_ok(scoped_env):
    client, su_tok, ng_tok, ml_conv_id = scoped_env
    async with client(su_tok) as c:
        r = await c.get(f"/admin/conversations/{ml_conv_id}")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_country_admin_tickets_scoped(scoped_env):
    client, su_tok, ng_tok, _ = scoped_env
    async with client(ng_tok) as c:
        r = await c.get("/admin/tickets")
    assert b"ng t" in r.content
    assert b"ml t" not in r.content
    assert b"orphan t" not in r.content


@pytest.mark.asyncio
async def test_superadmin_tickets_all(scoped_env):
    client, su_tok, ng_tok, _ = scoped_env
    async with client(su_tok) as c:
        r = await c.get("/admin/tickets")
    assert b"ng t" in r.content and b"ml t" in r.content and b"orphan t" in r.content


@pytest.mark.asyncio
async def test_country_admin_close_cross_country_ticket_404(scoped_env):
    client, su_tok, ng_tok, _ = scoped_env
    # ticket 2 is the ML ticket
    async with client(ng_tok) as c:
        list_r = await c.get("/admin/tickets")
        r = await c.post("/admin/tickets/2/close", follow_redirects=False)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_country_admin_update_cross_country_order_404(scoped_env):
    client, su_tok, ng_tok, _ = scoped_env
    async with client(ng_tok) as c:
        r = await c.post("/admin/orders/2/status", data={"status": "shipped"}, follow_redirects=False)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_country_admin_dashboard_scoped_counts(scoped_env):
    client, su_tok, ng_tok, _ = scoped_env
    async with client(ng_tok) as c:
        r = await c.get("/admin/dashboard")
    assert r.status_code == 200
    assert b'text-blue-800">1</div>' in r.content   # 1 conversation for NG
    assert b'text-orange-500">1</div>' in r.content  # 1 open ticket for NG


@pytest.mark.asyncio
async def test_superadmin_dashboard_counts_all(scoped_env):
    client, su_tok, ng_tok, _ = scoped_env
    async with client(su_tok) as c:
        r = await c.get("/admin/dashboard")
    assert r.status_code == 200
    assert b'text-blue-800">2</div>' in r.content    # 2 conversations
    assert b'text-orange-500">3</div>' in r.content  # 3 open tickets
