from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.models import Rule


async def get_matching_rules(text: str, db: AsyncSession) -> list[str]:
    """Return body text of active rules whose trigger keyword appears in text.

    Rules are sorted by priority (lower number = higher priority).
    A rule with an empty trigger always matches.
    Trigger field stores slash-separated keywords: "price/tariff/duty".
    """
    stmt = select(Rule).where(Rule.active.is_(True)).order_by(Rule.priority)
    result = await db.execute(stmt)
    rules = result.scalars().all()

    text_lower = text.lower()
    matched: list[str] = []

    for rule in rules:
        if not rule.trigger:
            matched.append(rule.body)
            continue
        keywords = [kw.strip() for kw in rule.trigger.split("/") if kw.strip()]
        if any(kw in text_lower for kw in keywords):
            matched.append(rule.body)

    return matched
