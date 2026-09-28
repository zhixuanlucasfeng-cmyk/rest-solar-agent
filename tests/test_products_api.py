import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.db.models import Product, ProductImage
from app.db.session import get_db


@pytest.fixture
async def client(db):
    async def override_get_db():
        yield db
    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_products_public_no_auth_required(client, db):
    product = Product(
        name="Test Panel 300W", sku="PUB-TEST-1", category="solar_panels",
        wattage="300W", price_xaf=25000.0, featured=True,
        image_path="static/product_images/PUB-TEST-1.jpg",
    )
    db.add(product)
    await db.flush()
    db.add(ProductImage(product_id=product.id, path="static/product_images/PUB-TEST-1_1.jpg", sort_order=0))
    await db.commit()

    resp = await client.get("/api/products")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    item = data[0]
    assert item["sku"] == "PUB-TEST-1"
    assert item["featured"] is True
    assert item["image"] == "/static/product_images/PUB-TEST-1.jpg"
    assert item["images"] == ["/static/product_images/PUB-TEST-1_1.jpg"]
    assert "duty_rate" not in item
    assert "vat_rate" not in item


@pytest.mark.asyncio
async def test_products_feed_country_filter(client, db):
    # Seed products: one shared (country=None), one NG-only, one ML-only
    db.add_all([
        Product(name="Shared", sku="SH-1", category="solar_panels", country=None),
        Product(name="NG only", sku="NG-1", category="solar_panels", country="NG"),
        Product(name="ML only", sku="ML-1", category="solar_panels", country="ML"),
    ])
    await db.commit()

    # No param: should return only shared (country=None)
    r_all = await client.get("/api/products")
    skus_default = {p["sku"] for p in r_all.json()}
    assert skus_default == {"SH-1"}

    # Valid country param: should return shared + that country's products
    r_ng = await client.get("/api/products?country=NG")
    skus_ng = {p["sku"] for p in r_ng.json()}
    assert skus_ng == {"SH-1", "NG-1"}

    # Invalid country param: should return only shared
    r_bad = await client.get("/api/products?country=US")
    skus_bad = {p["sku"] for p in r_bad.json()}
    assert skus_bad == {"SH-1"}

    # Whitespace / mixed-case country param must still resolve (fix #7d)
    r_ws = await client.get("/api/products", params={"country": " ng "})
    skus_ws = {p["sku"] for p in r_ws.json()}
    assert skus_ws == {"SH-1", "NG-1"}


@pytest.mark.asyncio
async def test_products_feed_publishes_only_active_with_local_catalog_fields(client, db):
    active = Product(
        name="Active NG panel", sku="NG-ACTIVE", category="solar_panels",
        country="NG", status="active", price_local=850000.0, stock=7,
    )
    db.add_all([
        active,
        Product(name="Inactive NG panel", sku="NG-INACTIVE", category="solar_panels",
                country="NG", status="inactive", price_local=700000.0),
        Product(name="Archived NG panel", sku="NG-ARCHIVED", category="solar_panels",
                country="NG", status="archived", price_local=600000.0),
    ])
    await db.commit()

    response = await client.get("/api/products?country=NG")
    assert response.status_code == 200
    assert [item["sku"] for item in response.json()] == ["NG-ACTIVE"]
    item = response.json()[0]
    assert {key: item[key] for key in ("id", "country", "status", "price_local", "currency", "stock")} == {
        "id": active.id,
        "country": "NG",
        "status": "active",
        "price_local": 850000.0,
        "currency": "NGN",
        "stock": 7,
    }


@pytest.mark.asyncio
async def test_shared_catalog_never_serializes_a_local_price(client, db):
    db.add(Product(name="Shared legacy price", sku="SHARED-PRICE", country=None,
                   price_local=125000, price_xaf=120000, price_cny=500))
    await db.commit()
    for country in ("CM", "NG", "ML", "SD"):
        response = await client.get("/api/products", params={"country": country})
        assert response.status_code == 200
        assert response.json()[0]["price_local"] is None
        assert response.json()[0]["currency"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("price", [float("nan"), float("inf"), float("-inf")])
async def test_public_feed_suppresses_nonfinite_legacy_prices(client, db, price):
    product = Product(name="Legacy invalid price", sku="LEGACY-INVALID", country="NG",
                      price_local=price, price_xaf=price, price_cny=price)
    db.add(product)
    await db.commit()
    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False),
                           base_url="http://test") as public:
        response = await public.get("/api/products?country=NG")
    assert response.status_code == 200
    item = response.json()[0]
    assert {key: item[key] for key in ("price_local", "price_xaf", "price_cny")} == {
        "price_local": None, "price_xaf": None, "price_cny": None,
    }
