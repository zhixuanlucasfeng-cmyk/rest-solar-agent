import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.main import app
from app.db.models import Base, AdminUser, Conversation, Order, Ticket, Product, ProductImage
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


@pytest.fixture
async def product_lifecycle_env():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        su = AdminUser(email="su-products@test.com", password_hash=hash_password("p"), role="superadmin")
        ng = AdminUser(email="ng-products@test.com", password_hash=hash_password("p"), role="country_admin", country="NG")
        s.add_all([su, ng])
        await s.flush()
        s.add_all([
            Product(name="Shared", sku="SHARED-LIFE", country=None, status="active"),
            Product(name="Nigeria", sku="NG-LIFE", country="NG", status="active", price_local=100, stock=3),
            Product(name="Cameroon", sku="CM-LIFE", country="CM", status="active"),
        ])
        await s.commit()
        su_token = create_access_token({"sub": str(su.id), "role": su.role})
        ng_token = create_access_token({"sub": str(ng.id), "role": ng.role})

    from app.db.session import get_db
    async def override_get_db():
        async with Session() as s:
            yield s
    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)

    def client(token):
        return AsyncClient(transport=transport, base_url="http://test", cookies={"admin_token": token})

    yield client, su_token, ng_token, Session
    app.dependency_overrides.clear()
    await engine.dispose()


async def _product_by_sku(Session, sku):
    from sqlalchemy import select
    async with Session() as s:
        return await s.scalar(select(Product).where(Product.sku == sku))


@pytest.mark.asyncio
async def test_country_admin_creates_product_in_own_country(product_lifecycle_env):
    client, _, ng_token, Session = product_lifecycle_env
    async with client(ng_token) as c:
        response = await c.post("/admin/products", data={
            "name": "New Nigerian panel", "sku": "NG-NEW", "country": "CM",
            "price_local": "12000", "price_cny": "500", "stock": "8",
        }, follow_redirects=False)
    assert response.status_code == 302
    product = await _product_by_sku(Session, "NG-NEW")
    assert (product.country, product.price_local, product.price_cny, product.stock, product.status) == (
        "NG", 12000, 500, 8, "active",
    )


@pytest.mark.asyncio
async def test_country_admin_edits_own_product_and_image(product_lifecycle_env):
    client, _, ng_token, Session = product_lifecycle_env
    product = await _product_by_sku(Session, "NG-LIFE")
    async with client(ng_token) as c:
        response = await c.post(f"/admin/products/{product.id}/edit", data={
            "name": "Nigeria updated", "sku": "NG-LIFE", "country": "CM",
            "price_local": "250", "stock": "11",
        }, files={"primary_image": ("panel.jpg", b"new-image", "image/jpeg")}, follow_redirects=False)
    assert response.status_code == 302
    updated = await _product_by_sku(Session, "NG-LIFE")
    assert (updated.name, updated.country, updated.price_local, updated.stock) == (
        "Nigeria updated", "NG", 250, 11,
    )
    assert updated.image_asset_id is not None
    async with client(ng_token) as c:
        image = await c.get(f"/media/{updated.image_asset_id}")
    assert image.status_code == 200 and image.content == b"new-image"


@pytest.mark.asyncio
@pytest.mark.parametrize("initial_status", ("inactive", "archived"))
async def test_legacy_edit_preserves_omitted_local_price_and_status(product_lifecycle_env, initial_status):
    client, _, ng_token, Session = product_lifecycle_env
    product = await _product_by_sku(Session, "NG-LIFE")
    async with client(ng_token) as c:
        changed = await c.post(f"/admin/products/{product.id}/status", data={"status": initial_status})
        assert changed.status_code == 302
        edited = await c.post(f"/admin/products/{product.id}/edit", data={
            "name": "Legacy form edit", "sku": "NG-LIFE", "price_cny": "90", "stock": "7",
        }, follow_redirects=False)
    assert edited.status_code == 302
    updated = await _product_by_sku(Session, "NG-LIFE")
    assert (updated.name, updated.price_local, updated.price_cny, updated.stock, updated.status) == (
        "Legacy form edit", 100, 90, 7, initial_status,
    )


@pytest.mark.asyncio
async def test_edit_explicit_empty_local_price_clears_and_status_can_change(product_lifecycle_env):
    client, _, ng_token, Session = product_lifecycle_env
    product = await _product_by_sku(Session, "NG-LIFE")
    async with client(ng_token) as c:
        assert (await c.post(f"/admin/products/{product.id}/status", data={"status": "inactive"})).status_code == 302
        cleared = await c.post(f"/admin/products/{product.id}/edit", data={
            "name": "No local price", "sku": "NG-LIFE", "price_local": "",
        }, follow_redirects=False)
        assert cleared.status_code == 302
        current = await _product_by_sku(Session, "NG-LIFE")
        assert (current.price_local, current.status) == (None, "inactive")
        changed = await c.post(f"/admin/products/{product.id}/edit", data={
            "name": "Reactivated", "sku": "NG-LIFE", "status": "active",
        }, follow_redirects=False)
        assert changed.status_code == 302
        invalid = await c.post(f"/admin/products/{product.id}/edit", data={
            "name": "Invalid", "sku": "NG-LIFE", "status": "retired",
        }, follow_redirects=False)
        empty = await c.post(f"/admin/products/{product.id}/edit", data={
            "name": "Empty status", "sku": "NG-LIFE", "status": "",
        }, follow_redirects=False)
    assert invalid.status_code == 400
    assert empty.status_code == 400
    final = await _product_by_sku(Session, "NG-LIFE")
    assert (final.name, final.price_local, final.status) == ("Reactivated", None, "active")


@pytest.mark.asyncio
async def test_country_admin_product_status_lifecycle_and_list_filter(product_lifecycle_env):
    client, _, ng_token, Session = product_lifecycle_env
    product = await _product_by_sku(Session, "NG-LIFE")
    async with client(ng_token) as c:
        for status in ("inactive", "archived", "active"):
            response = await c.post(f"/admin/products/{product.id}/status", data={"status": status}, follow_redirects=False)
            assert response.status_code == 302
            assert response.headers["location"] == f"/admin/products?status={status}"
            assert (await _product_by_sku(Session, "NG-LIFE")).status == status
            selected = await c.get(f"/admin/products?status={status}")
            assert b"NG-LIFE" in selected.content
            other = "active" if status != "active" else "archived"
            unselected = await c.get(f"/admin/products?status={other}")
            assert b"NG-LIFE" not in unselected.content


@pytest.mark.asyncio
async def test_product_form_rejects_invalid_values_without_persisting(product_lifecycle_env):
    client, _, ng_token, Session = product_lifecycle_env
    product = await _product_by_sku(Session, "NG-LIFE")
    async with client(ng_token) as c:
        for field, value in (("price_local", "-1"), ("stock", "-1"), ("status", "unknown")):
            response = await c.post("/admin/products", data={
                "name": "Bad", "sku": f"BAD-{field.upper()}", field: value,
            }, follow_redirects=False)
            assert response.status_code == 400
            assert await _product_by_sku(Session, f"BAD-{field.upper()}") is None
            response = await c.post(f"/admin/products/{product.id}/edit", data={
                "name": "Bad edit", "sku": "NG-LIFE", field: value,
            }, follow_redirects=False)
            assert response.status_code == 400
            unchanged = await _product_by_sku(Session, "NG-LIFE")
            assert (unchanged.name, unchanged.price_local, unchanged.stock, unchanged.status) == (
                "Nigeria", 100, 3, "active",
            )


@pytest.mark.asyncio
async def test_superadmin_product_country_validation_and_permanent_delete(product_lifecycle_env):
    client, su_token, _, Session = product_lifecycle_env
    async with client(su_token) as c:
        invalid = await c.post("/admin/products", data={
            "name": "Invalid country", "sku": "BAD-COUNTRY", "country": "ZZ",
        }, follow_redirects=False)
        assert invalid.status_code == 400
        assert await _product_by_sku(Session, "BAD-COUNTRY") is None
        normalized = await c.post("/admin/products", data={
            "name": "Country valid", "sku": "VALID-COUNTRY", "country": " ng ",
        }, follow_redirects=False)
        assert normalized.status_code == 302
        product = await _product_by_sku(Session, "VALID-COUNTRY")
        assert product.country == "NG"
        blank = await c.post("/admin/products", data={
            "name": "Shared blank", "sku": "BLANK-COUNTRY", "country": "  ",
        }, follow_redirects=False)
        assert blank.status_code == 302
        assert (await _product_by_sku(Session, "BLANK-COUNTRY")).country is None
        invalid_edit = await c.post(f"/admin/products/{product.id}/edit", data={
            "name": "Country valid", "sku": "VALID-COUNTRY", "country": "ZZ",
        }, follow_redirects=False)
        assert invalid_edit.status_code == 400
        assert (await _product_by_sku(Session, "VALID-COUNTRY")).country == "NG"
        missing = await c.post("/admin/products/99999/delete", follow_redirects=False)
        assert missing.status_code == 404
        deleted = await c.post(f"/admin/products/{product.id}/delete", follow_redirects=False)
        assert deleted.status_code == 302
        assert await _product_by_sku(Session, "VALID-COUNTRY") is None


@pytest.mark.asyncio
async def test_product_status_and_list_reject_invalid_values(product_lifecycle_env):
    client, _, ng_token, Session = product_lifecycle_env
    product = await _product_by_sku(Session, "NG-LIFE")
    async with client(ng_token) as c:
        invalid_status = await c.post(f"/admin/products/{product.id}/status", data={"status": "retired"})
        invalid_filter = await c.get("/admin/products?status=retired")
        missing = await c.post("/admin/products/99999/status", data={"status": "inactive"})
    assert (invalid_status.status_code, invalid_filter.status_code, missing.status_code) == (400, 400, 404)
    assert (await _product_by_sku(Session, "NG-LIFE")).status == "active"


@pytest.mark.asyncio
async def test_country_product_page_shows_local_price_status_tabs_and_safe_actions(product_env):
    import re

    client, _, ng_token, ids = product_env
    async with client(ng_token) as c:
        active = await c.get("/admin/products")
        assert active.status_code == 200
        assert re.search(r'<label[^>]*for="price_local"[^>]*>[^<]*NGN', active.text)
        assert 'name="price_local"' in active.text
        assert all(f'status={state}' in active.text for state in ("active", "inactive", "archived"))
        assert f'/admin/products/{ids["NGP-1"]}/status' in active.text
        assert re.search(r'name="status" value="inactive"[^>]*>\s*Unpublish', active.text)
        assert f'/admin/products/{ids["SHARE-1"]}/status' not in active.text
        assert f'/admin/products/{ids["SHARE-1"]}/edit' not in active.text
        assert '/delete"' not in active.text

        assert (await c.post(f'/admin/products/{ids["NGP-1"]}/status', data={"status": "inactive"})).status_code == 302
        inactive = await c.get("/admin/products?status=inactive")
        assert re.search(r'name="status" value="archived"[^>]*>\s*Archive', inactive.text)
        assert 'Inactive' in inactive.text
        assert '/delete"' not in inactive.text

        assert (await c.post(f'/admin/products/{ids["NGP-1"]}/status', data={"status": "archived"})).status_code == 302
        archived = await c.get("/admin/products?status=archived")
        assert re.search(r'name="status" value="active"[^>]*>\s*Restore', archived.text)
        assert 'Archived' in archived.text
        assert '/delete"' not in archived.text


@pytest.mark.asyncio
async def test_product_status_tabs_preserve_category_filter(product_lifecycle_env):
    client, _, ng_token, _ = product_lifecycle_env
    async with client(ng_token) as c:
        response = await c.get("/admin/products?category=solar_panels&status=active")
    assert response.status_code == 200
    assert 'href="/admin/products?category=solar_panels&amp;status=inactive"' in response.text


@pytest.mark.asyncio
async def test_country_product_edit_shows_local_price_and_status(product_env):
    import re

    client, _, ng_token, ids = product_env
    async with client(ng_token) as c:
        response = await c.get(f'/admin/products/{ids["NGP-1"]}/edit')
    assert response.status_code == 200
    assert re.search(r'<label[^>]*for="price_local"[^>]*>[^<]*NGN', response.text)
    assert 'name="price_local"' in response.text
    assert 'name="price_cny"' in response.text
    assert re.search(r'<select[^>]*name="status"[^>]*>.*?<option value="active" selected', response.text, re.S)
    assert 'name="datasheet"' in response.text
    assert 'name="primary_image"' in response.text
    assert 'name="gallery_images"' in response.text


@pytest.mark.asyncio
async def test_superadmin_product_page_keeps_permanent_delete_and_generic_shared_price(product_env):
    client, su_token, _, ids = product_env
    async with client(su_token) as c:
        listing = await c.get("/admin/products")
        edit = await c.get(f'/admin/products/{ids["SHARE-1"]}/edit')
    assert listing.status_code == edit.status_code == 200
    assert f'/admin/products/{ids["SHARE-1"]}/delete' in listing.text
    assert 'Delete permanently' in listing.text
    assert f'action="/admin/products/{ids["SHARE-1"]}/delete" method="post" data-delete-product="Shared panel (SHARE-1)"' in listing.text
    assert "dataset.deleteProduct" in listing.text
    assert "addEventListener('submit'" in listing.text
    assert "window.confirm(" in listing.text
    assert "event.preventDefault()" in listing.text
    assert 'Local price' in edit.text
    assert 'name="price_local"' in edit.text


@pytest.mark.asyncio
async def test_superadmin_delete_confirmation_escapes_product_label(product_lifecycle_env):
    import html
    import re
    from sqlalchemy import select

    client, su_token, ng_token, Session = product_lifecycle_env
    hostile_name = 'Panel "><img src=x onerror=alert(1)>'
    async with Session() as session:
        product = await session.scalar(select(Product).where(Product.sku == "NG-LIFE"))
        product.name = hostile_name
        await session.commit()

    async with client(su_token) as c:
        listing = await c.get("/admin/products")
    assert listing.status_code == 200
    forms = re.findall(r'<form action="/admin/products/\d+/delete" method="post" data-delete-product="([^"]+)">', listing.text)
    assert forms
    assert f"{hostile_name} (NG-LIFE)" in [html.unescape(label) for label in forms]
    assert 'onsubmit=' not in listing.text

    async with client(ng_token) as c:
        country_listing = await c.get("/admin/products")
    assert re.search(r'<form action="/admin/products/\d+/delete"', country_listing.text) is None


@pytest.mark.asyncio
async def test_product_list_uses_only_local_price_after_clearing(su_env):
    import re

    c, Session = su_env
    async with Session() as session:
        product = Product(name="Cleared Cameroon", sku="CLEARED-CM", country="CM",
                          price_local=130000, price_xaf=125000, price_cny=700)
        session.add(product)
        await session.commit()
        product_id = product.id
    response = await c.post(f"/admin/products/{product_id}/edit", data={
        "name": "Cleared Cameroon", "sku": "CLEARED-CM", "price_local": "",
        "price_xaf": "125000", "price_cny": "700",
    })
    assert response.status_code == 302
    listing = await c.get("/admin/products")
    row = next(row for row in re.findall(r"<tr.*?</tr>", listing.text, re.S) if "CLEARED-CM" in row)
    assert "On request" in row
    assert "125000" not in row and "700.00" not in row


@pytest.mark.asyncio
@pytest.mark.parametrize("price", ["0", "125000"])
async def test_new_shared_product_rejects_a_local_price(su_env, price):
    c, Session = su_env
    response = await c.post("/admin/products", data={
        "name": "Invalid shared price", "sku": "SHARED-PRICE", "country": "",
        "price_local": price,
    })
    assert response.status_code == 400
    assert await _product_by_sku(Session, "SHARED-PRICE") is None


@pytest.mark.asyncio
async def test_editing_shared_product_clears_legacy_local_price(su_env):
    import re

    c, Session = su_env
    async with Session() as session:
        product = Product(name="Shared price", sku="SHARED-PRICE", country=None, price_local=125000)
        session.add(product)
        await session.commit()
        product_id = product.id
    listing = await c.get("/admin/products")
    row = next(row for row in re.findall(r"<tr.*?</tr>", listing.text, re.S) if "SHARED-PRICE" in row)
    assert "On request" in row and "125000" not in row
    response = await c.post(f"/admin/products/{product_id}/edit", data={
        "name": "Shared price", "sku": "SHARED-PRICE", "price_local": "500",
    })
    assert response.status_code == 302
    assert (await _product_by_sku(Session, "SHARED-PRICE")).price_local is None


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["price_local", "price_cny"])
@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
@pytest.mark.parametrize("operation", ["create", "edit"])
async def test_product_prices_reject_nonfinite_values_without_writes(su_env, field, value, operation):
    c, Session = su_env
    async with Session() as session:
        product = Product(name="Finite price", sku="FINITE", country="NG", price_local=100, price_cny=20)
        session.add(product)
        await session.commit()
        product_id = product.id
    path = "/admin/products" if operation == "create" else f"/admin/products/{product_id}/edit"
    response = await c.post(path, data={
        "name": "Invalid price", "sku": "INVALID" if operation == "create" else "FINITE",
        "country": "NG", field: value,
    })
    assert response.status_code == 400
    assert await _product_by_sku(Session, "INVALID") is None
    unchanged = await _product_by_sku(Session, "FINITE")
    assert (unchanged.name, unchanged.price_local, unchanged.price_cny) == ("Finite price", 100, 20)


@pytest.mark.asyncio
async def test_superadmin_can_reassign_country_to_shared_and_back(product_lifecycle_env):
    client, su_token, _, Session = product_lifecycle_env
    product = await _product_by_sku(Session, "NG-LIFE")
    async with client(su_token) as c:
        path = f"/admin/products/{product.id}/edit"
        fields = {"name": "Reassigned", "sku": "NG-LIFE"}
        assert (await c.post(path, data=fields)).status_code == 302
        preserved = await _product_by_sku(Session, "NG-LIFE")
        assert (preserved.country, preserved.price_local) == ("NG", 100)
        assert (await c.post(path, data={**fields, "country": "", "price_local": "100"})).status_code == 302
        shared = await _product_by_sku(Session, "NG-LIFE")
        assert (shared.country, shared.price_local) == (None, None)
        assert (await c.post(path, data={**fields, "country": " cm ", "price_local": "60000"})).status_code == 302
        reassigned = await _product_by_sku(Session, "NG-LIFE")
        assert (reassigned.country, reassigned.price_local) == ("CM", 60000)
        response = await c.post(path, data={**fields, "country": "XX", "price_local": "70000"})
        assert response.status_code == 400
        unchanged = await _product_by_sku(Session, "NG-LIFE")
        assert (unchanged.country, unchanged.price_local) == ("CM", 60000)


@pytest.mark.asyncio
@pytest.mark.parametrize("country,currency", [(None, None), ("CM", "XAF"), ("ML", "XOF"), ("NG", "NGN"), ("SD", "SDG")])
async def test_superadmin_forms_show_ownership_currency_and_shared_price_state(su_env, country, currency):
    import re

    c, Session = su_env
    async with Session() as session:
        product = Product(name="Form ownership", sku="FORM-COUNTRY", country=country, price_local=125000)
        session.add(product)
        await session.commit()
        product_id = product.id
    for path, selected_country, expected_currency in [
        ("/admin/products", None, None),
        (f"/admin/products/{product_id}/edit", country, currency),
    ]:
        response = await c.get(path)
        assert response.status_code == 200
        selector = re.search(r'<select[^>]*name="country"[^>]*>(.*?)</select>', response.text, re.S)
        assert selector, path
        assert re.search(r'<option[^>]*value="' + (selected_country or "") + r'"[^>]*selected', selector.group(1))
        for code, unit in [("CM", "XAF"), ("ML", "XOF"), ("NG", "NGN"), ("SD", "SDG")]:
            assert re.search(r'<option[^>]*value="' + code + r'"[^>]*data-currency="' + unit + '"', selector.group(1))
        label = re.search(r'<label[^>]*for="price_local"[^>]*>(.*?)</label>', response.text, re.S).group(0)
        price_input = re.search(r'<input[^>]*name="price_local"[^>]*>', label).group(0)
        if selected_country:
            assert expected_currency in label
            assert "hidden" not in label.split(">", 1)[0]
            assert "disabled" not in price_input
        else:
            assert "hidden" in label.split(">", 1)[0]
            assert "disabled" in price_input
            assert "125000" not in price_input
        assert 'src="/static/admin-product-form.js"' in response.text


@pytest.mark.asyncio
async def test_country_admin_cannot_reassign_to_shared(product_lifecycle_env):
    client, _, ng_token, Session = product_lifecycle_env
    product = await _product_by_sku(Session, "NG-LIFE")
    async with client(ng_token) as c:
        form = await c.get(f"/admin/products/{product.id}/edit")
        assert 'name="country"' not in form.text
        response = await c.post(f"/admin/products/{product.id}/edit", data={
            "name": "Nigeria", "sku": "NG-LIFE", "country": "", "price_local": "250",
        })
    assert response.status_code == 302
    updated = await _product_by_sku(Session, "NG-LIFE")
    assert (updated.country, updated.price_local) == ("NG", 250)
