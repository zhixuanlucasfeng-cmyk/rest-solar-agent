from app.db import session


def test_database_pool_checks_connections_before_use():
    """Neon can close idle connections while Render keeps the app alive."""
    assert session.engine.sync_engine.pool._pre_ping is True
