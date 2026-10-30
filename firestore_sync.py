"""Bidirectional sync helpers between Cloud Firestore and SQLite.

Ensures that whenever Cloud Firestore is the persistent cloud store (e.g. Neon
PostgreSQL disabled or offline), all tournaments, teams, players, matches,
innings, deliveries, and chat data are loaded into SQLite on application startup.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any, Dict, List, Optional

import firestore_db
from migrate_postgres_to_firestore import (
    COMPOSITE_KEYS,
    SINGLE_KEYS,
    TABLES,
    _document_id,
    _to_firestore_value,
)

logger = logging.getLogger(__name__)

# Topological order for importing to SQLite
SYNC_ORDER = [
    "players",
    "teams",
    "tournaments",
    "team_players",
    "tournament_teams",
    "matches",
    "match_players",
    "innings",
    "substitutions",
    "deliveries",
    "admin_users",
    "admin_audit_logs",
    "match_awards_override",
    "admin_statistics_cache",
    "ai_chat_conversations",
    "ai_chat_messages",
]


def is_sync_enabled() -> bool:
    """Return True if Firestore credentials are configured."""
    return firestore_db.is_firestore_configured()


def _get_table_columns(cursor, table: str) -> List[str]:
    """Retrieve column names for a table in SQLite."""
    try:
        cursor.execute(f'PRAGMA table_info("{table}")')
        rows = cursor.fetchall()
        return [row[1] for row in rows]
    except Exception as e:
        logger.warning("Could not get columns for table %s: %s", table, e)
        return []


def restore_firestore_to_sqlite(conn=None) -> Dict[str, int]:
    """Restore all data from Cloud Firestore into the local SQLite database.

    Uses INSERT OR REPLACE to update existing rows and insert missing rows
    without duplicating primary keys.
    """
    if not is_sync_enabled():
        logger.info("Firestore is not configured. Skipping restore.")
        return {}

    try:
        db = firestore_db.get_firestore_client()
    except Exception as exc:
        logger.warning("Could not get Firestore client for restore: %s", exc)
        return {}

    close_conn = False
    if conn is None:
        from database import get_db_connection
        conn = get_db_connection()
        close_conn = True

    raw_conn = getattr(conn, "_connection", conn)
    is_sqlite = isinstance(raw_conn, sqlite3.Connection)
    
    counts: Dict[str, int] = {}

    try:
        cursor = raw_conn.cursor()

        if is_sqlite:
            cursor.execute("PRAGMA foreign_keys = OFF;")

        for table in SYNC_ORDER:
            try:
                table_cols = set(_get_table_columns(cursor, table))
                if not table_cols:
                    continue

                docs = list(db.collection(table).stream())
                if not docs:
                    continue

                synced_count = 0
                for doc in docs:
                    data = doc.to_dict()
                    if not isinstance(data, dict):
                        continue

                    # Filter valid fields matching SQLite table columns and format timestamps
                    valid_items = {
                        k: (v.isoformat() if hasattr(v, "isoformat") else v)
                        for k, v in data.items()
                        if k in table_cols
                    }
                    if not valid_items:
                        continue

                    col_names = ", ".join(f'"{k}"' for k in valid_items.keys())
                    placeholders = ", ".join(["?"] * len(valid_items))
                    values = list(valid_items.values())

                    if is_sqlite:
                        query = f'INSERT OR REPLACE INTO "{table}" ({col_names}) VALUES ({placeholders})'
                    else:
                        query = f'INSERT INTO "{table}" ({col_names}) VALUES ({placeholders}) ON CONFLICT DO NOTHING'

                    cursor.execute(query, values)
                    synced_count += 1

                counts[table] = synced_count
            except Exception as table_err:
                logger.error("Error restoring table %s from Firestore: %s", table, table_err)

        raw_conn.commit()

        if is_sqlite:
            cursor.execute("PRAGMA foreign_keys = ON;")
            raw_conn.commit()

        print(f"Firestore restore completed successfully: {counts}")
    except Exception as exc:
        logger.error("Failed to restore Firestore to SQLite: %s", exc)
    finally:
        if close_conn:
            conn.close()

    return counts


def sync_document_to_firestore(table: str, doc_id: str, data: Dict[str, Any]) -> bool:
    """Save a single document to Cloud Firestore."""
    if not is_sync_enabled():
        return False
    try:
        db = firestore_db.get_firestore_client()
        clean_data = _to_firestore_value(data)
        db.collection(table).document(str(doc_id)).set(clean_data, merge=True)
        return True
    except Exception as exc:
        logger.warning("Failed to sync %s doc %s to Firestore: %s", table, doc_id, exc)
        return False
