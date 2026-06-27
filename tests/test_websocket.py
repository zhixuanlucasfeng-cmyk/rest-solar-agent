import pytest
import json
from httpx import AsyncClient
from httpx_ws import aconnect_ws
from httpx_ws.transport import ASGIWebSocketTransport
from app.main import app


@pytest.mark.asyncio
async def test_ws_connect_and_ai_reply(monkeypatch):
    tokens = ["Hello", " from", " AI"]

    async def fake_run_stream(message, session_id, db):
        for t in tokens:
            yield t

    monkeypatch.setattr("app.api.ws.run_stream", fake_run_stream)

    async def fake_redis_get(key):
        return None  # mode = ai

    import app.api.ws as ws_mod
    import unittest.mock as mock

    fake_redis = mock.AsyncMock()
    fake_redis.get = mock.AsyncMock(return_value=None)
    fake_redis.aclose = mock.AsyncMock()
    monkeypatch.setattr(ws_mod, "get_redis", lambda: fake_redis)

    transport = ASGIWebSocketTransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async with aconnect_ws("/ws/1", client) as ws:
            await ws.send_text(json.dumps({"message": "hi"}))
            msg1 = json.loads(await ws.receive_text())
            assert msg1["type"] == "start"
            collected = []
            while True:
                msg = json.loads(await ws.receive_text())
                if msg["type"] == "end":
                    break
                if msg["type"] == "token":
                    collected.append(msg["text"])
            assert "".join(collected) == "Hello from AI"
