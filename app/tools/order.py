from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.tools.base import BaseTool
from app.db.models import Order


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
