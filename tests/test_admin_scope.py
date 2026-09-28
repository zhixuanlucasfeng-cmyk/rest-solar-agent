import pytest
from fastapi import HTTPException
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.admin.deps import scope_clause, assert_visible
from app.admin.auth import create_access_token, hash_password
from app.db.models import AdminUser, Base, Conversation, Product
from app.db.session import get_db
from app.main import app


class _Obj:
    def __init__(self, country):
        self.country = country


def test_scope_clause_superadmin_is_true():
    su = AdminUser(email="s", password_hash="x", role="superadmin", country=None)
    clause = scope_clause(su, Conversation)
    assert clause.compare(__import__("sqlalchemy").true())


def test_scope_clause_country_admin():
    ca = AdminUser(email="c", password_hash="x", role="country_admin", country="NG")
    clause = scope_clause(ca, Conversation)
    # renders to "conversations.country = :country_1"
    assert "country" in str(clause)


def test_assert_visible():
    su = AdminUser(email="s", password_hash="x", role="superadmin", country=None)
    ca = AdminUser(email="c", password_hash="x", role="country_admin", country="NG")
    assert_visible(su, _Obj("ML"))          # superadmin: no raise
    assert_visible(ca, _Obj("NG"))          # same country: no raise
    with pytest.raises(HTTPException) as e:
        assert_visible(ca, _Obj("ML"))
    assert e.value.status_code == 404
    with pytest.raises(HTTPException):
        assert_visible(ca, _Obj(None))


@pytest.fixture
async def country_product_scope_env():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        admin = AdminUser(email="ng-scope@test.com", password_hash=hash_password("p"),
                          role="country_admin", country="NG")
        products = {
            "shared": Product(name="Shared", sku="SH-SCOPE", country=None),
            "other": Product(name="Cameroon", sku="CM-SCOPE", country="CM"),
            "own": Product(name="Nigeria", sku="NG-SCOPE", country="NG"),
        }
        s.add(admin)
        s.add_all(products.values())
        await s.commit()
        ids = {key: product.id for key, product in products.items()}
        token = create_access_token({"sub": str(admin.id), "role": admin.role})

    async def override_get_db():
        async with Session() as s:
            yield s
    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test",
                           cookies={"admin_token": token}) as client:
        yield client, Session, ids
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_country_admin_product_scope_and_deletion_permissions(country_product_scope_env):
    client, Session, ids = country_product_scope_env
    for key, expected in (("shared", 403), ("other", 404)):
        product_id = ids[key]
        edit_page = await client.get(f"/admin/products/{product_id}/edit")
        edit = await client.post(f"/admin/products/{product_id}/edit", data={
            "name": "Hacked", "sku": "SH-SCOPE" if key == "shared" else "CM-SCOPE",
        }, follow_redirects=False)
        status = await client.post(f"/admin/products/{product_id}/status", data={
            "status": "archived",
        }, follow_redirects=False)
        assert (edit_page.status_code, edit.status_code, status.status_code) == (expected,) * 3
    delete = await client.post(f"/admin/products/{ids['own']}/delete", follow_redirects=False)
    assert delete.status_code == 403
    async with Session() as s:
        rows = (await s.execute(select(Product).order_by(Product.id))).scalars().all()
    assert [(row.name, row.status) for row in rows] == [
        ("Shared", "active"), ("Cameroon", "active"), ("Nigeria", "active"),
    ]
