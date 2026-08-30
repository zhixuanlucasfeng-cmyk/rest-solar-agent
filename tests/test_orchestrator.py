import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import Product, Rule
from app.agent.orchestrator import run
from app.llm.client import LLMUnavailableError


@pytest.fixture
async def db_with_rules(db: AsyncSession):
    db.add(Rule(
        name="low_score_fallback", trigger="", priority=0,
        body="If no KB chunks found, decline and offer a ticket."
    ))
    await db.commit()
    return db


async def _make_llm_text_response(content: str):
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = None
    return msg


async def _make_llm_tool_response(tool_name: str, args: dict, call_id: str = "call_1"):
    tc = MagicMock()
    tc.id = call_id
    tc.function.name = tool_name
    tc.function.arguments = json.dumps(args)

    msg = MagicMock()
    msg.content = None
    msg.tool_calls = [tc]
    return msg


@patch("app.agent.orchestrator.chat_complete")
async def test_plain_text_response(mock_llm, db_with_rules):
    mock_llm.return_value = await _make_llm_text_response("We sell 50W to 550W panels.")
    result = await run("What panels do you sell?", "session-1", db_with_rules)
    assert result["reply"] == "We sell 50W to 550W panels."
    assert result["language"] == "en"


@patch("app.agent.orchestrator.chat_complete")
async def test_tool_call_currency(mock_llm, db_with_rules):
    tool_resp = await _make_llm_tool_response(
        "currency_convert",
        {"amount": 500, "from_currency": "CNY", "to_currency": "XAF"},
    )
    text_resp = await _make_llm_text_response("500 CNY = 45000 XAF at today's rate.")
    mock_llm.side_effect = [tool_resp, text_resp]

    result = await run("Convert 500 CNY to XAF", "session-2", db_with_rules)
    assert "45000" in result["reply"] or "XAF" in result["reply"]
    assert mock_llm.call_count == 2


@patch("app.agent.orchestrator.chat_complete")
async def test_french_input_detected(mock_llm, db_with_rules):
    mock_llm.return_value = await _make_llm_text_response("Nous vendons des panneaux solaires.")
    result = await run("Quels panneaux vendez-vous ?", "session-3", db_with_rules)
    assert result["language"] == "fr"


@patch("app.agent.orchestrator.chat_complete")
async def test_llm_unavailable_returns_friendly_fallback_en(mock_llm, db_with_rules):
    """A transient LLM failure must produce a friendly reply with contact
    info, not propagate and 500 the /api/chat route."""
    mock_llm.side_effect = LLMUnavailableError("rate limited")
    result = await run("How much is the panel?", "session-4", db_with_rules)
    assert "trouble connecting" in result["reply"]
    assert "681 105 611" in result["reply"]
    assert result["language"] == "en"


@patch("app.agent.orchestrator.chat_complete")
async def test_llm_unavailable_returns_friendly_fallback_fr(mock_llm, db_with_rules):
    mock_llm.side_effect = LLMUnavailableError("rate limited")
    result = await run("Combien coûte le panneau ?", "session-5", db_with_rules)
    assert "problème de connexion" in result["reply"]
    assert result["language"] == "fr"


@patch("app.agent.orchestrator.chat_complete")
async def test_catalog_context_shows_real_price_when_set(mock_llm, db_with_rules):
    """A product with price_xaf populated (scripts/apply_price_list.py) must
    surface its actual FCFA price in the system prompt instead of the old
    hardcoded 'Price on request' — that hardcoding was the whole reason the
    chatbot couldn't quote prices even after they were in the DB."""
    db_with_rules.add(Product(
        name="RTM210M 210W", sku="SP-999-TEST", category="solar_panels",
        model="RTM210M", wattage="210W", price_xaf=18000.0,
    ))
    await db_with_rules.commit()

    mock_llm.return_value = await _make_llm_text_response("It costs 18,000 FCFA.")
    await run("How much does the RTM210M 210W panel cost?", "session-6", db_with_rules)

    system_content = mock_llm.call_args.args[0][0]["content"]
    assert "18,000 FCFA" in system_content


@patch("app.agent.orchestrator.chat_complete")
async def test_catalog_context_falls_back_when_price_unset(mock_llm, db_with_rules):
    db_with_rules.add(Product(
        name="Unpriced Panel", sku="SP-998-TEST", category="solar_panels",
        model="UnpricedPanel", wattage="999W",
    ))
    await db_with_rules.commit()

    mock_llm.return_value = await _make_llm_text_response("Contact us for pricing.")
    await run("How much does the UnpricedPanel 999W cost?", "session-7", db_with_rules)

    system_content = mock_llm.call_args.args[0][0]["content"]
    assert "Price on request" in system_content


@patch("app.agent.orchestrator.chat_complete")
async def test_catalog_context_country_scoped(mock_llm, db_with_rules):
    """A conversation's catalog context sees only shared products + its own
    country's products, never another country's."""
    db_with_rules.add_all([
        Product(name="SharedPanel", sku="SHP-1", category="solar_panels",
                model="SharedPanel", wattage="100W", country=None),
        Product(name="NGPanel", sku="NGP-1", category="solar_panels",
                model="NGPanel", wattage="100W", country="NG"),
        Product(name="MLPanel", sku="MLP-1", category="solar_panels",
                model="MLPanel", wattage="100W", country="ML"),
    ])
    await db_with_rules.commit()

    mock_llm.return_value = await _make_llm_text_response("ok")
    await run("Do you have the SharedPanel, NGPanel or MLPanel?",
              "session-ctry-1", db_with_rules, country="NG")

    system_content = mock_llm.call_args.args[0][0]["content"]
    assert "SHP-1" in system_content
    assert "NGP-1" in system_content
    assert "MLP-1" not in system_content


@patch("app.agent.orchestrator.chat_complete")
async def test_catalog_context_none_country_sees_shared_only(mock_llm, db_with_rules):
    db_with_rules.add_all([
        Product(name="SharedPanel", sku="SHP-1", category="solar_panels",
                model="SharedPanel", wattage="100W", country=None),
        Product(name="NGPanel", sku="NGP-1", category="solar_panels",
                model="NGPanel", wattage="100W", country="NG"),
    ])
    await db_with_rules.commit()

    mock_llm.return_value = await _make_llm_text_response("ok")
    await run("Do you have the SharedPanel or NGPanel?",
              "session-ctry-2", db_with_rules)

    system_content = mock_llm.call_args.args[0][0]["content"]
    assert "SHP-1" in system_content
    assert "NGP-1" not in system_content


@patch("app.agent.orchestrator.chat_complete")
async def test_catalog_context_flags_featured_product(mock_llm, db_with_rules):
    """Admin-marked Featured products must surface a ★ marker in the system
    prompt so the assistant can call them out as a recommended pick — the
    Featured flag previously only showed up in the admin UI, never reaching
    what the bot actually told customers."""
    db_with_rules.add(Product(
        name="FeaturedPanel 300W", sku="SP-997-TEST", category="solar_panels",
        model="FeaturedPanel300", wattage="300W", price_xaf=25000.0, featured=True,
    ))
    db_with_rules.add(Product(
        name="PlainPanel 300W", sku="SP-996-TEST", category="solar_panels",
        model="PlainPanel300", wattage="300W", price_xaf=24000.0, featured=False,
    ))
    await db_with_rules.commit()

    mock_llm.return_value = await _make_llm_text_response("We recommend the FeaturedPanel300.")
    await run("Tell me about your 300W panels", "session-8", db_with_rules)

    system_content = mock_llm.call_args.args[0][0]["content"]
    assert "SKU SP-997-TEST) (★ Featured/recommended model):" in system_content
    assert "SKU SP-996-TEST):" in system_content
    assert "SKU SP-996-TEST) (★" not in system_content
