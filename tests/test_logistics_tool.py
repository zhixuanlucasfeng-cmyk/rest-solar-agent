import pytest
from app.tools.logistics import LogisticsTool


@pytest.mark.asyncio
async def test_sea_freight():
    tool = LogisticsTool()
    result = await tool.call({"origin": "Shenzhen", "destination": "Douala", "weight_kg": 100, "mode": "sea"})
    assert result["mode"] == "sea"
    assert result["transit_days"] == 30
    assert result["freight_cny"] == pytest.approx(100 * 8.0)
    assert "freight_xaf" in result


@pytest.mark.asyncio
async def test_air_freight():
    tool = LogisticsTool()
    result = await tool.call({"origin": "Guangzhou", "destination": "Douala", "weight_kg": 10, "mode": "air"})
    assert result["mode"] == "air"
    assert result["transit_days"] == 7
    assert result["freight_cny"] == pytest.approx(10 * 45.0)


@pytest.mark.asyncio
async def test_default_mode_is_sea():
    tool = LogisticsTool()
    result = await tool.call({"origin": "Shanghai", "destination": "Douala", "weight_kg": 50})
    assert result["mode"] == "sea"


def test_definition():
    tool = LogisticsTool()
    defn = tool.definition()
    assert defn["function"]["name"] == "get_logistics"
    props = defn["function"]["parameters"]["properties"]
    assert "origin" in props
    assert "destination" in props
    assert "weight_kg" in props
