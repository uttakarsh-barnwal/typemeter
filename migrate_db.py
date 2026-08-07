#!/usr/bin/env python3
"""
TypeMeter Standalone Database Migration Script
Applies schema updates (e.g. creating typing_sessions table and missing indices)
safely to an existing SQLite database without dropping or duplicating data.
"""

import sys
import os
import sqlite3
import typemeter_db

def run_migrations(db_path="typemeter.db"):
    print(f"[*] Starting TypeMeter Database Migration for target: '{db_path}'...")
    
    if not os.path.exists(db_path):
        print(f"[*] Database file '{db_path}' does not exist yet. Initializing new schema...")
        conn = typemeter_db.get_db(db_path)
        conn.close()
        print(f"[✓] Schema successfully created in '{db_path}'.")
        return

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Enable WAL mode and Foreign Keys
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.execute("PRAGMA journal_mode = WAL;")

    # 1. Check & Create typing_sessions table
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='typing_sessions';")
    if not cursor.fetchone():
        print("[+] Creating missing 'typing_sessions' table...")
        cursor.execute("""
            CREATE TABLE typing_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                identity_id TEXT NOT NULL,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                wpm REAL NOT NULL,
                raw_wpm REAL NOT NULL,
                accuracy REAL NOT NULL,
                mistakes_count INTEGER DEFAULT 0,
                total_chars INTEGER DEFAULT 0,
                time_seconds REAL DEFAULT 0.0,
                difficulty TEXT NOT NULL DEFAULT 'easy',
                created_at TEXT NOT NULL
            )
        """)
        print("[✓] 'typing_sessions' table created.")
    else:
        print("[=] Table 'typing_sessions' already exists.")

    # 2. Check & Create indices
    indices = [
        ("idx_users_email", "users", "email"),
        ("idx_users_google_id", "users", "google_id"),
        ("idx_email_tokens_hash", "email_verification_tokens", "token_hash"),
        ("idx_reset_tokens_hash", "password_reset_tokens", "token_hash"),
        ("idx_sessions_user_id", "sessions", "user_id"),
        ("idx_rate_limits_key_timestamp", "ip_rate_limits", "key, timestamp"),
        ("idx_typing_sessions_user_id", "typing_sessions", "user_id"),
        ("idx_typing_sessions_identity", "typing_sessions", "identity_id")
    ]

    for idx_name, table_name, columns in indices:
        cursor.execute(f"SELECT name FROM sqlite_master WHERE type='index' AND name='{idx_name}';")
        if not cursor.fetchone():
            print(f"[+] Creating index '{idx_name}' on table '{table_name}'...")
            cursor.execute(f"CREATE INDEX {idx_name} ON {table_name}({columns});")
            print(f"[✓] Index '{idx_name}' created.")
        else:
            print(f"[=] Index '{idx_name}' already exists.")

    conn.commit()
    conn.close()
    print(f"\n[✓] Migration completed successfully for '{db_path}'.")

if __name__ == "__main__":
    db_target = sys.argv[1] if len(sys.argv) > 1 else "typemeter.db"
    run_migrations(db_target)
