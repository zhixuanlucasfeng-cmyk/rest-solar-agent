import pytest
from app.tools.currency import CurrencyTool

tool = CurrencyTool()


def test_definition_schema():
    defn = tool.definition()
    assert defn["type"] == "function"
    assert defn["function"]["name"] == "currency_convert"
    params = defn["function"]["parameters"]["properties"]
    assert "amount" in params
    assert "from_currency" in params
    assert "to_currency" in params


async def test_cny_to_xaf_static_rate():
    result = await tool.call({"amount": 100, "from_currency": "CNY", "to_currency": "XAF"})
    assert result["from"] == "CNY"
    assert result["to"] == "XAF"
    assert result["result"] == pytest.approx(9000.0, rel=0.01)


async def test_xaf_to_cny_static_rate():
    result = await tool.call({"amount": 900, "from_currency": "XAF", "to_currency": "CNY"})
    assert result["result"] == pytest.approx(10.0, rel=0.01)


async def test_rate_field_present():
    result = await tool.call({"amount": 1, "from_currency": "CNY", "to_currency": "XAF"})
    assert "rate" in result
    assert isinstance(result["rate"], float)
