import pytest
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport
from app.main import app


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
