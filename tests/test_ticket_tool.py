import pytest
from unittest.mock import patch
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.db.models import Base
from app.tools.ticket import TicketTool


@pytest.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_ticket_created(db_session):
    with patch("app.tools.ticket.send_ticket_email") as mock_task:
        tool = TicketTool(db_session)
        result = await tool.call({"subject": "Panel broken", "body": "My panel stopped working after 2 days."})
    assert "ticket_id" in result
    assert result["status"] == "open"
    assert "confirmation" in result
    mock_task.assert_called_once()


@pytest.mark.asyncio
async def test_ticket_with_conversation_id(db_session):
    from app.db.models import Conversation
    conv = Conversation(session_id="sess-abc", language="fr")
    db_session.add(conv)
    await db_session.flush()

    with patch("app.tools.ticket.send_ticket_email"):
        tool = TicketTool(db_session)
        result = await tool.call({
            "subject": "Livraison retardée",
            "body": "Ma commande est en retard.",
            "conversation_id": conv.id,
        })
    assert result["ticket_id"] is not None


def test_definition():
    import asyncio
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async def _run():
        async with Session() as s:
            tool = TicketTool(s)
            defn = tool.definition()
            assert defn["function"]["name"] == "create_ticket"
            props = defn["function"]["parameters"]["properties"]
            assert "subject" in props
            assert "body" in props
    asyncio.run(_run())
