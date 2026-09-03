import json
import unittest.mock as mock
from contextlib import asynccontextmanager

import pytest
from httpx import AsyncClient
from httpx_ws import aconnect_ws
from httpx_ws.transport import ASGIWebSocketTransport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.db.models import Base, Conversation, Message
from app.db.session import get_db
from app.api.ws_manager import ConnectionManager


# --- unit: country-scoped admin broadcast -----------------------------------

class _FakeWS:
    def __init__(self):
        self.sent = []

    async def send_json(self, data):
        self.sent.append(data)


async def test_broadcast_targets_country_and_superadmins():
    m = ConnectionManager()
    ng, cm, sup = _FakeWS(), _FakeWS(), _FakeWS()
    m.admin = {1: ng, 2: cm, 3: sup}
    m.admin_country = {1: "NG", 2: "CM", 3: None}

    await m.broadcast_to_admins_in_country("NG", {"x": 1})

    assert ng.sent == [{"x": 1}]      # same country
    assert sup.sent == [{"x": 1}]     # superadmin sees all
    assert cm.sent == []              # other country excluded


# --- integration: customer message is persisted while queued/live ----------

@asynccontextmanager
async def customer_ws(path, redis_mode):
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

    async def _get(key):
        return redis_mode if key.endswith(":mode") else None

    fake_redis.get = mock.AsyncMock(side_effect=_get)
    fake_redis.set = mock.AsyncMock()
    fake_redis.aclose = mock.AsyncMock()
    with mock.patch("app.api.ws.get_redis", lambda: fake_redis):
        transport = ASGIWebSocketTransport(app=app)
        try:
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                async with aconnect_ws(path, client) as ws:
                    yield ws, Session, fake_redis
        finally:
            app.dependency_overrides.pop(get_db, None)
            await eng.dispose()


async def _messages(Session, conv_session_id):
    async with Session() as db:
        conv = (await db.execute(
            select(Conversation).where(Conversation.session_id == conv_session_id)
        )).scalar_one()
        return (await db.execute(
            select(Message).where(Message.conversation_id == conv.id).order_by(Message.created_at)
        )).scalars().all()


async def test_request_human_sets_waiting_mode():
    async with customer_ws("/ws/700001", redis_mode=None) as (ws, Session, fake_redis):
        assert json.loads(await ws.receive_text())["type"] == "init"
        await ws.send_text(json.dumps({"action": "request_human"}))
        status = json.loads(await ws.receive_text())
        assert status["type"] == "status"
        fake_redis.set.assert_any_call("conv:1:mode", "waiting")


async def test_customer_message_persisted_when_waiting():
    async with customer_ws("/ws/700002", redis_mode="waiting") as (ws, Session, _):
        assert json.loads(await ws.receive_text())["type"] == "init"
        await ws.send_text(json.dumps({"message": "my inverter is dead"}))
        assert json.loads(await ws.receive_text())["type"] == "status"
        msgs = await _messages(Session, "conv-700002")

    assert [(m.role, m.content) for m in msgs] == [("user", "my inverter is dead")]


async def test_ai_mode_does_not_persist_via_handoff_path(monkeypatch):
    async def fake_run_stream(message, session_id, db):
        for t in ["ok"]:
            yield t

    monkeypatch.setattr("app.api.ws.run_stream", fake_run_stream)
    async with customer_ws("/ws/700003", redis_mode=None) as (ws, Session, _):
        assert json.loads(await ws.receive_text())["type"] == "init"
        await ws.send_text(json.dumps({"message": "hi"}))
        while json.loads(await ws.receive_text())["type"] != "end":
            pass
        # orchestrator is faked, so it writes nothing; handoff path must not either
        msgs = await _messages(Session, "conv-700003")
    assert msgs == []
