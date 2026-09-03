import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession

from app.db.models import Base, AdminUser
from app.db.session import DATABASE_URL
from app.admin.auth import hash_password
from app.api.chat import router as chat_router
from app.api.ws import router as ws_router
from app.api.products import router as products_router
from app.api.media import router as media_router
from app.admin.routes import router as admin_router
from app.media import media_url


async def _seed_admin_users(session: AsyncSession) -> None:
    """Seed the superadmin and the per-country admins from env vars.

    Idempotent per email; runs on every startup so accounts survive Render's
    ephemeral disk (free tier sqlite doesn't persist across redeploys).
    """
    from app.countries import is_valid_country

    async def _ensure(email: str, password: str, role: str, country: str | None):
        if not email or not password:
            return
        exists = await session.scalar(select(AdminUser).where(AdminUser.email == email))
        if exists:
            return
        session.add(AdminUser(
            email=email, password_hash=hash_password(password), role=role, country=country,
        ))

    await _ensure(os.getenv("ADMIN_EMAIL", ""), os.getenv("ADMIN_PASSWORD", ""), "superadmin", None)

    def _seed_country_users(raw: str, role: str, email_suffix: str):
        for entry in (e.strip() for e in raw.split(",") if e.strip()):
            if ":" not in entry:
                print(f"[seed] skipping malformed entry: {entry!r}")
                continue
            key, _, pw = entry.partition(":")
            key = key.strip().upper()
            cc = key.split("-")[0]
            if not is_valid_country(cc):
                print(f"[seed] skipping unknown country code: {cc!r}")
                continue
            yield f"{key.lower()}-{email_suffix}@restsolar.com", pw.strip(), role, cc

    for email, pw, role, cc in _seed_country_users(
        os.getenv("SEED_COUNTRY_ADMINS", ""), "country_admin", "admin"
    ):
        await _ensure(email, pw, role, cc)

    # e.g. SEED_COUNTRY_AGENTS="CM:pw1,CM-2:pw2,NG:pw3" -> cm-agent@, cm-2-agent@, ng-agent@
    for email, pw, role, cc in _seed_country_users(
        os.getenv("SEED_COUNTRY_AGENTS", ""), "agent", "agent"
    ):
        await _ensure(email, pw, role, cc)

    await session.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    if os.getenv("RENDER") and not os.getenv("DATABASE_URL"):
        raise RuntimeError("DATABASE_URL must be set in production")
    engine = create_async_engine(DATABASE_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSession(engine) as session:
        await _seed_admin_users(session)
    await engine.dispose()
    yield


app = FastAPI(title="RestarSolar AI Agent", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
templates.env.globals["media_url"] = media_url

app.include_router(chat_router)
app.include_router(ws_router)
app.include_router(products_router)
app.include_router(media_router)
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
