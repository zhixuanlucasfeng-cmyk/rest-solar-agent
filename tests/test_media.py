import io

import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from starlette.datastructures import UploadFile, Headers

from app.main import app
from app.db.models import Base, MediaAsset
from app.media import media_url, save_upload


def test_media_url_prefers_asset_over_path():
    assert media_url(7, "static/x.jpg") == "/media/7"
    assert media_url(None, "static/x.jpg") == "/static/x.jpg"
    assert media_url(None, "/static/x.jpg") == "/static/x.jpg"
    assert media_url(None, None) is None


@pytest.mark.asyncio
async def test_save_upload_and_serve():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    upload = UploadFile(
        filename="p.jpg",
        file=io.BytesIO(b"\xff\xd8\xffDATA"),
        headers=Headers({"content-type": "image/jpeg"}),
    )
    async with Session() as s:
        asset_id = await save_upload(s, upload, "image")
        await s.commit()

    from app.db.session import get_db

    async def override_get_db():
        async with Session() as s:
            yield s

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/media/{asset_id}")
    app.dependency_overrides.clear()
    await engine.dispose()

    assert resp.status_code == 200
    assert resp.content == b"\xff\xd8\xffDATA"
    assert resp.headers["content-type"] == "image/jpeg"


@pytest.mark.asyncio
async def test_media_404():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    from app.db.session import get_db

    async def override_get_db():
        async with Session() as s:
            yield s

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/media/999999")
    app.dependency_overrides.clear()
    await engine.dispose()

    assert resp.status_code == 404
