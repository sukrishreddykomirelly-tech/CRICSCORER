"""PostgreSQL connection and schema helpers for CricScorer.

The application intentionally has no SQLite fallback.  A missing
DATABASE_URL is a configuration error rather than a reason to create a
temporary local database.
"""

import os
from typing import Any, Iterable, Optional

import psycopg
from psycopg.rows import tuple_row


class CompatRow(dict):
    """A row that supports both sqlite3.Row-style key and index access."""

    def __init__(self, columns=None, values=None):
        if isinstance(columns, dict):
            super().__init__(columns)
            self._columns = tuple(columns.keys())
            self._values = tuple(columns.values())
        elif columns is not None and values is not None:
            self._columns = tuple(columns)
            self._values = tuple(values)
            super().__init__(zip(self._columns, self._values))
        else:
            super().__init__()
            self._columns = ()
            self._values = ()

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, int):
            if 0 <= key < len(self._values):
                return self._values[key]
            elif -len(self._values) <= key < 0:
                return self._values[key]
            # Fallback to values list if _values was not set
            dict_vals = list(self.values())
            if 0 <= key < len(dict_vals):
                return dict_vals[key]
            return None
        return super().get(key)

    def get(self, key: Any, default: Any = None) -> Any:
        if isinstance(key, int):
            if 0 <= key < len(self._values):
                return self._values[key]
            return default
        return super().get(key, default)

    def keys(self):
        return self._columns if self._columns else super().keys()


def compat_row_factory(cursor):
    if cursor.description is None:
        return lambda values: values

    columns = [column.name for column in cursor.description]

    def make_row(values: Iterable[Any]) -> CompatRow:
        val_tuple = tuple(values) if values is not None else ()
        return CompatRow(columns, val_tuple)

    return make_row


def _convert_qmark_placeholders(query: str) -> str:
    """Translate the existing SQLite qmark placeholders to Psycopg format."""

    result = []
    in_single_quote = False
    in_double_quote = False
    index = 0

    while index < len(query):
        char = query[index]

        if char == "'" and not in_double_quote:
            result.append(char)
            if in_single_quote and index + 1 < len(query) and query[index + 1] == "'":
                result.append("'")
                index += 2
                continue
            in_single_quote = not in_single_quote
        elif char == '"' and not in_single_quote:
            result.append(char)
            in_double_quote = not in_double_quote
        elif char == "?" and not in_single_quote and not in_double_quote:
            result.append("%s")
        else:
            result.append(char)

        index += 1

    return "".join(result)


class CompatCursor:
    """Small cursor adapter that preserves the current database.py contract."""

    def __init__(self, cursor, connection):
        self._cursor = cursor
        self._connection = connection
        self.lastrowid: Optional[int] = None

    def execute(self, query: str, params=None):
        converted = _convert_qmark_placeholders(query)
        if params is None:
            self._cursor.execute(converted)
        else:
            self._cursor.execute(converted, params)

        self.lastrowid = None
        if converted.lstrip().upper().startswith("INSERT"):
            try:
                with self._connection.cursor(row_factory=tuple_row) as id_cursor:
                    id_cursor.execute("SELECT lastval()")
                    row = id_cursor.fetchone()
                    self.lastrowid = row[0] if row else None
            except psycopg.Error:
                # Junction tables do not have an identity column.  Existing
                # callers only use lastrowid for tables that do.
                self.lastrowid = None

        return self

    def executemany(self, query: str, params_seq):
        self._cursor.executemany(
            _convert_qmark_placeholders(query),
            params_seq,
        )
        self.lastrowid = None
        return self

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchmany(self, size=None):
        return self._cursor.fetchmany() if size is None else self._cursor.fetchmany(size)

    def fetchall(self):
        return self._cursor.fetchall()

    def __iter__(self):
        return iter(self._cursor)

    def __enter__(self):
        self._cursor.__enter__()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return self._cursor.__exit__(exc_type, exc_value, traceback)

    def __getattr__(self, name):
        return getattr(self._cursor, name)


class PostgresConnection:
    """Connection wrapper with SQLite-compatible cursor rows/placeholders."""

    def __init__(self, connection):
        self._connection = connection

    def cursor(self):
        return CompatCursor(
            self._connection.cursor(row_factory=compat_row_factory),
            self._connection,
        )

    def commit(self):
        return self._connection.commit()

    def rollback(self):
        return self._connection.rollback()

    def close(self):
        return self._connection.close()

    def __enter__(self):
        self._connection.__enter__()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return self._connection.__exit__(exc_type, exc_value, traceback)

    def __getattr__(self, name):
        return getattr(self._connection, name)


def get_postgres_connection():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        import sqlite3
        sqlite_conn = sqlite3.connect("cricscorer.db", check_same_thread=False, timeout=30.0)
        sqlite_conn.row_factory = sqlite3.Row
        sqlite_conn.execute("PRAGMA foreign_keys = ON")
        sqlite_conn.execute("PRAGMA journal_mode = WAL")
        sqlite_conn.execute("PRAGMA busy_timeout = 30000")
        return sqlite_conn

    return PostgresConnection(
        psycopg.connect(database_url, row_factory=compat_row_factory)
    )


POSTGRES_SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS players (
        id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
        name TEXT NOT NULL,
        batting_style TEXT,
        bowling_style TEXT,
        is_keeper INTEGER DEFAULT 0,
        avatar_url TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS teams (
        id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
        name TEXT NOT NULL,
        logo_url TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tournaments (
        id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
        name TEXT NOT NULL,
        win_points INTEGER DEFAULT 2,
        tie_points INTEGER DEFAULT 1,
        nr_points INTEGER DEFAULT 1
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS team_players (
        team_id BIGINT,
        player_id BIGINT,
        PRIMARY KEY (team_id, player_id),
        FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE CASCADE,
        FOREIGN KEY (player_id) REFERENCES players(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tournament_teams (
        tournament_id BIGINT,
        team_id BIGINT,
        PRIMARY KEY (tournament_id, team_id),
        FOREIGN KEY (tournament_id) REFERENCES tournaments(id) ON DELETE CASCADE,
        FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS matches (
        id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
        tournament_id BIGINT,
        team1_id BIGINT NOT NULL,
        team2_id BIGINT NOT NULL,
        match_format TEXT DEFAULT 'T20',
        overs_limit INTEGER DEFAULT 20,
        ground TEXT,
        match_date TEXT,
        match_time TEXT,
        status TEXT DEFAULT 'scheduled',
        toss_winner_id BIGINT,
        toss_decision TEXT,
        current_innings_id BIGINT,
        winner_id BIGINT,
        result_margin TEXT,
        is_super_over INTEGER DEFAULT 0,
        single_batting INTEGER DEFAULT 0,
        FOREIGN KEY (tournament_id) REFERENCES tournaments(id) ON DELETE SET NULL,
        FOREIGN KEY (team1_id) REFERENCES teams(id),
        FOREIGN KEY (team2_id) REFERENCES teams(id),
        FOREIGN KEY (toss_winner_id) REFERENCES teams(id),
        FOREIGN KEY (winner_id) REFERENCES teams(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS match_players (
        match_id BIGINT,
        team_id BIGINT,
        player_id BIGINT,
        batting_order INTEGER,
        PRIMARY KEY (match_id, team_id, player_id),
        FOREIGN KEY (match_id) REFERENCES matches(id) ON DELETE CASCADE,
        FOREIGN KEY (team_id) REFERENCES teams(id),
        FOREIGN KEY (player_id) REFERENCES players(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS innings (
        id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
        match_id BIGINT NOT NULL,
        innings_number INTEGER NOT NULL,
        batting_team_id BIGINT NOT NULL,
        bowling_team_id BIGINT NOT NULL,
        total_runs INTEGER DEFAULT 0,
        total_wickets INTEGER DEFAULT 0,
        balls_bowled INTEGER DEFAULT 0,
        wides INTEGER DEFAULT 0,
        noballs INTEGER DEFAULT 0,
        byes INTEGER DEFAULT 0,
        legbyes INTEGER DEFAULT 0,
        status TEXT DEFAULT 'ongoing',
        current_striker_id BIGINT,
        current_non_striker_id BIGINT,
        current_bowler_id BIGINT,
        FOREIGN KEY (match_id) REFERENCES matches(id) ON DELETE CASCADE,
        FOREIGN KEY (batting_team_id) REFERENCES teams(id),
        FOREIGN KEY (bowling_team_id) REFERENCES teams(id),
        FOREIGN KEY (current_striker_id) REFERENCES players(id),
        FOREIGN KEY (current_non_striker_id) REFERENCES players(id),
        FOREIGN KEY (current_bowler_id) REFERENCES players(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS substitutions (
        id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
        match_id BIGINT NOT NULL,
        innings_id BIGINT NOT NULL,
        outgoing_id BIGINT NOT NULL,
        incoming_id BIGINT NOT NULL,
        FOREIGN KEY (match_id) REFERENCES matches(id) ON DELETE CASCADE,
        FOREIGN KEY (outgoing_id) REFERENCES players(id),
        FOREIGN KEY (incoming_id) REFERENCES players(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS deliveries (
        id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
        innings_id BIGINT NOT NULL,
        over_number INTEGER NOT NULL,
        ball_of_over INTEGER NOT NULL,
        delivery_count INTEGER NOT NULL,
        striker_id BIGINT NOT NULL,
        non_striker_id BIGINT NOT NULL,
        bowler_id BIGINT NOT NULL,
        runs_batter INTEGER DEFAULT 0,
        runs_extras INTEGER DEFAULT 0,
        extra_type TEXT,
        is_legal INTEGER DEFAULT 1,
        is_wicket INTEGER DEFAULT 0,
        wicket_type TEXT,
        player_dismissed_id BIGINT,
        fielder_id BIGINT,
        is_bowler_wicket INTEGER DEFAULT 0,
        commentary TEXT,
        timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        new_batter_id BIGINT,
        next_striker_id BIGINT,
        FOREIGN KEY (innings_id) REFERENCES innings(id) ON DELETE CASCADE,
        FOREIGN KEY (striker_id) REFERENCES players(id),
        FOREIGN KEY (non_striker_id) REFERENCES players(id),
        FOREIGN KEY (bowler_id) REFERENCES players(id),
        FOREIGN KEY (player_dismissed_id) REFERENCES players(id),
        FOREIGN KEY (fielder_id) REFERENCES players(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS admin_users (
        id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS admin_audit_logs (
        id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
        action TEXT NOT NULL,
        target_type TEXT,
        target_id TEXT,
        details TEXT,
        admin_username TEXT NOT NULL,
        result TEXT DEFAULT 'success',
        timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS match_awards_override (
        match_id BIGINT PRIMARY KEY,
        potm_id BIGINT,
        best_batter_id BIGINT,
        best_bowler_id BIGINT,
        best_fielder_id BIGINT,
        mvp_id BIGINT,
        notes TEXT,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (match_id) REFERENCES matches(id) ON DELETE CASCADE,
        FOREIGN KEY (potm_id) REFERENCES players(id),
        FOREIGN KEY (best_batter_id) REFERENCES players(id),
        FOREIGN KEY (best_bowler_id) REFERENCES players(id),
        FOREIGN KEY (best_fielder_id) REFERENCES players(id),
        FOREIGN KEY (mvp_id) REFERENCES players(id)
    )
    """,
]

POSTGRES_COMPATIBILITY_ALTERS = [
    "ALTER TABLE matches ADD COLUMN IF NOT EXISTS single_batting INTEGER DEFAULT 0",
    "ALTER TABLE deliveries ADD COLUMN IF NOT EXISTS new_batter_id BIGINT",
    "ALTER TABLE deliveries ADD COLUMN IF NOT EXISTS next_striker_id BIGINT",
]


def ensure_postgres_schema(connection, commit=True):
    raw_connection = getattr(connection, "_connection", connection)
    import sqlite3
    if isinstance(raw_connection, sqlite3.Connection):
        # Create SQLite compatible tables
        sqlite_schema = [
            """
            CREATE TABLE IF NOT EXISTS admin_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS admin_audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                target_type TEXT,
                target_id TEXT,
                details TEXT,
                admin_username TEXT NOT NULL,
                result TEXT DEFAULT 'success',
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS match_awards_override (
                match_id INTEGER PRIMARY KEY,
                potm_id INTEGER,
                best_batter_id INTEGER,
                best_bowler_id INTEGER,
                best_fielder_id INTEGER,
                mvp_id INTEGER,
                notes TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (match_id) REFERENCES matches(id) ON DELETE CASCADE,
                FOREIGN KEY (potm_id) REFERENCES players(id),
                FOREIGN KEY (best_batter_id) REFERENCES players(id),
                FOREIGN KEY (best_bowler_id) REFERENCES players(id),
                FOREIGN KEY (best_fielder_id) REFERENCES players(id),
                FOREIGN KEY (mvp_id) REFERENCES players(id)
            )
            """
        ]
        cursor = raw_connection.cursor()
        for statement in sqlite_schema:
            cursor.execute(statement)
        if commit:
            raw_connection.commit()
        return

    with raw_connection.cursor() as cursor:
        for statement in POSTGRES_SCHEMA:
            cursor.execute(statement)
        for statement in POSTGRES_COMPATIBILITY_ALTERS:
            try:
                cursor.execute(statement)
            except Exception as e:
                print(f"Postgres alter warning: {e}")
    if commit:
        raw_connection.commit()