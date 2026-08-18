import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession

from app.db.models import Base, AdminUser
from app.db.session import DATABASE_URL
from app.admin.auth import hash_password
from app.api.chat import router as chat_router
from app.api.ws import router as ws_router
from app.admin.routes import router as admin_router


async def _seed_admin_user(session: AsyncSession) -> None:
    """Create the first superadmin account from env vars if none exists yet.

    Runs on every startup so the account survives Render's ephemeral disk
    (free tier sqlite doesn't persist across redeploys without a mounted disk).
    """
    count = (await session.execute(select(func.count()).select_from(AdminUser))).scalar_one()
    if count > 0:
        return
    email = os.getenv("ADMIN_EMAIL")
    password = os.getenv("ADMIN_PASSWORD")
    if not email or not password:
        return
    session.add(AdminUser(email=email, password_hash=hash_password(password), role="superadmin"))
    await session.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    engine = create_async_engine(DATABASE_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSession(engine) as session:
        await _seed_admin_user(session)
    await engine.dispose()
    yield


app = FastAPI(title="Rest Solar AI Agent", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

app.include_router(chat_router)
app.include_router(ws_router)
app.include_router(admin_router)


@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/chat")


@app.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request):
    return templates.TemplateResponse(request=request, name="chat.html")


@app.get("/mobile", response_class=HTMLResponse)
async def mobile_page(request: Request):
    return templates.TemplateResponse(request=request, name="mobile.html")


@app.get("/health")
async def health():
    return {"status": "ok"}
