import json
import os
import redis.asyncio as aioredis
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.agent.orchestrator import run_stream
from app.api.ws_manager import manager

router = APIRouter()

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")


def get_redis():
    return aioredis.from_url(REDIS_URL, decode_responses=True)


@router.websocket("/ws/admin/{user_id}")
async def admin_ws(user_id: int, ws: WebSocket):
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
    try:
        while True:
            text = await ws.receive_text()
            data = json.loads(text)
            message = data.get("message", "")

            mode = await redis.get(f"conv:{conversation_id}:mode") or "ai"

            if mode == "human":
                agent_id_str = await redis.get(f"conv:{conversation_id}:agent")
                if agent_id_str:
                    await manager.send_to_admin(int(agent_id_str), {
                        "type": "customer_message",
                        "conversation_id": conversation_id,
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
        await redis.aclose()
