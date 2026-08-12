#!/usr/bin/env python3
"""
One-time SQLite to PostgreSQL migration script for TypeMeter.
Reads existing data from local SQLite database (typemeter.db)
and populates the cloud-hosted PostgreSQL database specified in DATABASE_URL.
Preserves primary key IDs, foreign keys, and resets sequence generators.
"""

import os
import sys
import sqlite3
import datetime
from dotenv import load_dotenv

load_dotenv()

def get_postgres_connection(db_url):
    """Parses DATABASE_URL and returns a raw psycopg2 connection."""
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
    except ImportError:
        print("[!] psycopg2-binary or psycopg2 is required for PostgreSQL migration.")
        print("    Install it via: pip install psycopg2-binary")
        sys.exit(1)

    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)

    conn = psycopg2.connect(db_url)
    return conn

def main():
    db_url = os.environ.get("DATABASE_URL")
    sqlite_path = os.environ.get("SQLITE_PATH", "typemeter.db")

    if not db_url:
        print("[!] Error: DATABASE_URL environment variable is not set.")
        print("    Usage: DATABASE_URL=postgresql://user:pass@host:5432/dbname python migrate_to_postgres.py")
        sys.exit(1)

    if not os.path.exists(sqlite_path):
        print(f"[!] Error: Source SQLite file '{sqlite_path}' does not exist.")
        sys.exit(1)

    print(f"[*] Starting migration from SQLite ('{sqlite_path}') -> Postgres...")

    # Connect to SQLite
    sqlite_conn = sqlite3.connect(sqlite_path)
    sqlite_conn.row_factory = sqlite3.Row

    # Connect to Postgres
    pg_conn = get_postgres_connection(db_url)

    # Import schema initialization helper from typemeter_db
    try:
        import typemeter_db
        typemeter_db.init_postgres_schema(pg_conn)
        print("[+] PostgreSQL schema verified/created successfully.")
    except Exception as e:
        print(f"[!] Failed to initialize Postgres schema: {e}")
        sys.exit(1)

    # List of tables to migrate in foreign key order
    tables = [
        ("users", "id", "users_id_seq"),
        ("global_priors", None, None),
        ("unigram_stats", None, None),
        ("bigram_stats", None, None),
        ("trigram_stats", None, None),
        ("mistake_events", "id", "mistake_events_id_seq"),
        ("email_verification_tokens", "id", "email_verification_tokens_id_seq"),
        ("password_reset_tokens", "id", "password_reset_tokens_id_seq"),
        ("sessions", None, None),
        ("ip_rate_limits", None, None),
        ("typing_sessions", "id", "typing_sessions_id_seq")
    ]

    total_migrated = 0
    pg_cursor = pg_conn.cursor()

    for table_name, pk_col, seq_name in tables:
        sqlite_cursor = sqlite_conn.cursor()
        rows = sqlite_cursor.execute(f"SELECT * FROM {table_name}").fetchall()

        if not rows:
            print(f"  - Table '{table_name}': 0 rows (skipped)")
            continue

        columns = rows[0].keys()
        cols_str = ", ".join(columns)
        placeholders = ", ".join(["%s"] * len(columns))
        insert_sql = f"INSERT INTO {table_name} ({cols_str}) VALUES ({placeholders}) ON CONFLICT DO NOTHING"

        count = 0
        for row in rows:
            val_list = []
            for col in columns:
                val = row[col]
                if table_name == "users" and col == "email_verified":
                    val = bool(val)
                val_list.append(val)
            try:
                pg_cursor.execute(insert_sql, tuple(val_list))
                count += 1
            except Exception as ex:
                print(f"    [!] Warning: Failed inserting row in {table_name}: {ex}")

        pg_conn.commit()
        print(f"  [+] Table '{table_name}': {count}/{len(rows)} rows migrated.")
        total_migrated += count

        # Reset Postgres sequence for auto-increment columns if present
        if pk_col and seq_name:
            try:
                pg_cursor.execute(f"SELECT setval('{seq_name}', COALESCE((SELECT MAX({pk_col}) FROM {table_name}), 1), true)")
                pg_conn.commit()
                print(f"      Sequence '{seq_name}' updated.")
            except Exception as seq_ex:
                print(f"      [!] Warning: Could not set sequence '{seq_name}': {seq_ex}")

    sqlite_conn.close()
    pg_conn.close()

    print(f"\n[✓] MIGRATION COMPLETE! Total rows migrated: {total_migrated}")

if __name__ == "__main__":
    main()
