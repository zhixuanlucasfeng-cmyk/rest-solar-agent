from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.agent.orchestrator import run, run_stream

router = APIRouter()


class ChatRequest(BaseModel):
    message: str
    session_id: str


class ChatResponse(BaseModel):
    reply: str
    language: str


@router.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, db: AsyncSession = Depends(get_db)):
    result = await run(req.message, req.session_id, db)
    return ChatResponse(**result)


@router.post("/api/chat/stream")
async def chat_stream(req: ChatRequest, db: AsyncSession = Depends(get_db)):
    async def token_gen():
        async for token in run_stream(req.message, req.session_id, db):
            yield token

    return StreamingResponse(token_gen(), media_type="text/plain; charset=utf-8")
