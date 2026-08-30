import pytest
import yaml
from pathlib import Path
from app.main import app, lifespan


def test_render_yaml_does_not_pin_sqlite():
    cfg = yaml.safe_load(Path("render.yaml").read_text())
    env = cfg["services"][0]["envVars"]
    db = next((e for e in env if e["key"] == "DATABASE_URL"), None)
    # DATABASE_URL must be set in the dashboard (sync: false), never a literal sqlite value
    assert db is None or "value" not in db or "sqlite" not in str(db.get("value", ""))


async def test_lifespan_fails_fast_without_database_url_on_render(monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        async with lifespan(app):
            pass


async def test_lifespan_ok_when_not_on_render(monkeypatch):
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr("app.main.DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    async with lifespan(app):
        pass
