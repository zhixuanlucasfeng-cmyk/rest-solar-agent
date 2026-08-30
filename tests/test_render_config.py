import yaml
from pathlib import Path


def test_render_yaml_does_not_pin_sqlite():
    cfg = yaml.safe_load(Path("render.yaml").read_text())
    env = cfg["services"][0]["envVars"]
    db = next((e for e in env if e["key"] == "DATABASE_URL"), None)
    # DATABASE_URL must be set in the dashboard (sync: false), never a literal sqlite value
    assert db is None or "value" not in db or "sqlite" not in str(db.get("value", ""))
