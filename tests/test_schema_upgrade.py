from sqlalchemy import create_engine, inspect, insert, text

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
