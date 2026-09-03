import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.main import app
from app.db.models import Base, AdminUser, Conversation, Order, Ticket, ProductImage
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


@pytest.fixture
async def agent_client():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        user = AdminUser(email="cs@test.com", password_hash=hash_password("pass"),
                         role="agent", country="NG")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        token = create_access_token({"sub": str(user.id), "role": user.role})

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
async def test_agent_can_use_inbox(agent_client):
    assert (await agent_client.get("/admin/inbox")).status_code == 200


@pytest.mark.asyncio
async def test_agent_blocked_from_management_pages(agent_client):
    for path in ("/admin/products", "/admin/orders", "/admin/tickets"):
        assert (await agent_client.get(path)).status_code == 403, path


@pytest.mark.asyncio
async def test_agent_dashboard_redirects_to_inbox(agent_client):
    resp = await agent_client.get("/admin/dashboard", follow_redirects=False)
    assert resp.status_code == 302 and resp.headers["location"] == "/admin/inbox"


@pytest.mark.asyncio
async def test_create_agent_user(authed_client):
    resp = await authed_client.post("/admin/users", data={
        "email": "ng-cs@restsolar.com", "password": "x", "role": "agent", "country": "NG",
    }, follow_redirects=False)
    assert resp.status_code == 302
    page = await authed_client.get("/admin/users")
    assert b"ng-cs@restsolar.com" in page.content and b"agent" in page.content


@pytest.mark.asyncio
async def test_create_agent_requires_country(authed_client):
    resp = await authed_client.post("/admin/users", data={
        "email": "bad@x.com", "password": "x", "role": "agent", "country": "",
    })
    assert resp.status_code == 400


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
            Order(order_number="NG-1", country="NG", customer_name="A",
                  items="2x RTM210M panel", contact="+234 800 111 2222"),
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


# --- Task 8: country-scoped products; Rules locked to superadmin -------------

@pytest.fixture
async def product_env(scoped_env):
    """scoped_env + one shared (NULL) and one NG product, created via the API."""
    import re
    client, su_tok, ng_tok, _ = scoped_env
    async with client(su_tok) as c:
        await c.post("/admin/products",
                     data={"name": "Shared panel", "sku": "SHARE-1", "country": ""},
                     follow_redirects=False)
        await c.post("/admin/products",
                     data={"name": "NG panel", "sku": "NGP-1", "country": "NG"},
                     follow_redirects=False)
        r = await c.get("/admin/products")
    ids = {sku: int(pid) for sku, pid in
           re.findall(r'font-mono text-xs">([^<]+)</td>.*?/admin/products/(\d+)/edit', r.text, re.S)}
    return client, su_tok, ng_tok, ids


@pytest.mark.asyncio
async def test_country_admin_product_list_shows_shared_and_own(product_env):
    client, su_tok, ng_tok, ids = product_env
    async with client(ng_tok) as c:
        r = await c.get("/admin/products")
    assert b"SHARE-1" in r.content and b"NGP-1" in r.content
    assert b"read-only" in r.content  # shared row not editable by NG


@pytest.mark.asyncio
async def test_country_admin_cannot_edit_shared_product(product_env):
    client, su_tok, ng_tok, ids = product_env
    async with client(ng_tok) as c:
        r = await c.post(f"/admin/products/{ids['SHARE-1']}/edit",
                         data={"name": "hacked", "sku": "SHARE-1"}, follow_redirects=False)
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_country_admin_create_forces_own_country(product_env):
    client, su_tok, ng_tok, ids = product_env
    async with client(ng_tok) as c:
        await c.post("/admin/products",
                     data={"name": "New NG", "sku": "NEWNG-1", "country": "ML"},
                     follow_redirects=False)
        r = await c.get("/admin/products")
    assert b"NEWNG-1" in r.content  # visible to NG => tagged NG, not ML


@pytest.mark.asyncio
async def test_country_admin_product_count_and_facets_scoped(scoped_env):
    """final-review fix #7a: total_count and the category facet list must be
    country-scoped, not a global count over every country's catalog."""
    client, su_tok, ng_tok, _ = scoped_env
    async with client(su_tok) as c:
        await c.post("/admin/products", data={
            "name": "Shared", "sku": "SH-CT", "country": "", "category": "solar_panels"})
        await c.post("/admin/products", data={
            "name": "NG one", "sku": "NG-CT", "country": "NG", "category": "inverters"})
        await c.post("/admin/products", data={
            "name": "ML one", "sku": "ML-CT", "country": "ML", "category": "batteries"})
    async with client(ng_tok) as c:
        r = await c.get("/admin/products")
    assert b"All (2)" in r.content                      # shared + NG, not ML
    assert b"?category=solar_panels" in r.content
    assert b"?category=inverters" in r.content
    assert b"?category=batteries" not in r.content      # ML-only category chip hidden


@pytest.mark.asyncio
async def test_country_admin_rules_forbidden(scoped_env):
    client, su_tok, ng_tok, _ = scoped_env
    async with client(ng_tok) as c:
        r = await c.get("/admin/rules", follow_redirects=False)
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_country_admin_sidebar_hides_rules(scoped_env):
    client, su_tok, ng_tok, _ = scoped_env
    async with client(ng_tok) as c:
        r = await c.get("/admin/dashboard")
    assert b'href="/admin/rules"' not in r.content
    assert b'href="/admin/users"' not in r.content


# --- final-review fix #2: Users page creates scoped, correctly-roled accounts ---

@pytest.fixture
async def su_env():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        su = AdminUser(email="su@x.c", password_hash=hash_password("p"), role="superadmin", country=None)
        s.add(su)
        await s.flush()
        tok = create_access_token({"sub": str(su.id), "role": "superadmin"})
        await s.commit()

    from app.db.session import get_db
    async def override_get_db():
        async with Session() as s:
            yield s
    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", cookies={"admin_token": tok}) as c:
        yield c, Session
    app.dependency_overrides.clear()
    await engine.dispose()


async def _user_by_email(Session, email):
    from sqlalchemy import select as _select
    async with Session() as s:
        return (await s.execute(_select(AdminUser).where(AdminUser.email == email))).scalar_one()


@pytest.mark.asyncio
async def test_create_country_admin_with_country(su_env):
    c, Session = su_env
    r = await c.post("/admin/users", data={
        "email": "ng2@x.c", "password": "p", "role": "country_admin", "country": "NG",
    }, follow_redirects=False)
    assert r.status_code == 302
    u = await _user_by_email(Session, "ng2@x.c")
    assert u.role == "country_admin" and u.country == "NG"


@pytest.mark.asyncio
async def test_create_country_admin_without_country_is_400(su_env):
    c, Session = su_env
    r = await c.post("/admin/users", data={
        "email": "bad@x.c", "password": "p", "role": "country_admin",
    }, follow_redirects=False)
    assert r.status_code == 400
    from sqlalchemy import select as _select
    async with Session() as s:
        assert (await s.execute(_select(AdminUser).where(AdminUser.email == "bad@x.c"))).scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_create_superadmin_forces_country_none(su_env):
    c, Session = su_env
    r = await c.post("/admin/users", data={
        "email": "su2@x.c", "password": "p", "role": "superadmin", "country": "NG",
    }, follow_redirects=False)
    assert r.status_code == 302
    u = await _user_by_email(Session, "su2@x.c")
    assert u.role == "superadmin" and u.country is None


# --- final-review fix #5: order status vocab + captured data visible ---

@pytest.mark.asyncio
async def test_update_order_status_rejects_invalid(scoped_env):
    client, su_tok, ng_tok, _ = scoped_env
    async with client(ng_tok) as c:
        r = await c.post("/admin/orders/1/status", data={"status": "confirmed"}, follow_redirects=False)
        assert r.status_code == 400
        page = await c.get("/admin/orders")
    assert b">pending<" in page.content  # NG-1 unchanged


@pytest.mark.asyncio
async def test_update_order_status_accepts_quoted(scoped_env):
    client, su_tok, ng_tok, _ = scoped_env
    async with client(ng_tok) as c:
        r = await c.post("/admin/orders/1/status", data={"status": "quoted"}, follow_redirects=False)
        assert r.status_code in (302, 303)
        page = await c.get("/admin/orders")
    assert b">quoted<" in page.content


@pytest.mark.asyncio
async def test_delete_product_image_404_when_parent_product_missing(su_env):
    """fix #7c: a dangling image whose product is gone must not skip the write-guard."""
    c, Session = su_env
    async with Session() as s:
        img = ProductImage(product_id=99999, path="", sort_order=0)
        s.add(img)
        await s.commit()
        await s.refresh(img)
        img_id = img.id
    r = await c.post(f"/admin/products/99999/images/{img_id}/delete", follow_redirects=False)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_orders_page_shows_contact_and_items(scoped_env):
    client, su_tok, ng_tok, _ = scoped_env
    async with client(ng_tok) as c:
        r = await c.get("/admin/orders")
    assert b"+234 800 111 2222" in r.content
    assert b"2x RTM210M panel" in r.content
