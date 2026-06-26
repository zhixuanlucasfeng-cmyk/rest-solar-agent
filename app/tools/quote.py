from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.tools.base import BaseTool
from app.db.models import Product

SHIPPING_RATE_CNY_PER_KG = 22.0  # sea freight China→Cameroon, per kg


class QuoteTool(BaseTool):
    name = "get_quote"
    description = (
        "Get a price quote for a Rest Solar product. "
        "Returns subtotal, import duty, VAT, shipping, and total in CNY and XAF."
    )

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
                        "sku": {
                            "type": "string",
                            "description": "Product SKU code, e.g. SP-400",
                        },
                        "quantity": {
                            "type": "integer",
                            "description": "Number of units",
                            "minimum": 1,
                        },
                    },
                    "required": ["sku", "quantity"],
                },
            },
        }

    async def call(self, params: dict) -> dict:
        sku = str(params["sku"]).upper()
        qty = int(params["quantity"])

        result = await self._db.execute(select(Product).where(Product.sku == sku))
        product = result.scalar_one_or_none()
        if not product:
            return {"error": f"Product with SKU '{sku}' not found"}

        subtotal_cny = round(product.price_cny * qty, 2)
        duty_cny = round(subtotal_cny * product.duty_rate, 2)
        vat_cny = round(subtotal_cny * product.vat_rate, 2)
        weight_total = (product.weight_kg or 0.0) * qty
        shipping_cny = round(weight_total * SHIPPING_RATE_CNY_PER_KG, 2)
        total_cny = round(subtotal_cny + duty_cny + vat_cny + shipping_cny, 2)
        total_xaf = round(total_cny * (product.price_xaf / product.price_cny), 2)

        return {
            "sku": product.sku,
            "name": product.name,
            "quantity": qty,
            "unit_price_cny": product.price_cny,
            "unit_price_xaf": product.price_xaf,
            "subtotal_cny": subtotal_cny,
            "duty_cny": duty_cny,
            "vat_cny": vat_cny,
            "shipping_cny": shipping_cny,
            "total_cny": total_cny,
            "total_xaf": total_xaf,
        }
