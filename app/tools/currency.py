import os
import httpx
from app.tools.base import BaseTool
from dotenv import load_dotenv

load_dotenv()

STATIC_RATE_CNY_TO_XAF = 90.0


class CurrencyTool(BaseTool):
    name = "currency_convert"
    description = "Convert between CNY (Chinese Yuan Renminbi) and XAF (West African CFA franc)."

    def definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "amount": {
                            "type": "number",
                            "description": "Amount to convert (must be positive)",
                        },
                        "from_currency": {
                            "type": "string",
                            "enum": ["CNY", "XAF"],
                            "description": "Source currency",
                        },
                        "to_currency": {
                            "type": "string",
                            "enum": ["CNY", "XAF"],
                            "description": "Target currency",
                        },
                    },
                    "required": ["amount", "from_currency", "to_currency"],
                },
            },
        }

    async def call(self, params: dict) -> dict:
        amount = float(params["amount"])
        from_c = params["from_currency"].upper()
        to_c = params["to_currency"].upper()

        rate = await self._get_rate_cny_to_xaf()

        if from_c == "CNY" and to_c == "XAF":
            converted = round(amount * rate, 2)
        elif from_c == "XAF" and to_c == "CNY":
            converted = round(amount / rate, 2)
        else:
            return {"error": f"Unsupported pair: {from_c}/{to_c}"}

        return {
            "amount": amount,
            "from": from_c,
            "to": to_c,
            "rate": rate,
            "result": converted,
        }

    async def _get_rate_cny_to_xaf(self) -> float:
        api_key = os.getenv("CURRENCY_API_KEY", "").strip()
        if not api_key:
            return STATIC_RATE_CNY_TO_XAF
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    f"https://v6.exchangerate-api.com/v6/{api_key}/pair/CNY/XAF"
                )
                data = resp.json()
                if data.get("result") == "success":
                    return float(data["conversion_rate"])
        except Exception:
            pass
        return STATIC_RATE_CNY_TO_XAF


TOOLS: list[BaseTool] = [CurrencyTool()]
TOOL_MAP: dict[str, BaseTool] = {t.name: t for t in TOOLS}
