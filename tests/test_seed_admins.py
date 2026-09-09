import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.db.models import Base, AdminUser
from app.admin.auth import verify_password
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
async def test_changed_env_password_is_resynced_not_skipped(monkeypatch):
    """Rotating the env var must change the existing account's password."""
    monkeypatch.setenv("ADMIN_EMAIL", "boss@restsolar.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "oldpw")
    monkeypatch.setenv("SEED_COUNTRY_ADMINS", "cm:oldcm")
    monkeypatch.delenv("SEED_COUNTRY_AGENTS", raising=False)
    Session, engine = await _session()
    async with Session() as s:
        await _seed_admin_users(s)

    monkeypatch.setenv("ADMIN_PASSWORD", "newpw")
    monkeypatch.setenv("SEED_COUNTRY_ADMINS", "cm:newcm")
    async with Session() as s:
        await _seed_admin_users(s)

    async with Session() as s:
        users = (await s.execute(select(AdminUser))).scalars().all()
    await engine.dispose()

    by_email = {u.email: u for u in users}
    assert len(users) == 2, "re-seeding must update in place, not duplicate"
    boss = by_email["boss@restsolar.com"]
    assert verify_password("newpw", boss.password_hash)
    assert not verify_password("oldpw", boss.password_hash)
    assert boss.role == "superadmin" and boss.country is None
    assert verify_password("newcm", by_email["cm-admin@restsolar.com"].password_hash)


@pytest.mark.asyncio
async def test_seeds_country_agents(monkeypatch):
    monkeypatch.delenv("ADMIN_EMAIL", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("SEED_COUNTRY_ADMINS", raising=False)
    monkeypatch.setenv("SEED_COUNTRY_AGENTS", "cm:a1,ng:a2,sd:a3,ml:a4")
    Session, engine = await _session()
    async with Session() as s:
        await _seed_admin_users(s)
    async with Session() as s:
        users = (await s.execute(select(AdminUser))).scalars().all()
    await engine.dispose()

    by_email = {u.email: u for u in users}
    assert set(by_email) == {
        f"{cc}-agent@restsolar.com" for cc in ("cm", "ng", "sd", "ml")
    }
    assert by_email["cm-agent@restsolar.com"].role == "agent"
    assert by_email["cm-agent@restsolar.com"].country == "CM"
    assert verify_password("a1", by_email["cm-agent@restsolar.com"].password_hash)


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
