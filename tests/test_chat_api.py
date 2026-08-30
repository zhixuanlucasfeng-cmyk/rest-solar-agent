import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.main import app
from app.db.models import Base, Conversation
from app.db.session import get_db


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


@patch("app.api.chat.run", new_callable=AsyncMock,
       return_value={"reply": "We sell 50W to 550W panels.", "language": "en"})
async def test_post_chat_returns_reply(mock_run, client):
    resp = await client.post("/api/chat", json={
        "message": "What panels do you sell?",
        "session_id": "test-session-1"
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["reply"] == "We sell 50W to 550W panels."
    assert data["language"] == "en"


@patch("app.api.chat.run", new_callable=AsyncMock,
       return_value={"reply": "Nous vendons des panneaux.", "language": "fr"})
async def test_post_chat_french(mock_run, client):
    resp = await client.post("/api/chat", json={
        "message": "Quels panneaux vendez-vous ?",
        "session_id": "test-session-2"
    })
    assert resp.status_code == 200
    assert resp.json()["language"] == "fr"


async def test_post_chat_missing_field(client):
    resp = await client.post("/api/chat", json={"session_id": "x"})
    assert resp.status_code == 422


async def test_get_chat_page(client):
    resp = await client.get("/chat")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


def test_chat_request_accepts_country():
    from app.api.chat import ChatRequest
    req = ChatRequest(message="hi", session_id="s", country="NG")
    assert req.country == "NG"
    req2 = ChatRequest(message="hi", session_id="s")
    assert req2.country is None


@patch("app.agent.orchestrator.chat_complete", new_callable=AsyncMock)
async def test_chat_threads_country_into_conversation(mock_llm):
    msg = MagicMock()
    msg.content = "hi"
    msg.tool_calls = None
    mock_llm.return_value = msg

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async def override_get_db():
        async with Session() as s:
            yield s

    app.dependency_overrides[get_db] = override_get_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            await c.post("/api/chat", json={"message": "hello", "session_id": "cc-1", "country": "NG"})
            await c.post("/api/chat", json={"message": "hello", "session_id": "cc-2"})
        async with Session() as s:
            c1 = (await s.execute(select(Conversation).where(Conversation.session_id == "cc-1"))).scalar_one()
            c2 = (await s.execute(select(Conversation).where(Conversation.session_id == "cc-2"))).scalar_one()
        assert c1.country == "NG"
        assert c2.country is None
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()
