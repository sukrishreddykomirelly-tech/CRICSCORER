"""Copy PostgreSQL tables into Firestore without deleting PostgreSQL data.

Start with a dry run:
    python migrate_postgres_to_firestore.py

Apply the copy after adding FIREBASE_SERVICE_ACCOUNT_JSON to Replit Secrets:
    python migrate_postgres_to_firestore.py --apply

This is a data-copy utility only; the Flask application continues to use
PostgreSQL until its SQL data-access code is migrated separately.
"""

from __future__ import annotations

import argparse
import os
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict
from uuid import UUID

from database import get_db_connection
from firestore_db import get_firestore_client


TABLES = (
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
)

COMPOSITE_KEYS = {
    "team_players": ("team_id", "player_id"),
    "tournament_teams": ("tournament_id", "team_id"),
    "match_players": ("match_id", "team_id", "player_id"),
}

SINGLE_KEYS = {
    "match_awards_override": ("match_id",),
}
FIRESTORE_BATCH_SIZE = 450


def _to_firestore_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _to_firestore_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_firestore_value(item) for item in value]
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.isoformat()
    return value


def _document_id(table: str, row: Dict[str, Any]) -> str:
    if "id" in row and row["id"] is not None:
        return str(row["id"])

    key_fields = COMPOSITE_KEYS.get(table) or SINGLE_KEYS.get(table)
    if not key_fields:
        raise ValueError(f"No stable Firestore document key is defined for {table}.")

    missing = [field for field in key_fields if row.get(field) is None]
    if missing:
        raise ValueError(f"{table} row is missing key field(s): {', '.join(missing)}")
    return "_".join(str(row[field]) for field in key_fields)


def _load_table_rows(cursor, table: str):
    # Table names come only from the fixed TABLES allowlist above.
    cursor.execute(f'SELECT * FROM "{table}"')
    return [dict(row) for row in cursor.fetchall()]


def copy_postgres_to_firestore(apply: bool = False) -> Dict[str, int]:
    if not os.environ.get("DATABASE_URL"):
        raise RuntimeError(
            "DATABASE_URL is required. Refusing to copy from a local SQLite database."
        )

    conn = get_db_connection()
    counts: Dict[str, int] = {}
    try:
        cursor = conn.cursor()
        firestore_client = get_firestore_client() if apply else None

        for table in TABLES:
            rows = _load_table_rows(cursor, table)
            counts[table] = len(rows)
            if not apply or not rows:
                continue

            collection = firestore_client.collection(table)
            batch = firestore_client.batch()
            writes_in_batch = 0
            for row in rows:
                doc_ref = collection.document(_document_id(table, row))
                batch.set(doc_ref, _to_firestore_value(row))
                writes_in_batch += 1

                if writes_in_batch >= FIRESTORE_BATCH_SIZE:
                    batch.commit()
                    batch = firestore_client.batch()
                    writes_in_batch = 0

            if writes_in_batch:
                batch.commit()
    finally:
        conn.close()

    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Copy PostgreSQL data to Firestore.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write the rows to Firestore. Without this flag, only report source counts.",
    )
    args = parser.parse_args()

    counts = copy_postgres_to_firestore(apply=args.apply)
    mode = "Copied" if args.apply else "Dry run; no Firestore data was written"
    print(mode)
    for table, count in counts.items():
        print(f"{table}: {count} rows")
    if not args.apply:
        print("Add Firebase credentials to Replit Secrets, then rerun with --apply.")


if __name__ == "__main__":
    main()
