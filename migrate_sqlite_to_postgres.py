"""One-time, idempotent CricScorer SQLite -> PostgreSQL migration."""

import argparse
import hashlib
import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import psycopg

from postgres_db import POSTGRES_SCHEMA, ensure_postgres_schema


TABLE_COLUMNS = {
    "players": [
        "id", "name", "batting_style", "bowling_style", "is_keeper", "avatar_url"
    ],
    "teams": ["id", "name", "logo_url"],
    "tournaments": ["id", "name", "win_points", "tie_points", "nr_points"],
    "team_players": ["team_id", "player_id"],
    "tournament_teams": ["tournament_id", "team_id"],
    "matches": [
        "id", "tournament_id", "team1_id", "team2_id", "match_format",
        "overs_limit", "ground", "match_date", "match_time", "status",
        "toss_winner_id", "toss_decision", "current_innings_id", "winner_id",
        "result_margin", "is_super_over", "single_batting",
    ],
    "match_players": ["match_id", "team_id", "player_id", "batting_order"],
    "innings": [
        "id", "match_id", "innings_number", "batting_team_id", "bowling_team_id",
        "total_runs", "total_wickets", "balls_bowled", "wides", "noballs",
        "byes", "legbyes", "status", "current_striker_id",
        "current_non_striker_id", "current_bowler_id",
    ],
    "substitutions": [
        "id", "match_id", "innings_id", "outgoing_id", "incoming_id"
    ],
    "deliveries": [
        "id", "innings_id", "over_number", "ball_of_over", "delivery_count",
        "striker_id", "non_striker_id", "bowler_id", "runs_batter",
        "runs_extras", "extra_type", "is_legal", "is_wicket", "wicket_type",
        "player_dismissed_id", "fielder_id", "is_bowler_wicket", "commentary",
        "timestamp", "new_batter_id", "next_striker_id",
    ],
}

IMPORT_ORDER = [
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
]

PRIMARY_KEYS = {
    "players": ["id"],
    "teams": ["id"],
    "tournaments": ["id"],
    "team_players": ["team_id", "player_id"],
    "tournament_teams": ["tournament_id", "team_id"],
    "matches": ["id"],
    "match_players": ["match_id", "team_id", "player_id"],
    "innings": ["id"],
    "substitutions": ["id"],
    "deliveries": ["id"],
}


def backup_sqlite(source: Path, backup_dir: Path) -> tuple[Path, str]:
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = backup_dir / f"cricscorer-pre-postgresql-{timestamp}.db"
    if backup.exists():
        raise FileExistsError(f"Refusing to overwrite existing backup: {backup}")
    shutil.copy2(source, backup)
    checksum = hashlib.sha256(source.read_bytes()).hexdigest()
    return backup, checksum


def sqlite_rows(source: Path, table: str):
    connection = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        columns = TABLE_COLUMNS[table]
        query = f'SELECT {", ".join(columns)} FROM "{table}" ORDER BY rowid'
        return [tuple(row[column] for column in columns) for row in connection.execute(query)]
    finally:
        connection.close()


def sqlite_counts(source: Path):
    connection = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    try:
        return {
            table: connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            for table in IMPORT_ORDER
        }
    finally:
        connection.close()


def import_table(cursor, table: str, rows):
    if not rows:
        return

    columns = TABLE_COLUMNS[table]
    primary_key = PRIMARY_KEYS[table]
    quoted_columns = ", ".join(f'"{column}"' for column in columns)
    placeholders = ", ".join(["%s"] * len(columns))
    update_columns = [column for column in columns if column not in primary_key]

    if update_columns:
        updates = ", ".join(
            f'"{column}" = EXCLUDED."{column}"' for column in update_columns
        )
        conflict = (
            f'ON CONFLICT ({", ".join(f""" "{column}" """.strip() for column in primary_key)}) '
            f"DO UPDATE SET {updates}"
        )
    else:
        conflict = (
            f'ON CONFLICT ({", ".join(f""" "{column}" """.strip() for column in primary_key)}) '
            "DO NOTHING"
        )

    statement = (
        f'INSERT INTO "{table}" ({quoted_columns}) VALUES ({placeholders}) '
        f"{conflict}"
    )
    cursor.executemany(statement, rows)


def reset_sequences(cursor):
    for table in ("players", "teams", "tournaments", "matches", "innings",
                  "substitutions", "deliveries"):
        cursor.execute(
            f"""
            SELECT setval(
                pg_get_serial_sequence('{table}', 'id'),
                COALESCE(MAX(id), 1),
                MAX(id) IS NOT NULL
            )
            FROM "{table}"
            """
        )


def verify_relationships(cursor):
    checks = {
        "orphan_team_players": """
            SELECT COUNT(*) FROM team_players tp
            WHERE NOT EXISTS (SELECT 1 FROM teams t WHERE t.id = tp.team_id)
               OR NOT EXISTS (SELECT 1 FROM players p WHERE p.id = tp.player_id)
        """,
        "orphan_tournament_teams": """
            SELECT COUNT(*) FROM tournament_teams tt
            WHERE NOT EXISTS (
                SELECT 1 FROM tournaments t WHERE t.id = tt.tournament_id
            )
            OR NOT EXISTS (SELECT 1 FROM teams t WHERE t.id = tt.team_id)
        """,
        "orphan_match_players": """
            SELECT COUNT(*) FROM match_players mp
            WHERE NOT EXISTS (SELECT 1 FROM matches m WHERE m.id = mp.match_id)
               OR NOT EXISTS (SELECT 1 FROM teams t WHERE t.id = mp.team_id)
               OR NOT EXISTS (SELECT 1 FROM players p WHERE p.id = mp.player_id)
        """,
        "orphan_innings": """
            SELECT COUNT(*) FROM innings i
            WHERE NOT EXISTS (SELECT 1 FROM matches m WHERE m.id = i.match_id)
        """,
        "orphan_deliveries": """
            SELECT COUNT(*) FROM deliveries d
            WHERE NOT EXISTS (SELECT 1 FROM innings i WHERE i.id = d.innings_id)
        """,
        "orphan_substitutions": """
            SELECT COUNT(*) FROM substitutions s
            WHERE NOT EXISTS (SELECT 1 FROM matches m WHERE m.id = s.match_id)
               OR NOT EXISTS (SELECT 1 FROM players p WHERE p.id = s.outgoing_id)
               OR NOT EXISTS (SELECT 1 FROM players p WHERE p.id = s.incoming_id)
        """,
    }
    results = {}
    for name, query in checks.items():
        cursor.execute(query)
        results[name] = cursor.fetchone()[0]
    return results


def migrate(source: Path, backup_dir: Path):
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required; refusing SQLite-only migration.")
    if not source.exists():
        raise FileNotFoundError(f"SQLite source does not exist: {source}")

    backup, checksum = backup_sqlite(source, backup_dir)
    source_counts = sqlite_counts(source)

    with psycopg.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS sqlite_migration_runs (
                    source_checksum TEXT PRIMARY KEY,
                    source_path TEXT NOT NULL,
                    backup_path TEXT NOT NULL,
                    migrated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            cursor.execute(
                "SELECT 1 FROM sqlite_migration_runs WHERE source_checksum = %s",
                (checksum,),
            )
            already_migrated = cursor.fetchone() is not None

            if not already_migrated:
                for statement in POSTGRES_SCHEMA:
                    cursor.execute(statement)
                for table in IMPORT_ORDER:
                    import_table(cursor, table, sqlite_rows(source, table))
                reset_sequences(cursor)
                cursor.execute(
                    """
                    INSERT INTO sqlite_migration_runs
                        (source_checksum, source_path, backup_path)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (source_checksum) DO NOTHING
                    """,
                    (checksum, str(source), str(backup)),
                )

            target_counts = {}
            for table in IMPORT_ORDER:
                cursor.execute(f'SELECT COUNT(*) FROM "{table}"')
                target_counts[table] = cursor.fetchone()[0]

            relationship_counts = verify_relationships(cursor)
            cursor.execute("SELECT COUNT(*) FROM matches")
            match_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM deliveries")
            delivery_count = cursor.fetchone()[0]

    if any(
        target_counts[table] < source_counts[table]
        for table in IMPORT_ORDER
    ):
        raise RuntimeError(
            f"PostgreSQL row counts are lower than SQLite: "
            f"source={source_counts} target={target_counts}"
        )
    if any(relationship_counts.values()):
        raise RuntimeError(f"Foreign-key verification failed: {relationship_counts}")

    return {
        "backup": str(backup),
        "checksum": checksum,
        "already_migrated": already_migrated,
        "source_counts": source_counts,
        "target_counts": target_counts,
        "relationship_counts": relationship_counts,
        "matches": match_count,
        "deliveries": delivery_count,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sqlite", default="cricscorer.db", type=Path)
    parser.add_argument("--backup-dir", default="backups", type=Path)
    args = parser.parse_args()
    result = migrate(args.sqlite, args.backup_dir)
    for key, value in result.items():
        print(f"{key}={value}")


if __name__ == "__main__":
    main()