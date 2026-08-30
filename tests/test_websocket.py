import pytest
import json
import unittest.mock as mock
from contextlib import asynccontextmanager
from httpx import AsyncClient
from httpx_ws import aconnect_ws
from httpx_ws.transport import ASGIWebSocketTransport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool
from app.main import app
from app.db.models import Base, Conversation
from app.db.session import get_db


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
            # C1 fix: server sends init with DB conv_id before any user message
            init_msg = json.loads(await ws.receive_text())
            assert init_msg["type"] == "init"
            assert isinstance(init_msg["conv_id"], int) and init_msg["conv_id"] > 0

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


@asynccontextmanager
async def ws_client_factory(path, monkeypatch):
    """Open a customer websocket against an isolated in-memory DB.

    Yields (ws, Session) where Session is an async_sessionmaker bound to the
    same engine the ws handler wrote to, so the created Conversation can be
    read back.
    """
    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(eng, expire_on_commit=False)

    async def _get_db():
        async with Session() as s:
            yield s

    app.dependency_overrides[get_db] = _get_db

    fake_redis = mock.AsyncMock()
    fake_redis.get = mock.AsyncMock(return_value=None)
    fake_redis.aclose = mock.AsyncMock()
    monkeypatch.setattr("app.api.ws.get_redis", lambda: fake_redis)

    transport = ASGIWebSocketTransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            async with aconnect_ws(path, client) as ws:
                yield ws, Session
    finally:
        app.dependency_overrides.pop(get_db, None)
        await eng.dispose()


async def _country_for(path, monkeypatch, session_id):
    async with ws_client_factory(path, monkeypatch) as (ws, Session):
        init = json.loads(await ws.receive_text())
        assert init["type"] == "init"
        async with Session() as db:
            conv = (
                await db.execute(
                    select(Conversation).where(Conversation.session_id == session_id)
                )
            ).scalar_one()
            return conv.country


async def test_ws_stores_country(monkeypatch):
    assert await _country_for("/ws/424242?country=NG", monkeypatch, "conv-424242") == "NG"


async def test_ws_missing_country_defaults_cm(monkeypatch):
    assert await _country_for("/ws/424243", monkeypatch, "conv-424243") == "CM"


async def test_ws_invalid_country_defaults_cm(monkeypatch):
    assert await _country_for("/ws/424244?country=US", monkeypatch, "conv-424244") == "CM"
