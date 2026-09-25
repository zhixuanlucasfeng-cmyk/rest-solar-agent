from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.countries import is_valid_country, normalize_country
from app.db.models import Conversation, Order, Product
from app.db.session import get_db
from app.tools.order import next_order_number

router = APIRouter()
MAX_ORDER_ATTEMPTS = 3


@router.post("/api/orders", status_code=status.HTTP_201_CREATED)
async def create_order(
    payload: dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db),
):
    country = payload.get("country")
    if not is_valid_country(country):
        raise HTTPException(status_code=400, detail="A supported country is required")
    country = normalize_country(country)

    customer_name = payload.get("customer_name")
    if not isinstance(customer_name, str) or not customer_name.strip():
        raise HTTPException(status_code=400, detail="customer_name is required")
    customer_name = customer_name.strip()

    contact = payload.get("contact")
    if not isinstance(contact, str) or not contact.strip():
        raise HTTPException(status_code=400, detail="contact is required")
    contact = contact.strip()

    raw_items = payload.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise HTTPException(status_code=400, detail="items must be a non-empty array")

    quantities: dict[str, int] = {}
    for item in raw_items:
        if not isinstance(item, dict):
            raise HTTPException(status_code=400, detail="Each item must contain a SKU and quantity")
        sku = item.get("sku")
        if not isinstance(sku, str) or not sku.strip():
            raise HTTPException(status_code=400, detail="Each item must contain a SKU")
        qty = item.get("qty")
        if type(qty) is not int or qty <= 0:
            raise HTTPException(status_code=400, detail="Item quantity must be a positive integer")
        sku = sku.strip()
        quantities[sku] = quantities.get(sku, 0) + qty

    session_id = payload.get("session_id")
    if session_id is not None:
        if not isinstance(session_id, str) or not session_id.strip():
            raise HTTPException(status_code=400, detail="session_id must be a non-empty string")
        session_id = session_id.strip()

    notes = payload.get("notes")
    if notes is not None and not isinstance(notes, str):
        raise HTTPException(status_code=400, detail="notes must be a string")
    notes = notes.strip() or None if isinstance(notes, str) else None

    for attempt in range(MAX_ORDER_ATTEMPTS):
        try:
            products = (
                await db.scalars(
                    select(Product)
                    .where(
                        Product.sku.in_(quantities),
                        or_(Product.country.is_(None), Product.country == country),
                    )
                    .with_for_update()
                )
            ).all()
            products_by_sku = {product.sku: product for product in products}
            unavailable = [sku for sku in quantities if sku not in products_by_sku]
            if unavailable:
                raise HTTPException(
                    status_code=404,
                    detail=f"SKU unavailable for {country}: {', '.join(unavailable)}",
                )

            for sku, qty in quantities.items():
                product = products_by_sku[sku]
                if product.country is not None and product.stock < qty:
                    raise HTTPException(status_code=409, detail=f"Insufficient stock for SKU {sku}")

            conversation_id = None
            if session_id is not None:
                conversation_id = await db.scalar(
                    select(Conversation.id)
                    .where(
                        Conversation.session_id == session_id,
                        Conversation.country == country,
                    )
                    .order_by(Conversation.id.desc())
                    .limit(1)
                )

            number = await next_order_number(db, country)
            item_snapshot = "\n".join(
                f"{qty}x {sku} — {products_by_sku[sku].name}"
                for sku, qty in quantities.items()
            )
            order = Order(
                order_number=number,
                country=country,
                conversation_id=conversation_id,
                customer_name=customer_name,
                contact=contact,
                items=item_snapshot,
                notes=notes,
                status="pending",
            )
            db.add(order)

            for sku, qty in quantities.items():
                product = products_by_sku[sku]
                if product.country is not None:
                    product.stock -= qty

            await db.flush()
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            if attempt == MAX_ORDER_ATTEMPTS - 1:
                raise HTTPException(status_code=409, detail="Order could not be saved") from exc
            continue
        except HTTPException:
            await db.rollback()
            raise
        except Exception as exc:
            await db.rollback()
            raise HTTPException(status_code=409, detail="Order could not be saved") from exc

        return {
            "order_number": number,
            "status": "pending",
            "confirmation": (
                f"Order {number} recorded. The {country} team will contact {contact} "
                "to confirm details and pricing."
            ),
        }

    raise HTTPException(status_code=409, detail="Order could not be saved")
