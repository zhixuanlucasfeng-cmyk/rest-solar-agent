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
