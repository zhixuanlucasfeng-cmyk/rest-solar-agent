import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import Rule
from app.agent.orchestrator import run, _retrieve_catalog_context
from app.db.models import Product


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


async def test_catalog_context_includes_panel_warranty(db_with_rules):
    db_with_rules.add(Product(
        name="RT8K-M", sku="SP-TEST-1", category="solar_panels",
        model="RT8K-M", wattage="440-465W",
    ))
    await db_with_rules.commit()
    context = await _retrieve_catalog_context("RT8K-M panel warranty", db_with_rules)
    assert "Warranty: 15-year product warranty" in context
    assert "30-year performance warranty" in context
    assert "≥83% output guaranteed" in context


async def test_catalog_context_no_warranty_for_battery(db_with_rules):
    db_with_rules.add(Product(
        name="RF12-100A", sku="BAT-TEST-1", category="batteries",
        model="RF12-100A", capacity_ah="100Ah",
    ))
    await db_with_rules.commit()
    context = await _retrieve_catalog_context("RF12-100A battery", db_with_rules)
    assert "Warranty:" not in context
