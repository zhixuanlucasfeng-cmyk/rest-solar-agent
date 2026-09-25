import re

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.db.models import Conversation, Order, Product
from app.db.session import get_db
from app.main import app


@pytest.fixture
async def client(db):
    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="https://agent-backend.test",
    ) as http_client:
        yield http_client
    app.dependency_overrides.clear()


def order_payload(**overrides):
    payload = {
        "country": "NG",
        "customer_name": "Ada Okafor",
        "contact": "+234 800 000 0000",
        "items": [{"sku": "NG-PANEL", "qty": 2}],
        "notes": "Call before delivery",
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_create_order_persists_server_snapshot_and_decrements_country_stock(client, db):
    db.add(Product(name="Nigeria Panel", sku="NG-PANEL", country="NG", stock=5, price_xaf=99_000))
    await db.commit()

    response = await client.post("/api/orders", json=order_payload())

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"order_number", "status", "confirmation"}
    assert re.fullmatch(r"NG-\d{8}-001", body["order_number"])
    assert body["status"] == "pending"
    assert body["order_number"] in body["confirmation"]
    assert "price_xaf" not in body

    order = await db.scalar(select(Order))
    product = await db.scalar(select(Product).where(Product.sku == "NG-PANEL"))
    assert order is not None
    assert order.country == "NG"
    assert order.customer_name == "Ada Okafor"
    assert order.contact == "+234 800 000 0000"
    assert order.items == "2x NG-PANEL — Nigeria Panel"
    assert order.notes == "Call before delivery"
    assert order.status == "pending"
    assert product.stock == 3


@pytest.mark.asyncio
async def test_create_order_allows_shared_product_without_decrementing_stock(client, db):
    db.add(Product(name="Shared Cable", sku="SH-CABLE", country=None, stock=0))
    await db.commit()

    response = await client.post(
        "/api/orders",
        json=order_payload(items=[{"sku": "SH-CABLE", "qty": 50}]),
    )

    assert response.status_code == 201
    product = await db.scalar(select(Product).where(Product.sku == "SH-CABLE"))
    assert product.stock == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("country", [None, "OTHER", "US"])
async def test_create_order_rejects_missing_or_unsupported_country(client, country):
    payload = order_payload(country=country)
    if country is None:
        payload.pop("country")

    response = await client.post("/api/orders", json=payload)

    assert response.status_code == 400
    assert "country" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_order_rejects_empty_items(client):
    response = await client.post("/api/orders", json=order_payload(items=[]))

    assert response.status_code == 400
    assert "items" in response.json()["detail"].lower()


@pytest.mark.asyncio
@pytest.mark.parametrize("qty", [0, -1, 1.5])
async def test_create_order_rejects_non_positive_or_non_integer_quantity(client, qty):
    response = await client.post(
        "/api/orders",
        json=order_payload(items=[{"sku": "NG-PANEL", "qty": qty}]),
    )

    assert response.status_code == 400
    assert "quantity" in response.json()["detail"].lower()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("product_country", "sku"),
    [(None, "MISSING"), ("ML", "ML-PANEL")],
)
async def test_create_order_rejects_unknown_or_cross_country_sku(
    client, db, product_country, sku
):
    if product_country is not None:
        db.add(Product(name="Mali Panel", sku=sku, country=product_country, stock=9))
        await db.commit()

    response = await client.post(
        "/api/orders",
        json=order_payload(items=[{"sku": sku, "qty": 1}]),
    )

    assert response.status_code == 404
    assert "sku" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_order_rejects_insufficient_country_stock_without_creating_order(client, db):
    db.add(Product(name="Nigeria Panel", sku="NG-PANEL", country="NG", stock=1))
    await db.commit()

    response = await client.post("/api/orders", json=order_payload())

    assert response.status_code == 409
    assert "stock" in response.json()["detail"].lower()
    assert await db.scalar(select(Order)) is None
    product = await db.scalar(select(Product).where(Product.sku == "NG-PANEL"))
    assert product.stock == 1


@pytest.mark.asyncio
async def test_create_order_aggregates_duplicate_skus_before_stock_check(client, db):
    db.add(Product(name="Nigeria Panel", sku="NG-PANEL", country="NG", stock=5))
    await db.commit()

    response = await client.post(
        "/api/orders",
        json=order_payload(
            items=[
                {"sku": "NG-PANEL", "qty": 2},
                {"sku": "NG-PANEL", "qty": 3},
            ]
        ),
    )

    assert response.status_code == 201
    order = await db.scalar(select(Order))
    product = await db.scalar(select(Product).where(Product.sku == "NG-PANEL"))
    assert order.items == "5x NG-PANEL — Nigeria Panel"
    assert product.stock == 0


@pytest.mark.asyncio
async def test_create_order_links_only_same_country_session(client, db):
    matching = Conversation(session_id="same-country", country="NG")
    cross_country = Conversation(session_id="other-country", country="ML")
    db.add_all([
        matching,
        cross_country,
        Product(name="Nigeria Panel", sku="NG-PANEL", country="NG", stock=5),
    ])
    await db.commit()

    linked_response = await client.post(
        "/api/orders",
        json=order_payload(session_id="same-country"),
    )
    unlinked_response = await client.post(
        "/api/orders",
        json=order_payload(session_id="other-country", items=[{"sku": "NG-PANEL", "qty": 1}]),
    )

    assert linked_response.status_code == 201
    assert unlinked_response.status_code == 201
    orders = (await db.scalars(select(Order).order_by(Order.id))).all()
    assert orders[0].conversation_id == matching.id
    assert orders[1].conversation_id is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    [("customer_name", "  "), ("contact", "")],
)
async def test_create_order_rejects_blank_customer_fields(client, field, value):
    response = await client.post("/api/orders", json=order_payload(**{field: value}))

    assert response.status_code == 400
    assert field in response.json()["detail"].lower()
