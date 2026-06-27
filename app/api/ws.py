import json
import os
import redis.asyncio as aioredis
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.session import get_db
from app.db.models import Conversation
from app.agent.orchestrator import run_stream
from app.api.ws_manager import manager

router = APIRouter()

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")


def get_redis():
    return aioredis.from_url(REDIS_URL, decode_responses=True)


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

    await manager.connect_admin(user_id, ws)
    redis = get_redis()
    try:
        while True:
            text = await ws.receive_text()
            data = json.loads(text)
            action = data.get("action")

            if action == "takeover":
                conv_id = int(data["conversation_id"])
                await redis.set(f"conv:{conv_id}:mode", "human")
                await redis.set(f"conv:{conv_id}:agent", str(user_id))
                await manager.send_to_customer(conv_id, {
                    "type": "status",
                    "text": "You have been connected to a live agent.",
                })

            elif action == "release":
                conv_id = int(data["conversation_id"])
                await redis.set(f"conv:{conv_id}:mode", "ai")
                await redis.delete(f"conv:{conv_id}:agent")
                await manager.send_to_customer(conv_id, {
                    "type": "status",
                    "text": "You have been reconnected to the AI assistant.",
                })

            elif action == "message":
                conv_id = int(data["conversation_id"])
                await manager.send_to_customer(conv_id, {
                    "type": "agent_message",
                    "text": data.get("text", ""),
                })
    except WebSocketDisconnect:
        manager.disconnect_admin(user_id)
        await redis.aclose()


@router.websocket("/ws/{conversation_id}")
async def customer_ws(conversation_id: int, ws: WebSocket, db: AsyncSession = Depends(get_db)):
    await manager.connect_customer(conversation_id, ws)
    redis = get_redis()
    session_id = f"conv-{conversation_id}"

    # Create/find conversation immediately and send DB id to client
    result = await db.execute(select(Conversation).where(Conversation.session_id == session_id))
    conv = result.scalar_one_or_none()
    if not conv:
        conv = Conversation(session_id=session_id, language="en")
        db.add(conv)
        await db.flush()
        await db.commit()

    # Send DB conv id so admin dashboard and client share the same id
    await manager.send_to_customer(conversation_id, {"type": "init", "conv_id": conv.id})

    # Register by DB id in manager so admin can reach this WS
    manager.customer[conv.id] = ws  # also keyed by DB id

    try:
        while True:
            text = await ws.receive_text()
            data = json.loads(text)
            message = data.get("message", "")

            # Use DB conv.id for Redis (so admin takeover aligns)
            mode = await redis.get(f"conv:{conv.id}:mode") or "ai"

            if mode == "human":
                agent_id_str = await redis.get(f"conv:{conv.id}:agent")
                if agent_id_str:
                    await manager.send_to_admin(int(agent_id_str), {
                        "type": "customer_message",
                        "conversation_id": conv.id,
                        "text": message,
                    })
                    await manager.send_to_customer(conversation_id, {
                        "type": "status",
                        "text": "Message sent to your agent.",
                    })
            else:
                await manager.send_to_customer(conversation_id, {"type": "start"})
                async for token in run_stream(message, session_id, db):
                    await manager.send_to_customer(conversation_id, {
                        "type": "token",
                        "text": token,
                    })
                await manager.send_to_customer(conversation_id, {"type": "end"})
    except WebSocketDisconnect:
        manager.disconnect_customer(conversation_id)
        manager.customer.pop(conv.id, None)  # also remove DB-id entry
        await redis.aclose()
