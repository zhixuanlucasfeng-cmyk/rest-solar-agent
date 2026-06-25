from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import Conversation, Message, Rule


async def test_create_rule(db: AsyncSession):
    rule = Rule(name="test_rule", trigger="price", body="Never invent prices.", priority=1)
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    assert rule.id is not None
    assert rule.active is True


async def test_create_conversation_and_message(db: AsyncSession):
    conv = Conversation(session_id="abc-123", language="en")
    db.add(conv)
    await db.flush()
    msg = Message(conversation_id=conv.id, role="user", content="Hello")
    db.add(msg)
    await db.commit()
    assert msg.id is not None
    assert msg.tool_name is None
