from sqlalchemy import inspect, text


def upgrade_schema(connection) -> None:
    inspector = inspect(connection)
    if "products" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("products")}
    dialect = connection.dialect.name

    if "price_local" not in columns:
        connection.execute(text("ALTER TABLE products ADD COLUMN price_local FLOAT"))
    if "status" not in columns:
        default = "DEFAULT 'active'" if dialect == "sqlite" else "DEFAULT 'active'"
        connection.execute(text(
            f"ALTER TABLE products ADD COLUMN status VARCHAR(20) NOT NULL {default}"
        ))

    connection.execute(text(
        "UPDATE products SET status = 'active' WHERE status IS NULL OR status = ''"
    ))
    connection.execute(text(
        "UPDATE products SET price_local = price_xaf "
        "WHERE country = 'CM' AND price_local IS NULL AND price_xaf IS NOT NULL"
    ))
