from sqlalchemy import create_engine, inspect, insert, text
from types import SimpleNamespace

from app.db.models import Base, Product
from app.db.schema import upgrade_schema


def test_upgrade_legacy_products_backfills_and_is_repeatable(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE products (id INTEGER PRIMARY KEY, country VARCHAR(2), price_xaf FLOAT)"
        ))
        connection.execute(text(
            "INSERT INTO products (id, country, price_xaf) VALUES "
            "(1, 'CM', 125000), (2, 'NG', 240000), (3, NULL, NULL)"
        ))
        upgrade_schema(connection)

        columns = {column["name"] for column in inspect(connection).get_columns("products")}
        assert {"price_local", "status"} <= columns
        rows = connection.execute(text(
            "SELECT country, price_local, status FROM products ORDER BY id"
        )).all()
        assert rows == [
            ("CM", 125000.0, "active"),
            ("NG", None, "active"),
            (None, None, "active"),
        ]

        upgrade_schema(connection)
        assert connection.execute(text(
            "SELECT country, price_local, status FROM products ORDER BY id"
        )).all() == rows


def test_upgrade_accepts_fresh_orm_schema(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    with engine.begin() as connection:
        Base.metadata.create_all(connection)
        upgrade_schema(connection)
        columns = {column["name"] for column in inspect(connection).get_columns("products")}
        assert {"price_local", "status"} <= columns

        connection.execute(insert(Product).values(
            name="Existing", sku="EXISTING", country="CM",
            price_xaf=125000, price_local=130000,
        ))
        upgrade_schema(connection)
        assert connection.execute(text(
            "SELECT price_local, status FROM products WHERE sku = 'EXISTING'"
        )).one() == (130000.0, "active")


def test_cleared_cameroon_price_stays_null_after_repeated_restarts(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'restart.db'}"
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE products (id INTEGER PRIMARY KEY, country VARCHAR(2), price_xaf FLOAT)"
        ))
        connection.execute(text("INSERT INTO products VALUES (1, 'CM', 125000)"))
        upgrade_schema(connection)
        assert connection.execute(text("SELECT price_local FROM products")).scalar_one() == 125000
        connection.execute(text("UPDATE products SET price_local = NULL"))
    engine.dispose()

    for _ in range(2):
        restarted = create_engine(database_url)
        with restarted.begin() as connection:
            upgrade_schema(connection)
            assert connection.execute(text("SELECT price_local FROM products")).scalar_one() is None
        restarted.dispose()


def test_existing_local_price_column_is_not_backfilled(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'current.db'}")
    with engine.begin() as connection:
        Base.metadata.create_all(connection)
        connection.execute(insert(Product).values(
            name="Contact for price", sku="CLEARED-CM", country="CM",
            price_xaf=125000, price_local=None,
        ))
        upgrade_schema(connection)
        assert connection.execute(text("SELECT price_local FROM products")).scalar_one() is None


def test_postgresql_adds_columns_with_concurrent_startup_guards(monkeypatch):
    from app.db import schema

    events = []

    class Inspector:
        def get_table_names(self):
            return ["products"]

        def get_columns(self, table):
            assert table == "products"
            events.append("inspect columns")
            return [{"name": name} for name in ("id", "country", "price_xaf")]

    connection = SimpleNamespace(
        dialect=SimpleNamespace(name="postgresql"),
        execute=lambda statement: events.append(str(statement)),
    )
    monkeypatch.setattr(schema, "inspect", lambda _: Inspector())
    upgrade_schema(connection)

    additions = [statement for statement in events if statement.startswith("ALTER TABLE")]
    assert additions == [
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS price_local FLOAT",
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'active'",
    ]
    # Serialize inspection with the additive upgrade: only the process that sees
    # the legacy schema under the lock may perform the one-time price backfill.
    assert events.index("LOCK TABLE products IN ACCESS EXCLUSIVE MODE") < events.index("inspect columns")
