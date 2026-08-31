from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.tools.base import BaseTool
from app.db.models import Order
from app.countries import normalize_country


async def next_order_number(db: AsyncSession, country: str) -> str:
    cc = normalize_country(country)
    today = datetime.utcnow().strftime("%Y%m%d")
    prefix = f"{cc}-{today}-"
    count = await db.scalar(
        select(func.count()).select_from(Order).where(Order.order_number.like(prefix + "%"))
    )
    return f"{prefix}{(count or 0) + 1:03d}"


class OrderTool(BaseTool):
    name = "get_order_status"
    description = "Look up the status of a customer order by order number."

    def __init__(self, db: AsyncSession):
        self._db = db

    def definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "order_number": {
                            "type": "string",
                            "description": "The order number, e.g. ORD-2024-001",
                        },
                    },
                    "required": ["order_number"],
                },
            },
        }

    async def call(self, params: dict) -> dict:
        order_number = str(params["order_number"]).strip()
        result = await self._db.execute(select(Order).where(Order.order_number == order_number))
        order = result.scalar_one_or_none()
        if not order:
            return {"error": f"Order '{order_number}' not found"}
        return {
            "order_number": order.order_number,
            "customer_name": order.customer_name,
            "status": order.status,
            "created_at": order.created_at.isoformat(),
        }


class CreateOrderTool(BaseTool):
    name = "create_order"
    description = (
        "Record a purchase order. Use ONLY after the customer has explicitly "
        "confirmed they want to order or be contacted to complete a purchase. "
        "Captures name, contact, and requested items. Does not take payment or "
        "change stock."
    )

    def __init__(self, db: AsyncSession, conversation=None):
        self._db = db
        self._conversation = conversation

    def definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "customer_name": {"type": "string", "description": "Customer's name"},
                        "contact": {"type": "string", "description": "Phone / WhatsApp / email"},
                        "items": {
                            "type": "string",
                            "description": "Requested items, e.g. '2x INV-5000, 1x BAT-100'",
                        },
                        "notes": {"type": "string", "description": "Any extra detail (optional)"},
                    },
                    "required": ["customer_name", "contact", "items"],
                },
            },
        }

    async def call(self, params: dict) -> dict:
        conv = self._conversation
        country = normalize_country(getattr(conv, "country", None))
        number = await next_order_number(self._db, country)
        order = Order(
            order_number=number,
            country=country,
            conversation_id=getattr(conv, "id", None),
            customer_name=str(params["customer_name"]),
            contact=str(params["contact"]),
            items=str(params["items"]),
            notes=(str(params.get("notes")).strip() or None) if params.get("notes") else None,
            status="pending",
        )
        self._db.add(order)
        await self._db.flush()
        return {
            "order_number": order.order_number,
            "status": order.status,
            "confirmation": (
                f"Order {order.order_number} recorded. The {country} team will contact "
                f"{params['contact']} to confirm details and pricing."
            ),
        }
