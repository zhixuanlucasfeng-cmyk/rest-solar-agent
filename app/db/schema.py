from sqlalchemy import inspect, text


def upgrade_schema(connection) -> None:
    inspector = inspect(connection)
    if "products" not in inspector.get_table_names():
        return
    dialect = connection.dialect.name
    if dialect == "postgresql":
        # Keep the inspection and one-time backfill in the same serialized
        # upgrade, even when multiple workers start against the legacy schema.
        connection.execute(text("LOCK TABLE products IN ACCESS EXCLUSIVE MODE"))
    columns = {column["name"] for column in inspector.get_columns("products")}
    column_guard = "IF NOT EXISTS " if dialect == "postgresql" else ""

    added_local_price = "price_local" not in columns
    if added_local_price:
        connection.execute(text(f"ALTER TABLE products ADD COLUMN {column_guard}price_local FLOAT"))
    if "status" not in columns:
        connection.execute(text(
            f"ALTER TABLE products ADD COLUMN {column_guard}status VARCHAR(20) NOT NULL DEFAULT 'active'"
        ))

    connection.execute(text(
        "UPDATE products SET status = 'active' WHERE status IS NULL OR status = ''"
    ))
    # Only the legacy schema upgrade may infer prices. A later null is an
    # intentional "contact for price" choice and must survive every restart.
    if added_local_price:
        connection.execute(text(
            "UPDATE products SET price_local = price_xaf "
            "WHERE country = 'CM' AND price_local IS NULL AND price_xaf IS NOT NULL"
        ))
