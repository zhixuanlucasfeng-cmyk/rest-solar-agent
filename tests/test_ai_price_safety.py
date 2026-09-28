from app.agent.orchestrator import _SYSTEM_TEMPLATE, _retrieve_catalog_context
from app.db.models import Product
from app.tools import get_tools


async def test_gemini_toolset_has_no_quote_tool(db):
    names = {tool.definition()["function"]["name"] for tool in get_tools(db)}
    assert "get_quote" not in names


async def test_gemini_catalog_context_omits_numeric_prices_and_currencies(db):
    db.add(Product(
        name="NG price safety panel", sku="NG-SAFE-PRICE", category="solar_panels",
        model="NGSafePrice", country="NG", status="active",
        price_local=850000.0, price_xaf=18000.0,
    ))
    await db.commit()

    context = await _retrieve_catalog_context("NGSafePrice", db, country="NG")
    assert "NG-SAFE-PRICE" in context
    assert "Price must be confirmed with staff because local prices can change." in context
    for forbidden in ("850000", "850,000", "18000", "18,000", "NGN", "FCFA"):
        assert forbidden not in context


def test_gemini_system_prompt_requires_human_price_confirmation():
    assert "Prices can change. Never state or promise an exact price." in _SYSTEM_TEMPLATE
    assert "confirm the current price with human staff" in _SYSTEM_TEMPLATE
    assert "For prices, just say them naturally" not in _SYSTEM_TEMPLATE
