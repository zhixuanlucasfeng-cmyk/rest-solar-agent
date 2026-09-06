import json
import os
import redis.asyncio as aioredis
from redis.exceptions import RedisError
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.session import get_db
from app.db.models import Conversation, AdminUser, Message
from app.countries import normalize_country
from app.agent.orchestrator import run_stream
from app.api.ws_manager import manager

router = APIRouter()

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")


def get_redis():
    # ponytail: fail fast (3s) instead of hanging on the OS-level TCP timeout
    # (30-120s) when REDIS_URL is unset/unreachable — that hang was silently
    # killing handoff websockets with no error surfaced anywhere.
    return aioredis.from_url(
        REDIS_URL, decode_responses=True,
        socket_connect_timeout=3, socket_timeout=3, retry_on_timeout=False,
    )


async def _queue_snapshot(redis, db: AsyncSession, user: AdminUser) -> list[dict]:
    """Conversations currently waiting for a human or in a live takeover, scoped
    to the admin's country. ponytail: Redis KEYS scan + per-conv query — fine at
    a handful of concurrent chats; index the state in a DB column if it grows."""
    try:
        keys = await redis.keys("conv:*:mode")
        keys = list(keys) if keys else []
    except TypeError:  # mocked redis in tests
        keys = []
    except RedisError:
        return []
    items = []
    for key in keys:
        mode = await redis.get(key)
        if mode not in ("waiting", "human"):
            continue
        try:
            conv_id = int(key.split(":")[1])
        except (IndexError, ValueError):
            continue
        conv = (await db.execute(
            select(Conversation).where(Conversation.id == conv_id)
        )).scalar_one_or_none()
        if conv is None:
            continue
        if user.country is not None and conv.country != user.country:
            continue
        last = (await db.execute(
            select(Message).where(Message.conversation_id == conv_id)
            .order_by(Message.created_at.desc()).limit(1)
        )).scalar_one_or_none()
        agent = await redis.get(f"conv:{conv_id}:agent")
        items.append({
            "conversation_id": conv_id,
            "country": conv.country,
            "mode": mode,
            "agent_id": int(agent) if agent else None,
            "preview": (last.content[:80] if last else ""),
        })
    return items


@router.websocket("/ws/admin/{user_id}")
async def admin_ws(user_id: int, ws: WebSocket, db: AsyncSession = Depends(get_db)):
    # Verify JWT before accepting
    from app.admin.auth import decode_access_token
    from jose import JWTError
    token = ws.cookies.get("admin_token")
    if not token:
        await ws.close(code=4003)
        return
    try:
        payload = decode_access_token(token)
        token_user_id = int(payload.get("sub", -1))
    except (JWTError, ValueError):
        await ws.close(code=4003)
        return
    if token_user_id != user_id:
        await ws.close(code=4003)
        return

    user = (await db.execute(
        select(AdminUser).where(AdminUser.id == user_id)
    )).scalar_one_or_none()
    if user is None:
        await ws.close(code=4003)
        return

    async def _visible_conv(conv_db_id: int):
        conv = (await db.execute(
            select(Conversation).where(Conversation.id == conv_db_id)
        )).scalar_one_or_none()
        if conv is None:
            return None
        if user.country is not None and conv.country != user.country:
            return None
        return conv

    await manager.connect_admin(user_id, ws, user.country)
    redis = get_redis()
    try:
        await ws.send_json({
            "type": "queue_snapshot",
            "items": await _queue_snapshot(redis, db, user),
        })

        while True:
            text = await ws.receive_text()
            data = json.loads(text)
            action = data.get("action")

            if action == "takeover":
                conv = await _visible_conv(int(data["conversation_id"]))
                if conv is None:
                    continue
                try:
                    await redis.set(f"conv:{conv.id}:mode", "human")
                    await redis.set(f"conv:{conv.id}:agent", str(user_id))
                except RedisError:
                    await ws.send_json({"type": "error", "text": "Live agent queue is unavailable — try again shortly."})
                    continue
                await manager.broadcast_to_admins_in_country(conv.country, {
                    "type": "handoff_claimed",
                    "conversation_id": conv.id,
                    "agent_id": user_id,
                })
                await manager.send_to_customer_by_db_id(conv.id, {
                    "type": "status",
                    "text": "You have been connected to a live agent.",
                })

            elif action == "release":
                conv = await _visible_conv(int(data["conversation_id"]))
                if conv is None:
                    continue
                try:
                    await redis.set(f"conv:{conv.id}:mode", "ai")
                    await redis.delete(f"conv:{conv.id}:agent")
                except RedisError:
                    await ws.send_json({"type": "error", "text": "Live agent queue is unavailable — try again shortly."})
                    continue
                await manager.broadcast_to_admins_in_country(conv.country, {
                    "type": "handoff_closed",
                    "conversation_id": conv.id,
                })
                await manager.send_to_customer_by_db_id(conv.id, {
                    "type": "status",
                    "text": "You have been reconnected to the AI assistant.",
                })

            elif action == "message":
                conv = await _visible_conv(int(data["conversation_id"]))
                if conv is None:
                    continue
                reply = data.get("text", "")
                db.add(Message(conversation_id=conv.id, role="agent", content=reply))
                await db.commit()
                await manager.send_to_customer_by_db_id(conv.id, {
                    "type": "agent_message",
                    "text": reply,
                })
    except WebSocketDisconnect:
        manager.disconnect_admin(user_id)
        await redis.aclose()


@router.websocket("/ws/{conversation_id}")
async def customer_ws(
    conversation_id: int,
    ws: WebSocket,
    country: str = Query("CM"),
    db: AsyncSession = Depends(get_db),
):
    redis = get_redis()
    session_id = f"conv-{conversation_id}"

    # Create/find conversation immediately and send DB id to client
    result = await db.execute(select(Conversation).where(Conversation.session_id == session_id))
    conv = result.scalar_one_or_none()
    if not conv:
        conv = Conversation(session_id=session_id, language="en", country=normalize_country(country))
        db.add(conv)
        await db.flush()
        await db.commit()

    # Connect with both channel_id (URL int) and db_id (DB primary key)
    await manager.connect_customer(conversation_id, conv.id, ws)

    # Send DB conv id so admin dashboard and client share the same id
    await manager.send_to_customer_by_channel(conversation_id, {"type": "init", "conv_id": conv.id})

    try:
        while True:
            text = await ws.receive_text()
            data = json.loads(text)
            action = data.get("action")

            if action == "request_human":
                try:
                    await redis.set(f"conv:{conv.id}:mode", "waiting")
                    await manager.broadcast_to_admins_in_country(conv.country, {
                        "type": "handoff_request",
                        "conversation_id": conv.id,
                        "country": conv.country,
                    })
                    await manager.send_to_customer_by_channel(conversation_id, {
                        "type": "status",
                        "text": "Connecting you to our team — please hold on.",
                    })
                except RedisError:
                    await manager.send_to_customer_by_channel(conversation_id, {
                        "type": "status",
                        "text": "Live agents are unavailable right now — I'll keep helping in the meantime.",
                    })
                continue

            message = data.get("message", "")

            # Use DB conv.id for Redis (so admin takeover aligns). Fail open to
            # AI mode if Redis is unreachable rather than dropping the socket.
            try:
                mode = await redis.get(f"conv:{conv.id}:mode") or "ai"
            except RedisError:
                mode = "ai"

            if mode in ("human", "waiting"):
                # Persist so the agent sees the full thread when they open it.
                db.add(Message(conversation_id=conv.id, role="user", content=message))
                await db.commit()
                agent_id_str = await redis.get(f"conv:{conv.id}:agent")
                if agent_id_str:
                    await manager.send_to_admin(int(agent_id_str), {
                        "type": "customer_message",
                        "conversation_id": conv.id,
                        "text": message,
                    })
                else:
                    # still queued — nudge the country's agents again
                    await manager.broadcast_to_admins_in_country(conv.country, {
                        "type": "handoff_request",
                        "conversation_id": conv.id,
                        "country": conv.country,
                    })
                await manager.send_to_customer_by_channel(conversation_id, {
                    "type": "status",
                    "text": "Message sent to our team.",
                })
            else:
                await manager.send_to_customer_by_channel(conversation_id, {"type": "start"})
                async for token in run_stream(message, session_id, db):
                    await manager.send_to_customer_by_channel(conversation_id, {
                        "type": "token",
                        "text": token,
                    })
                await manager.send_to_customer_by_channel(conversation_id, {"type": "end"})
    except WebSocketDisconnect:
        manager.disconnect_customer(conversation_id, conv.id)
        await redis.aclose()
