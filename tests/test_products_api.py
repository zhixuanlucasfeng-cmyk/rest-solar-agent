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
