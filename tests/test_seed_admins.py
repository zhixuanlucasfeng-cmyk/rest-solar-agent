import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.db.models import Base, AdminUser
from app.main import _seed_admin_users


async def _session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False), engine


@pytest.mark.asyncio
async def test_seeds_superadmin_and_country_admins(monkeypatch):
    monkeypatch.setenv("ADMIN_EMAIL", "boss@restsolar.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "bosspw")
    monkeypatch.setenv("SEED_COUNTRY_ADMINS", "cm:p1,ng:p2,sd:p3,ml:p4")
    Session, engine = await _session()
    async with Session() as s:
        await _seed_admin_users(s)
        await _seed_admin_users(s)  # idempotent
    async with Session() as s:
        users = (await s.execute(select(AdminUser))).scalars().all()
    await engine.dispose()

    by_email = {u.email: u for u in users}
    assert by_email["boss@restsolar.com"].role == "superadmin"
    assert by_email["boss@restsolar.com"].country is None
    assert by_email["ng-admin@restsolar.com"].role == "country_admin"
    assert by_email["ng-admin@restsolar.com"].country == "NG"
    assert len(users) == 5


@pytest.mark.asyncio
async def test_malformed_country_admin_entry_is_skipped(monkeypatch):
    monkeypatch.delenv("ADMIN_EMAIL", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    monkeypatch.setenv("SEED_COUNTRY_ADMINS", "cm:p1,garbage,xx:p9,ng:p2")
    Session, engine = await _session()
    async with Session() as s:
        await _seed_admin_users(s)
    async with Session() as s:
        countries = {u.country for u in (await s.execute(select(AdminUser))).scalars().all()}
    await engine.dispose()
    assert countries == {"CM", "NG"}
