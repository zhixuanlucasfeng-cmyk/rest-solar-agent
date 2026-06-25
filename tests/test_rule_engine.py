from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import Rule
from app.agent.rule_engine import get_matching_rules


async def test_matches_trigger_keyword(db: AsyncSession):
    db.add(Rule(name="r1", trigger="price/prix", body="Never invent prices.", priority=1))
    await db.commit()
    result = await get_matching_rules("What is the price of a 200W panel?", db)
    assert "Never invent prices." in result


async def test_no_match_returns_empty(db: AsyncSession):
    db.add(Rule(name="r2", trigger="warranty/garantie", body="Warranty policy.", priority=1))
    await db.commit()
    result = await get_matching_rules("Tell me about delivery time.", db)
    assert result == []


async def test_always_active_rule_matches_everything(db: AsyncSession):
    db.add(Rule(name="fallback", trigger="", body="Always active rule.", priority=0))
    await db.commit()
    result = await get_matching_rules("anything at all", db)
    assert "Always active rule." in result


async def test_priority_order(db: AsyncSession):
    db.add(Rule(name="low_pri", trigger="solar", body="Low priority body.", priority=10))
    db.add(Rule(name="high_pri", trigger="solar", body="High priority body.", priority=1))
    await db.commit()
    result = await get_matching_rules("solar panel", db)
    assert result[0] == "High priority body."
