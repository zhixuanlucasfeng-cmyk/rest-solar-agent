#!/usr/bin/env python
"""
Migrate the local SQLite dev database to the current schema.
Idempotent: creates missing tables and adds missing columns (no drops).
Preserves all existing rows.
"""

import os
import sqlite3
import sys
from sqlalchemy import create_engine, String, Integer, Float, Text
from app.db.models import Base

# Get database URL from environment or use default
db_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./data/rest_solar.db")

# Convert aiosqlite URL to plain sqlite3 URL for synchronous operations
sqlite_url = db_url.replace("sqlite+aiosqlite:///", "sqlite:///").replace("sqlite+aiosqlite://", "sqlite://")
db_path = sqlite_url.replace("sqlite:///", "").replace("sqlite://", "")

print(f"Migrating database: {db_path}")

# Create the engine and run metadata.create_all to create missing tables
engine = create_engine(sqlite_url)
Base.metadata.create_all(engine)
print("✓ Created missing tables (media_assets if it didn't exist)")

# Get a plain sqlite3 connection for PRAGMA and ALTER operations
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Define columns to ensure: (table_name, column_name, sql_definition)
columns_to_add = [
    ("conversations", "country", "VARCHAR(2)"),
    ("products", "country", "VARCHAR(2)"),
    ("products", "image_asset_id", "INTEGER"),
    ("products", "datasheet_asset_id", "INTEGER"),
    ("product_images", "asset_id", "INTEGER"),
    ("admin_users", "country", "VARCHAR(2)"),
    ("orders", "country", "VARCHAR(2) NOT NULL DEFAULT 'CM'"),
    ("orders", "conversation_id", "INTEGER"),
    ("orders", "contact", "VARCHAR(200)"),
    ("orders", "items", "TEXT NOT NULL DEFAULT ''"),
    ("orders", "notes", "TEXT"),
    ("orders", "total_xaf", "FLOAT"),
]

added = []

for table_name, column_name, column_def in columns_to_add:
    # Check if column exists using PRAGMA table_info
    cursor.execute(f"PRAGMA table_info({table_name})")
    existing_columns = {row[1] for row in cursor.fetchall()}

    if column_name not in existing_columns:
        # Add the column
        alter_sql = f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_def}"
        cursor.execute(alter_sql)
        added.append(f"{table_name}.{column_name}")
        print(f"✓ Added {table_name}.{column_name}")
    else:
        print(f"  (skip {table_name}.{column_name}, already exists)")

conn.commit()
conn.close()

if added:
    print(f"\nAdded {len(added)} columns:")
    for col in added:
        print(f"  - {col}")
else:
    print("\nNo new columns to add; database is current.")

print("\n✓ Migration complete!")
