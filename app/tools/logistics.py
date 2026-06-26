from app.tools.base import BaseTool

# Stubbed rates: sea CNY/kg, air CNY/kg, transit days
# Interface is ready for a real freight API integration later.
SEA_RATE_CNY_PER_KG = 8.0
AIR_RATE_CNY_PER_KG = 45.0
SEA_TRANSIT_DAYS = 30
AIR_TRANSIT_DAYS = 7
CNY_TO_XAF = 90.0  # static fallback


class LogisticsTool(BaseTool):
    name = "get_logistics"
    description = (
        "Get estimated shipping time and freight cost from China to Cameroon (Douala port). "
        "Supports sea freight (~30 days) and air freight (~7 days)."
    )

    def definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "origin": {
                            "type": "string",
                            "description": "Origin city in China, e.g. Shenzhen",
                        },
                        "destination": {
                            "type": "string",
                            "description": "Destination city in Cameroon, e.g. Douala",
                        },
                        "weight_kg": {
                            "type": "number",
                            "description": "Total shipment weight in kilograms",
                        },
                        "mode": {
                            "type": "string",
                            "enum": ["sea", "air"],
                            "description": "Shipping mode: sea (cheaper, slower) or air (faster, expensive). Defaults to sea.",
                        },
                    },
                    "required": ["origin", "destination", "weight_kg"],
                },
            },
        }

    async def call(self, params: dict) -> dict:
        origin = str(params["origin"])
        destination = str(params["destination"])
        weight_kg = float(params["weight_kg"])
        mode = str(params.get("mode", "sea")).lower()
        if mode not in ("sea", "air"):
            mode = "sea"

        if mode == "sea":
            transit_days = SEA_TRANSIT_DAYS
            freight_cny = round(weight_kg * SEA_RATE_CNY_PER_KG, 2)
        else:
            transit_days = AIR_TRANSIT_DAYS
            freight_cny = round(weight_kg * AIR_RATE_CNY_PER_KG, 2)

        return {
            "origin": origin,
            "destination": destination,
            "weight_kg": weight_kg,
            "mode": mode,
            "transit_days": transit_days,
            "freight_cny": freight_cny,
            "freight_xaf": round(freight_cny * CNY_TO_XAF, 2),
        }
