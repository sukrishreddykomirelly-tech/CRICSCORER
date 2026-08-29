# database.py
import sqlite3
import os
from scoring import MatchState, InningsState

DB_PATH = os.path.join(os.path.dirname(__file__), "cricscorer.db")

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # Enable foreign keys
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Players Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS players (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        batting_style TEXT,
        bowling_style TEXT,
        is_keeper INTEGER DEFAULT 0,
        avatar_url TEXT
    );
    """)
    
    # 2. Teams Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS teams (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        logo_url TEXT
    );
    """)
    
    # 3. Team Players (Roster)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS team_players (
        team_id INTEGER,
        player_id INTEGER,
        PRIMARY KEY (team_id, player_id),
        FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE CASCADE,
        FOREIGN KEY (player_id) REFERENCES players(id) ON DELETE CASCADE
    );
    """)
    
    # 4. Tournaments Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS tournaments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        win_points INTEGER DEFAULT 2,
        tie_points INTEGER DEFAULT 1,
        nr_points INTEGER DEFAULT 1
    );
    """)
    
    # 5. Tournament Teams Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS tournament_teams (
        tournament_id INTEGER,
        team_id INTEGER,
        PRIMARY KEY (tournament_id, team_id),
        FOREIGN KEY (tournament_id) REFERENCES tournaments(id) ON DELETE CASCADE,
        FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE CASCADE
    );
    """)
    
    # 6. Matches Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS matches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tournament_id INTEGER,
        team1_id INTEGER NOT NULL,
        team2_id INTEGER NOT NULL,
        match_format TEXT DEFAULT 'T20',
        overs_limit INTEGER DEFAULT 20,
        ground TEXT,
        match_date TEXT,
        match_time TEXT,
        status TEXT DEFAULT 'scheduled', -- scheduled, toss_done, live, completed, abandoned
        toss_winner_id INTEGER,
        toss_decision TEXT, -- bat, bowl
        current_innings_id INTEGER,
        winner_id INTEGER,
        result_margin TEXT,
        is_super_over INTEGER DEFAULT 0,
        single_batting INTEGER DEFAULT 0,
        FOREIGN KEY (tournament_id) REFERENCES tournaments(id) ON DELETE SET NULL,
        FOREIGN KEY (team1_id) REFERENCES teams(id),
        FOREIGN KEY (team2_id) REFERENCES teams(id),
        FOREIGN KEY (toss_winner_id) REFERENCES teams(id),
        FOREIGN KEY (winner_id) REFERENCES teams(id)
    );
    """)
    
    # 7. Match Players (Selected playing XIs)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS match_players (
        match_id INTEGER,
        team_id INTEGER,
        player_id INTEGER,
        batting_order INTEGER,
        PRIMARY KEY (match_id, team_id, player_id),
        FOREIGN KEY (match_id) REFERENCES matches(id) ON DELETE CASCADE,
        FOREIGN KEY (team_id) REFERENCES teams(id),
        FOREIGN KEY (player_id) REFERENCES players(id)
    );
    """)
    
    # 8. Innings Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS innings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        match_id INTEGER NOT NULL,
        innings_number INTEGER NOT NULL, -- 1 or 2
        batting_team_id INTEGER NOT NULL,
        bowling_team_id INTEGER NOT NULL,
        total_runs INTEGER DEFAULT 0,
        total_wickets INTEGER DEFAULT 0,
        balls_bowled INTEGER DEFAULT 0,
        wides INTEGER DEFAULT 0,
        noballs INTEGER DEFAULT 0,
        byes INTEGER DEFAULT 0,
        legbyes INTEGER DEFAULT 0,
        status TEXT DEFAULT 'ongoing', -- ongoing, completed
        current_striker_id INTEGER,
        current_non_striker_id INTEGER,
        current_bowler_id INTEGER,
        FOREIGN KEY (match_id) REFERENCES matches(id) ON DELETE CASCADE,
        FOREIGN KEY (batting_team_id) REFERENCES teams(id),
        FOREIGN KEY (bowling_team_id) REFERENCES teams(id),
        FOREIGN KEY (current_striker_id) REFERENCES players(id),
        FOREIGN KEY (current_non_striker_id) REFERENCES players(id),
        FOREIGN KEY (current_bowler_id) REFERENCES players(id)
    );
    """)
    
    # 9. Deliveries Table (Source of truth)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS deliveries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        innings_id INTEGER NOT NULL,
        over_number INTEGER NOT NULL, -- 1-indexed over count
        ball_of_over INTEGER NOT NULL, -- 1-6 legal balls
        delivery_count INTEGER NOT NULL, -- sequence of ball in over (incl. extras)
        striker_id INTEGER NOT NULL,
        non_striker_id INTEGER NOT NULL,
        bowler_id INTEGER NOT NULL,
        runs_batter INTEGER DEFAULT 0,
        runs_extras INTEGER DEFAULT 0,
        extra_type TEXT, -- wide, noball, bye, legbye, None
        is_legal INTEGER DEFAULT 1,
        is_wicket INTEGER DEFAULT 0,
        wicket_type TEXT, -- bowled, caught, lbw, stumped, run_out, hit_wicket, retired_out, retired_hurt, obstructing_field
        player_dismissed_id INTEGER,
        fielder_id INTEGER,
        is_bowler_wicket INTEGER DEFAULT 0,
        commentary TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (innings_id) REFERENCES innings(id) ON DELETE CASCADE,
        FOREIGN KEY (striker_id) REFERENCES players(id),
        FOREIGN KEY (non_striker_id) REFERENCES players(id),
        FOREIGN KEY (bowler_id) REFERENCES players(id),
        FOREIGN KEY (player_dismissed_id) REFERENCES players(id),
        FOREIGN KEY (fielder_id) REFERENCES players(id)
    );
    """)
    
    # 10. Substitutions Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS substitutions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        match_id INTEGER NOT NULL,
        innings_id INTEGER NOT NULL,
        outgoing_id INTEGER NOT NULL,
        incoming_id INTEGER NOT NULL,
        FOREIGN KEY (match_id) REFERENCES matches(id) ON DELETE CASCADE,
        FOREIGN KEY (outgoing_id) REFERENCES players(id),
        FOREIGN KEY (incoming_id) REFERENCES players(id)
    );
    """)
    
    # Migration: add single_batting column if it doesn't exist in matches table
    try:
        cursor.execute("ALTER TABLE matches ADD COLUMN single_batting INTEGER DEFAULT 0")
    except Exception:
        pass
        
    try:
        cursor.execute("ALTER TABLE deliveries ADD COLUMN new_batter_id INTEGER")
    except Exception:
        pass
        
    try:
        cursor.execute("ALTER TABLE deliveries ADD COLUMN next_striker_id INTEGER")
    except Exception:
        pass
        
    conn.commit()
    conn.close()

def seed_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Check if players table already has seed data
    cursor.execute("SELECT COUNT(*) FROM players")
    if cursor.fetchone()[0] > 0:
        conn.close()
        return
        
    # Add Legendary Players
    players = [
        # Batters
        ("Virat Kohli", "Right-hand bat", "Right-arm medium", 0, "/static/images/avatars/avatar1.svg"),
        ("Virat Kohli", "Right-hand bat", "Right-arm medium", 0, "/static/images/avatars/avatar1.svg"), # duplicate guard in seeding
    ]
    # We will insert standard set of players
    seed_players = [
        ("Virat Kohli", "Right-hand bat", "Right-arm medium", 0),
        ("Rohit Sharma", "Right-hand bat", "Right-arm offbreak", 0),
        ("MS Dhoni", "Right-hand bat", "Right-arm medium", 1),
        ("Sachin Tendulkar", "Right-hand bat", "Right-arm legbreak", 0),
        ("Steve Smith", "Right-hand bat", "Right-arm legbreak", 0),
        ("Joe Root", "Right-hand bat", "Right-arm offbreak", 0),
        ("AB de Villiers", "Right-hand bat", "Right-arm medium", 1),
        ("Ben Stokes", "Left-hand bat", "Right-arm fast-medium", 0),
        
        # Bowlers
        ("Jasprit Bumrah", "Right-hand bat", "Right-arm fast", 0),
        ("Rashid Khan", "Right-hand bat", "Right-arm legbreak", 0),
        ("Mitchell Starc", "Left-hand bat", "Left-arm fast", 0),
        ("Trent Boult", "Right-hand bat", "Left-arm fast-medium", 0),
        ("Ravindra Jadeja", "Left-hand bat", "Slow left-arm orthodox", 0),
        ("Ravichandran Ashwin", "Right-hand bat", "Right-arm offbreak", 0),
        
        # Additional batters & all-rounders to make XIs
        ("Hardik Pandya", "Right-hand bat", "Right-arm fast-medium", 0),
        ("KL Rahul", "Right-hand bat", "None", 1),
        ("Shikhar Dhawan", "Left-hand bat", "None", 0),
        ("Suryakumar Yadav", "Right-hand bat", "None", 0),
        ("Kane Williamson", "Right-hand bat", "Right-arm offbreak", 0),
        ("Glenn Maxwell", "Right-hand bat", "Right-arm offbreak", 0),
        ("Jos Buttler", "Right-hand bat", "None", 1),
        ("Jofra Archer", "Right-hand bat", "Right-arm fast", 0)
    ]
    
    player_ids = []
    for name, bat, bowl, keeper in seed_players:
        # Give simple generic SVG path or default URL
        avatar = f"https://api.dicebear.com/7.x/bottts/svg?seed={name.replace(' ', '')}"
        cursor.execute("INSERT INTO players (name, batting_style, bowling_style, is_keeper, avatar_url) VALUES (?, ?, ?, ?, ?)",
                       (name, bat, bowl, keeper, avatar))
        player_ids.append(cursor.lastrowid)
        
    # Add Teams
    teams = [
        ("Apex Titans", "https://api.dicebear.com/7.x/identicon/svg?seed=Titans"),
        ("Velocity Strykers", "https://api.dicebear.com/7.x/identicon/svg?seed=Strykers"),
        ("Desert Vipers", "https://api.dicebear.com/7.x/identicon/svg?seed=Vipers")
    ]
    
    team_ids = []
    for name, logo in teams:
        cursor.execute("INSERT INTO teams (name, logo_url) VALUES (?, ?)", (name, logo))
        team_ids.append(cursor.lastrowid)
        
    # Map Players to Teams
    # Titans get first 11
    for p_id in player_ids[:11]:
        cursor.execute("INSERT INTO team_players (team_id, player_id) VALUES (?, ?)", (team_ids[0], p_id))
    # Strykers get next 11
    for p_id in player_ids[11:22]:
        cursor.execute("INSERT INTO team_players (team_id, player_id) VALUES (?, ?)", (team_ids[1], p_id))
    # Desert Vipers get a mix of players
    for p_id in [player_ids[0], player_ids[2], player_ids[4], player_ids[6], player_ids[8], player_ids[10], player_ids[12], player_ids[14], player_ids[16]]:
        cursor.execute("INSERT INTO team_players (team_id, player_id) VALUES (?, ?)", (team_ids[2], p_id))
        
    # Add a sample Tournament
    cursor.execute("INSERT INTO tournaments (name, win_points, tie_points, nr_points) VALUES (?, ?, ?, ?)",
                   ("Ultimate Champions League 2026", 2, 1, 1))
    tourney_id = cursor.lastrowid
    
    # Map teams to tournament
    for t_id in team_ids:
        cursor.execute("INSERT INTO tournament_teams (tournament_id, team_id) VALUES (?, ?)", (tourney_id, t_id))
        
    conn.commit()
    conn.close()

# --- REPLAY ENGINE LOAD & SAVE STATE ---

def load_match_state(match_id, is_rebuilding=False):
    """
    Hydrates a MatchState object by replaying the delivery log in order.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get Match metadata
    cursor.execute("SELECT * FROM matches WHERE id = ?", (match_id,))
    match_row = cursor.fetchone()
    if not match_row:
        conn.close()
        return None
        
    # Count dynamic squad size to determine wickets limit
    cursor.execute("SELECT COUNT(*) FROM match_players WHERE match_id = ? AND team_id = ?", (match_id, match_row['team1_id']))
    t1_count = cursor.fetchone()[0] or 11
    cursor.execute("SELECT COUNT(*) FROM match_players WHERE match_id = ? AND team_id = ?", (match_id, match_row['team2_id']))
    t2_count = cursor.fetchone()[0] or 11
    players_per_team = max(t1_count, t2_count)
    
    # Read single batting setting
    single_batting = False
    if 'single_batting' in match_row.keys():
        single_batting = bool(match_row['single_batting'])
        
    # Instantiate match state
    match_state = MatchState(
        match_id=match_row['id'],
        team1_id=match_row['team1_id'],
        team2_id=match_row['team2_id'],
        match_format=match_row['match_format'],
        overs_limit=match_row['overs_limit'],
        players_per_team=players_per_team,
        single_batting=single_batting
    )
    
    # Set status, toss, result
    match_state.status = match_row['status']
    match_state.toss_winner_id = match_row['toss_winner_id']
    match_state.toss_decision = match_row['toss_decision']
    match_state.winner_id = match_row['winner_id']
    match_state.result_margin = match_row['result_margin']
    match_state.is_super_over = match_row['is_super_over']
    
    # Load substitutions
    cursor.execute("SELECT innings_id, outgoing_id, incoming_id FROM substitutions WHERE match_id = ?", (match_id,))
    sub_rows = cursor.fetchall()
    match_state.substitutions = [{"innings_id": r['innings_id'], "outgoing_id": r['outgoing_id'], "incoming_id": r['incoming_id']} for r in sub_rows]
    
    # Hydrate Player Names
    cursor.execute("SELECT id, name FROM players")
    player_rows = cursor.fetchall()
    for row in player_rows:
        match_state.add_player_name(row['id'], row['name'])
        
    # Fetch Innings for this match
    cursor.execute("SELECT * FROM innings WHERE match_id = ? ORDER BY innings_number ASC", (match_id,))
    innings_rows = cursor.fetchall()
    
    for inn_row in innings_rows:
        # Start Innings in state
        match_state.start_innings(
            innings_id=inn_row['id'],
            batting_team_id=inn_row['batting_team_id'],
            bowling_team_id=inn_row['bowling_team_id'],
            innings_number=inn_row['innings_number']
        )
        
        inn_state = match_state.get_current_innings()
        if inn_state:
            inn_state.striker_id = inn_row['current_striker_id']
            inn_state.non_striker_id = inn_row['current_non_striker_id']
            inn_state.bowler_id = inn_row['current_bowler_id']
        
        # Load all deliveries for this innings in chronological order
        cursor.execute("""
            SELECT * FROM deliveries 
            WHERE innings_id = ? 
            ORDER BY id ASC
        """, (inn_row['id'],))
        del_rows = cursor.fetchall()
        
        # If there are deliveries, we replay them one-by-one
        for index, d_row in enumerate(del_rows):
            # In order to set the crease batters and bowler *before* applying the ball,
            # we read the striker_id, non_striker_id, and bowler_id saved with this delivery.
            # This ensures that even if we change bowlers/batters mid-innings, 
            # the state machine starts each delivery with the correct crease players!
            inn_state.striker_id = d_row['striker_id']
            inn_state.non_striker_id = d_row['non_striker_id']
            inn_state.bowler_id = d_row['bowler_id']
            
            new_batter_id = None
            next_striker_id = None
            try:
                new_batter_id = d_row['new_batter_id']
            except Exception:
                pass
            try:
                next_striker_id = d_row['next_striker_id']
            except Exception:
                pass

            d_dict = {
                "runs_batter": d_row['runs_batter'],
                "runs_extras": d_row['runs_extras'],
                "extra_type": d_row['extra_type'],
                "is_legal": d_row['is_legal'],
                "is_wicket": d_row['is_wicket'],
                "wicket_type": d_row['wicket_type'],
                "player_dismissed_id": d_row['player_dismissed_id'],
                "fielder_id": d_row['fielder_id'],
                "over_number": d_row['over_number'],
                "ball_of_over": d_row['ball_of_over'],
                "delivery_count": d_row['delivery_count'],
                "commentary": d_row['commentary'],
                "is_bowler_wicket": d_row['is_bowler_wicket'],
                "striker_id": d_row['striker_id'],
                "non_striker_id": d_row['non_striker_id'],
                "bowler_id": d_row['bowler_id'],
                "new_batter_id": new_batter_id,
                "next_striker_id": next_striker_id
            }
            
            # Apply to state machine
            match_state.apply_delivery(d_dict)
            
        # Apply substitutions to the final crease state of the innings
        for sub in match_state.substitutions:
            if sub.get('innings_id') == inn_row['id'] or sub.get('innings_id') == 0:
                if inn_state:
                    if inn_state.striker_id == sub['outgoing_id']:
                        inn_state.striker_id = sub['incoming_id']
                    if inn_state.non_striker_id == sub['outgoing_id']:
                        inn_state.non_striker_id = sub['incoming_id']
                    if inn_state.bowler_id == sub['outgoing_id']:
                        inn_state.bowler_id = sub['incoming_id']
            
    conn.close()
    return match_state

def save_delivery(innings_id, d):
    """
    Saves a delivery into the database and rebuilds/caches match state summaries.
    d contains keys: over_number, ball_of_over, delivery_count, striker_id, non_striker_id, bowler_id, 
    runs_batter, runs_extras, extra_type, is_legal, is_wicket, wicket_type, player_dismissed_id, fielder_id, commentary.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Insert delivery
    cursor.execute("""
        INSERT INTO deliveries (
            innings_id, over_number, ball_of_over, delivery_count,
            striker_id, non_striker_id, bowler_id,
            runs_batter, runs_extras, extra_type, is_legal,
            is_wicket, wicket_type, player_dismissed_id, fielder_id,
            is_bowler_wicket, commentary, new_batter_id, next_striker_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        innings_id, d['over_number'], d['ball_of_over'], d['delivery_count'],
        d['striker_id'], d['non_striker_id'], d['bowler_id'],
        d['runs_batter'], d['runs_extras'], d['extra_type'], d['is_legal'],
        d['is_wicket'], d['wicket_type'], d['player_dismissed_id'], d['fielder_id'],
        d['is_bowler_wicket'], d['commentary'], d.get('new_batter_id'), d.get('next_striker_id')
    ))
    
    conn.commit()
    conn.close()
    
    # Trigger rebuild of cached summary
    # Get match ID for this innings
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT match_id FROM innings WHERE id = ?", (innings_id,))
    match_id = cursor.fetchone()['match_id']
    conn.close()
    
    rebuild_and_cache_match_state(match_id)
    return match_id

def delete_last_delivery(innings_id):
    """
    Deletes the last delivery for an innings (Undo action).
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Find last delivery ID
    cursor.execute("SELECT id FROM deliveries WHERE innings_id = ? ORDER BY id DESC LIMIT 1", (innings_id,))
    row = cursor.fetchone()
    if row:
        del_id = row['id']
        cursor.execute("DELETE FROM deliveries WHERE id = ?", (del_id,))
        conn.commit()
        
    conn.close()
    
    # Rebuild state
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT match_id FROM innings WHERE id = ?", (innings_id,))
    match_id = cursor.fetchone()['match_id']
    conn.close()
    
    rebuild_and_cache_match_state(match_id)
    return match_id

def rebuild_and_cache_match_state(match_id):
    """
    Replays all deliveries for a match, then saves the precomputed totals
    (runs, wickets, balls, status, winner, margin) in the database.
    """
    match_state = load_match_state(match_id, is_rebuilding=True)
    if not match_state:
        return
        
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Update overall Match status
    cursor.execute("""
        UPDATE matches 
        SET status = ?, winner_id = ?, result_margin = ?
        WHERE id = ?
    """, (match_state.status, match_state.winner_id, match_state.result_margin, match_id))
    
    # 2. Update each Innings summaries
    for inn in match_state.innings:
        cursor.execute("""
            UPDATE innings 
            SET total_runs = ?, total_wickets = ?, balls_bowled = ?,
                wides = ?, noballs = ?, byes = ?, legbyes = ?, status = ?,
                current_striker_id = ?, current_non_striker_id = ?, current_bowler_id = ?
            WHERE id = ?
        """, (
            inn.total_runs, inn.total_wickets, inn.balls_bowled,
            inn.wides, inn.noballs, inn.byes, inn.legbyes, inn.status,
            inn.striker_id, inn.non_striker_id, inn.bowler_id,
            inn.innings_id
        ))
        
    conn.commit()
    conn.close()


# --- SEARCH & CREATION ENDPOINTS ---

def search_all(query):
    conn = get_db_connection()
    cursor = conn.cursor()
    q = f"%{query}%"
    
    # Players
    cursor.execute("SELECT id, name, batting_style, bowling_style, avatar_url FROM players WHERE name LIKE ? LIMIT 10", (q,))
    players = [dict(row) for row in cursor.fetchall()]
    
    # Teams
    cursor.execute("SELECT id, name, logo_url FROM teams WHERE name LIKE ? LIMIT 10", (q,))
    teams = [dict(row) for row in cursor.fetchall()]
    
    # Matches
    cursor.execute("""
        SELECT m.id, m.match_date, m.ground, m.match_format, m.status, m.result_margin,
               t1.name AS team1_name, t2.name AS team2_name,
               t1.logo_url AS team1_logo, t2.logo_url AS team2_logo
        FROM matches m
        JOIN teams t1 ON m.team1_id = t1.id
        JOIN teams t2 ON m.team2_id = t2.id
        WHERE t1.name LIKE ? OR t2.name LIKE ? OR m.ground LIKE ? 
        ORDER BY m.id DESC LIMIT 10
    """, (q, q, q))
    matches = [dict(row) for row in cursor.fetchall()]
    
    # Tournaments
    cursor.execute("SELECT id, name FROM tournaments WHERE name LIKE ? LIMIT 10", (q,))
    tournaments = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    return {
        "players": players,
        "teams": teams,
        "matches": matches,
        "tournaments": tournaments
    }

def get_recent_matches(limit=5):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT m.id, m.match_date, m.match_time, m.ground, m.match_format, m.status, m.result_margin,
               t1.name AS team1_name, t2.name AS team2_name,
               t1.logo_url AS team1_logo, t2.logo_url AS team2_logo,
               i1.total_runs AS i1_runs, i1.total_wickets AS i1_wkts, i1.balls_bowled AS i1_balls,
               i2.total_runs AS i2_runs, i2.total_wickets AS i2_wkts, i2.balls_bowled AS i2_balls
        FROM matches m
        JOIN teams t1 ON m.team1_id = t1.id
        JOIN teams t2 ON m.team2_id = t2.id
        LEFT JOIN innings i1 ON m.id = i1.match_id AND i1.innings_number = 1
        LEFT JOIN innings i2 ON m.id = i2.match_id AND i2.innings_number = 2
        ORDER BY m.id DESC LIMIT ?
    """, (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_live_matches():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT m.id, m.ground, m.match_format, m.status, m.overs_limit,
               t1.name AS team1_name, t2.name AS team2_name,
               t1.logo_url AS team1_logo, t2.logo_url AS team2_logo,
               i1.id AS i1_id, i1.total_runs AS i1_runs, i1.total_wickets AS i1_wkts, i1.balls_bowled AS i1_balls,
               i2.id AS i2_id, i2.total_runs AS i2_runs, i2.total_wickets AS i2_wkts, i2.balls_bowled AS i2_balls,
               m.current_innings_id
        FROM matches m
        JOIN teams t1 ON m.team1_id = t1.id
        JOIN teams t2 ON m.team2_id = t2.id
        LEFT JOIN innings i1 ON m.id = i1.match_id AND i1.innings_number = 1
        LEFT JOIN innings i2 ON m.id = i2.match_id AND i2.innings_number = 2
        WHERE m.status IN ('live', 'toss_done')
        ORDER BY m.id DESC
    """, ())
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


# --- DYNAMIC PLAYER PROFILE STATISTICS ---

def get_player_profile(player_id):
    """
    Returns player info and calculates dynamic career stats and match performances.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Info
    cursor.execute("SELECT * FROM players WHERE id = ?", (player_id,))
    player_row = cursor.fetchone()
    if not player_row:
        conn.close()
        return None
    player_info = dict(player_row)
    
    # 2. Batting career stats
    cursor.execute("SELECT COUNT(DISTINCT match_id) AS matches_played FROM match_players WHERE player_id = ?", (player_id,))
    matches_played = cursor.fetchone()[0] or 0
    
    cursor.execute("""
        SELECT 
            SUM(runs_batter) AS total_runs,
            COUNT(CASE WHEN extra_type IS NULL OR extra_type != 'wide' THEN 1 END) AS balls_faced,
            SUM(CASE WHEN runs_batter = 4 THEN 1 ELSE 0 END) AS fours,
            SUM(CASE WHEN runs_batter = 6 THEN 1 ELSE 0 END) AS sixes
        FROM deliveries
        WHERE striker_id = ?
    """, (player_id,))
    row = cursor.fetchone()
    bat_row = dict(row) if row else {"total_runs": 0, "balls_faced": 0, "fours": 0, "sixes": 0}
    bat_row['matches_played'] = matches_played
    
    # Number of innings actually batted (faced at least 1 ball or was in crease)
    cursor.execute("""
        SELECT COUNT(DISTINCT innings_id) 
        FROM deliveries 
        WHERE striker_id = ? OR non_striker_id = ?
    """, (player_id, player_id))
    bat_innings = cursor.fetchone()[0]
    
    # Dismissals count (Innings - Not Outs)
    cursor.execute("""
        SELECT COUNT(*) 
        FROM deliveries 
        WHERE player_dismissed_id = ? AND wicket_type NOT IN ('retired_hurt')
    """, (player_id,))
    dismissals = cursor.fetchone()[0]
    
    not_outs = max(0, bat_innings - dismissals)
    
    # Highest score in an innings
    cursor.execute("""
        SELECT innings_id, SUM(runs_batter) AS innings_runs
        FROM deliveries
        WHERE striker_id = ?
        GROUP BY innings_id
        ORDER BY innings_runs DESC LIMIT 1
    """, (player_id,))
    high_row = cursor.fetchone()
    high_score = high_row['innings_runs'] if high_row else 0
    # check if not out in that high score innings
    if high_row:
        cursor.execute("SELECT COUNT(*) FROM deliveries WHERE player_dismissed_id = ? AND innings_id = ?", (player_id, high_row['innings_id']))
        was_out = cursor.fetchone()[0] > 0
        high_score_str = f"{high_score}" if was_out else f"{high_score}*"
    else:
        high_score_str = "0"
        
    # Count of 30s, 50s, 100s
    cursor.execute("""
        SELECT innings_runs FROM (
            SELECT SUM(runs_batter) AS innings_runs
            FROM deliveries
            WHERE striker_id = ?
            GROUP BY innings_id
        ) WHERE innings_runs >= 100
    """, (player_id,))
    hundreds = len(cursor.fetchall())
    
    cursor.execute("""
        SELECT innings_runs FROM (
            SELECT SUM(runs_batter) AS innings_runs
            FROM deliveries
            WHERE striker_id = ?
            GROUP BY innings_id
        ) WHERE innings_runs >= 50 AND innings_runs < 100
    """, (player_id,))
    fifties = len(cursor.fetchall())
    
    cursor.execute("""
        SELECT innings_runs FROM (
            SELECT SUM(runs_batter) AS innings_runs
            FROM deliveries
            WHERE striker_id = ?
            GROUP BY innings_id
        ) WHERE innings_runs >= 30 AND innings_runs < 50
    """, (player_id,))
    thirties = len(cursor.fetchall())
    
    cursor.execute("""
        SELECT innings_runs FROM (
            SELECT SUM(runs_batter) AS innings_runs
            FROM deliveries
            WHERE striker_id = ?
            GROUP BY innings_id
        ) WHERE innings_runs = 0
    """, (player_id,))
    # Ducks count (out for 0)
    cursor.execute("""
        SELECT COUNT(DISTINCT d.innings_id)
        FROM deliveries d
        WHERE d.player_dismissed_id = ? AND d.wicket_type NOT IN ('retired_hurt')
          AND (SELECT COALESCE(SUM(runs_batter), 0) FROM deliveries WHERE striker_id = ? AND innings_id = d.innings_id) = 0
    """, (player_id, player_id))
    ducks = cursor.fetchone()[0]

    # Assemble Batting Stats
    total_runs = bat_row['total_runs'] or 0
    balls_faced = bat_row['balls_faced'] or 0
    bat_average = round(total_runs / dismissals, 2) if dismissals > 0 else "-"
    bat_sr = round((total_runs * 100) / balls_faced, 2) if balls_faced > 0 else 0.0
    
    batting_stats = {
        "matches": bat_row['matches_played'] or 0,
        "innings": bat_innings,
        "runs": total_runs,
        "balls": balls_faced,
        "high_score": high_score_str,
        "average": bat_average,
        "strike_rate": bat_sr,
        "fours": bat_row['fours'] or 0,
        "sixes": bat_row['sixes'] or 0,
        "thirties": thirties,
        "fifties": fifties,
        "hundreds": hundreds,
        "ducks": ducks,
        "not_outs": not_outs
    }
    
    # 3. Bowling career stats
    # Overs and runs conceded
    # Under MCC bowler is charged with runs_batter + Wides + No Balls
    cursor.execute("""
        SELECT 
            COUNT(CASE WHEN is_legal = 1 THEN 1 END) AS legal_balls,
            SUM(CASE WHEN extra_type = 'wide' THEN 1 + runs_extras
                     WHEN extra_type = 'noball' THEN 1 + runs_batter
                     ELSE runs_batter END) AS runs_conceded,
            SUM(CASE WHEN is_wicket = 1 AND is_bowler_wicket = 1 THEN 1 ELSE 0 END) AS wickets
        FROM deliveries
        WHERE bowler_id = ?
    """, (player_id,))
    bowl_row = cursor.fetchone()
    
    # Bowling Innings count
    cursor.execute("SELECT COUNT(DISTINCT innings_id) FROM deliveries WHERE bowler_id = ?", (player_id,))
    bowl_innings = cursor.fetchone()[0]
    
    # Maidens count:
    # Need to load all completed bowler overs and count where over total bowler runs = 0 and no illegal deliveries
    # In sqlite, we can compute it by grouping by (innings_id, over_number)
    cursor.execute("""
        SELECT innings_id, over_number,
               COUNT(CASE WHEN is_legal = 1 THEN 1 END) AS legal_balls,
               SUM(CASE WHEN extra_type = 'wide' THEN 1 + runs_extras
                        WHEN extra_type = 'noball' THEN 1 + runs_batter
                        ELSE runs_batter END) AS bowler_runs
        FROM deliveries
        WHERE bowler_id = ?
        GROUP BY innings_id, over_number
        HAVING legal_balls = 6 AND bowler_runs = 0
           AND COUNT(CASE WHEN is_legal = 0 THEN 1 END) = 0
    """, (player_id,))
    maidens = len(cursor.fetchall())
    
    # Best Bowling Figures
    cursor.execute("""
        SELECT innings_id, 
               SUM(CASE WHEN is_wicket = 1 AND is_bowler_wicket = 1 THEN 1 ELSE 0 END) AS wickets_inn,
               SUM(CASE WHEN extra_type = 'wide' THEN 1 + runs_extras
                        WHEN extra_type = 'noball' THEN 1 + runs_batter
                        ELSE runs_batter END) AS runs_inn
        FROM deliveries
        WHERE bowler_id = ?
        GROUP BY innings_id
        ORDER BY wickets_inn DESC, runs_inn ASC LIMIT 1
    """, (player_id,))
    best_row = cursor.fetchone()
    best_bowling = f"{best_row['wickets_inn']}/{best_row['runs_inn']}" if best_row else "-"
    
    # 3-wicket and 5-wicket hauls
    cursor.execute("""
        SELECT wickets_inn FROM (
            SELECT SUM(CASE WHEN is_wicket = 1 AND is_bowler_wicket = 1 THEN 1 ELSE 0 END) AS wickets_inn
            FROM deliveries
            WHERE bowler_id = ?
            GROUP BY innings_id
        ) WHERE wickets_inn >= 5
    """, (player_id,))
    five_wkt = len(cursor.fetchall())
    
    cursor.execute("""
        SELECT wickets_inn FROM (
            SELECT SUM(CASE WHEN is_wicket = 1 AND is_bowler_wicket = 1 THEN 1 ELSE 0 END) AS wickets_inn
            FROM deliveries
            WHERE bowler_id = ?
            GROUP BY innings_id
        ) WHERE wickets_inn >= 3 AND wickets_inn < 5
    """, (player_id,))
    three_wkt = len(cursor.fetchall())
    
    legal_balls = bowl_row['legal_balls'] or 0
    runs_conceded = bowl_row['runs_conceded'] or 0
    wickets = bowl_row['wickets'] or 0
    
    bowl_average = round(runs_conceded / wickets, 2) if wickets > 0 else "-"
    bowl_econ = round((runs_conceded * 6) / legal_balls, 2) if legal_balls > 0 else 0.0
    bowl_overs = f"{legal_balls // 6}.{legal_balls % 6}"
    
    bowling_stats = {
        "innings": bowl_innings,
        "overs": bowl_overs,
        "balls": legal_balls,
        "runs_conceded": runs_conceded,
        "wickets": wickets,
        "average": bowl_average,
        "economy": bowl_econ,
        "maidens": maidens,
        "best_bowling": best_bowling,
        "three_wickets": three_wkt,
        "five_wickets": five_wkt
    }
    
    # 4. Fielding stats
    cursor.execute("SELECT COUNT(*) FROM deliveries WHERE fielder_id = ? AND wicket_type = 'caught'", (player_id,))
    catches = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM deliveries WHERE fielder_id = ? AND wicket_type = 'stumped'", (player_id,))
    stumpings = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM deliveries WHERE fielder_id = ? AND wicket_type = 'run_out'", (player_id,))
    run_outs = cursor.fetchone()[0]
    
    fielding_stats = {
        "catches": catches,
        "stumpings": stumpings,
        "run_outs": run_outs
    }
    
    # 5. Recent Match Performances (Last 5 batting/bowling scores)
    cursor.execute("""
        SELECT m.id, m.match_date, t1.name AS team1, t2.name AS team2,
               (SELECT SUM(runs_batter) FROM deliveries WHERE striker_id = ? AND innings_id = i.id) AS batter_runs,
               (SELECT COUNT(CASE WHEN extra_type IS NULL OR extra_type != 'wide' THEN 1 END) FROM deliveries WHERE striker_id = ? AND innings_id = i.id) AS batter_balls,
               (SELECT COUNT(*) FROM deliveries WHERE player_dismissed_id = ? AND innings_id = i.id) AS was_dismissed,
               (SELECT SUM(CASE WHEN is_wicket = 1 AND is_bowler_wicket = 1 THEN 1 ELSE 0 END) FROM deliveries WHERE bowler_id = ? AND innings_id = i.id) AS bowler_wkts,
               (SELECT SUM(CASE WHEN extra_type = 'wide' THEN 1 + runs_extras WHEN extra_type = 'noball' THEN 1 + runs_batter ELSE runs_batter END) FROM deliveries WHERE bowler_id = ? AND innings_id = i.id) AS bowler_runs
        FROM match_players mp
        JOIN matches m ON mp.match_id = m.id
        JOIN innings i ON m.id = i.match_id
        JOIN teams t1 ON m.team1_id = t1.id
        JOIN teams t2 ON m.team2_id = t2.id
        WHERE mp.player_id = ?
        GROUP BY m.id
        ORDER BY m.id DESC LIMIT 5
    """, (player_id, player_id, player_id, player_id, player_id, player_id))
    recent_performances = [dict(row) for row in cursor.fetchall()]
    
    # Get Teams player is part of
    cursor.execute("""
        SELECT t.id, t.name, t.logo_url
        FROM team_players tp
        JOIN teams t ON tp.team_id = t.id
        WHERE tp.player_id = ?
    """, (player_id,))
    teams_list = [dict(row) for row in cursor.fetchall()]

    conn.close()
    
    return {
        "info": player_info,
        "batting": batting_stats,
        "bowling": bowling_stats,
        "fielding": fielding_stats,
        "recent": recent_performances,
        "teams": teams_list
    }


# --- DYNAMIC TEAM STATISTICS & PROFILE ---

def get_team_profile(team_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM teams WHERE id = ?", (team_id,))
    team_row = cursor.fetchone()
    if not team_row:
        conn.close()
        return None
    team_info = dict(team_row)
    
    # Get team players
    cursor.execute("""
        SELECT p.id, p.name, p.batting_style, p.bowling_style, p.avatar_url
        FROM team_players tp
        JOIN players p ON tp.player_id = p.id
        WHERE tp.team_id = ?
    """, (team_id,))
    players = [dict(row) for row in cursor.fetchall()]
    
    # Calculate Wins, Losses, Ties dynamically
    cursor.execute("""
        SELECT 
            COUNT(*) AS played,
            SUM(CASE WHEN winner_id = ? THEN 1 ELSE 0 END) AS wins,
            SUM(CASE WHEN winner_id != ? AND winner_id IS NOT NULL AND status = 'completed' THEN 1 ELSE 0 END) AS losses,
            SUM(CASE WHEN result_margin = 'match tied' THEN 1 ELSE 0 END) AS ties
        FROM matches
        WHERE (team1_id = ? OR team2_id = ?) AND status = 'completed'
    """, (team_id, team_id, team_id, team_id))
    stats_row = cursor.fetchone()
    
    # Match History
    cursor.execute("""
        SELECT m.id, m.match_date, m.ground, m.match_format, m.status, m.result_margin, m.winner_id,
               t1.name AS team1_name, t2.name AS team2_name,
               t1.logo_url AS team1_logo, t2.logo_url AS team2_logo
        FROM matches m
        JOIN teams t1 ON m.team1_id = t1.id
        JOIN teams t2 ON m.team2_id = t2.id
        WHERE m.team1_id = ? OR m.team2_id = ?
        ORDER BY m.id DESC LIMIT 10
    """, (team_id, team_id))
    matches = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    
    return {
        "info": team_info,
        "players": players,
        "stats": {
            "played": stats_row['played'] or 0,
            "wins": stats_row['wins'] or 0,
            "losses": stats_row['losses'] or 0,
            "ties": stats_row['ties'] or 0
        },
        "matches": matches
    }


# --- DYNAMIC TOURNAMENT POINT TABLE & LEADERBOARDS ---

def get_tournament_details(tournament_id):
    """
    Returns tournament info, points table (with correct NRR calculations),
    fixtures, and player leaderboards.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Info
    cursor.execute("SELECT * FROM tournaments WHERE id = ?", (tournament_id,))
    tourney_row = cursor.fetchone()
    if not tourney_row:
        conn.close()
        return None
    tourney_info = dict(tourney_row)
    
    # 2. Get teams in tournament
    cursor.execute("""
        SELECT t.id, t.name, t.logo_url
        FROM tournament_teams tt
        JOIN teams t ON tt.team_id = t.id
        WHERE tt.tournament_id = ?
    """, (tournament_id,))
    teams = [dict(row) for row in cursor.fetchall()]
    
    # 3. Retrieve all matches for this tournament to calculate points & NRR
    cursor.execute("""
        SELECT m.id, m.team1_id, m.team2_id, m.status, m.winner_id, m.result_margin, m.overs_limit,
               i1.total_runs AS i1_runs, i1.total_wickets AS i1_wkts, i1.balls_bowled AS i1_balls,
               i2.total_runs AS i2_runs, i2.total_wickets AS i2_wkts, i2.balls_bowled AS i2_balls
        FROM matches m
        LEFT JOIN innings i1 ON m.id = i1.match_id AND i1.innings_number = 1
        LEFT JOIN innings i2 ON m.id = i2.match_id AND i2.innings_number = 2
        WHERE m.tournament_id = ?
    """, (tournament_id,))
    matches_list = cursor.fetchall()
    
    # Initialize points table structure for each team
    # team_id -> dict
    table = {}
    for team in teams:
        table[team['id']] = {
            "team_id": team['id'],
            "name": team['name'],
            "logo_url": team['logo_url'],
            "played": 0,
            "won": 0,
            "lost": 0,
            "tied": 0,
            "nr": 0,
            "points": 0,
            "total_runs_scored": 0,
            "total_overs_faced": 0.0,
            "total_runs_conceded": 0,
            "total_overs_bowled": 0.0,
            "nrr": 0.0
        }
        
    # Win / Tie Points Config
    win_pts = tourney_info['win_points']
    tie_pts = tourney_info['tie_points']
    nr_pts = tourney_info['nr_points']
    
    # Process each match to calculate NRR and Points
    for m in matches_list:
        t1, t2 = m['team1_id'], m['team2_id']
        status = m['status']
        winner = m['winner_id']
        margin = m['result_margin']
        overs_limit = m['overs_limit']
        
        # We only count completed or abandoned/tied matches
        if status not in ['completed', 'abandoned']:
            continue
            
        # Initialize rows if teams are in tourney
        if t1 not in table or t2 not in table:
            continue
            
        table[t1]['played'] += 1
        table[t2]['played'] += 1
        
        # Points allocation
        if status == 'abandoned' or margin == 'no result':
            table[t1]['nr'] += 1
            table[t2]['nr'] += 1
            table[t1]['points'] += nr_pts
            table[t2]['points'] += nr_pts
            # No NRR impact for abandoned matches
            continue
            
        if margin == 'match tied':
            table[t1]['tied'] += 1
            table[t2]['tied'] += 1
            table[t1]['points'] += tie_pts
            table[t2]['points'] += tie_pts
            # Tie typically has 0 NRR difference, but let's count actual runs scored/overs faced to be precise
            # (though in many leagues ties do not affect NRR, standard ICC rules still accumulate runs/overs)
        elif winner == t1:
            table[t1]['won'] += 1
            table[t1]['points'] += win_pts
            table[t2]['lost'] += 1
        elif winner == t2:
            table[t2]['won'] += 1
            table[t2]['points'] += win_pts
            table[t1]['lost'] += 1
            
        # NRR Runs and Overs faced accumulation
        # Innings 1 details
        i1_runs = m['i1_runs'] or 0
        i1_wkts = m['i1_wkts'] or 0
        i1_balls = m['i1_balls'] or 0
        
        # Innings 2 details
        i2_runs = m['i2_runs'] or 0
        i2_wkts = m['i2_wkts'] or 0
        i2_balls = m['i2_balls'] or 0
        
        # Team 1 is Innings 1 batting (always batting first)
        # Team 2 is Innings 2 batting
        
        # --- TEAM 1 BATTING (Innings 1) ---
        table[t1]['total_runs_scored'] += i1_runs
        table[t2]['total_runs_conceded'] += i1_runs
        
        # ICC Rule: If team is bowled out, overs faced is set to maximum overs limit
        # In a custom/T20 match, maximum wickets limit is players_per_team - 1
        # Let's query player count for playing XI of team 1
        cursor.execute("SELECT COUNT(*) FROM match_players WHERE match_id = ? AND team_id = ?", (m['id'], t1))
        t1_players_count = cursor.fetchone()[0] or 11
        t1_all_out_wkts = t1_players_count - 1
        
        if i1_wkts >= t1_all_out_wkts:
            table[t1]['total_overs_faced'] += overs_limit
            table[t2]['total_overs_bowled'] += overs_limit
        else:
            # Add actual overs faced
            overs_faced_val = (i1_balls // 6) + (i1_balls % 6) / 6.0
            table[t1]['total_overs_faced'] += overs_faced_val
            table[t2]['total_overs_bowled'] += overs_faced_val
            
        # --- TEAM 2 BATTING (Innings 2) ---
        table[t2]['total_runs_scored'] += i2_runs
        table[t1]['total_runs_conceded'] += i2_runs
        
        cursor.execute("SELECT COUNT(*) FROM match_players WHERE match_id = ? AND team_id = ?", (m['id'], t2))
        t2_players_count = cursor.fetchone()[0] or 11
        t2_all_out_wkts = t2_players_count - 1
        
        if i2_wkts >= t2_all_out_wkts:
            table[t2]['total_overs_faced'] += overs_limit
            table[t1]['total_overs_bowled'] += overs_limit
        else:
            overs_faced_val = (i2_balls // 6) + (i2_balls % 6) / 6.0
            table[t2]['total_overs_faced'] += overs_faced_val
            table[t1]['total_overs_bowled'] += overs_faced_val

    # Finalize NRR calculations and sort table
    points_table = []
    for team_id, t_stats in table.items():
        scored_rate = t_stats['total_runs_scored'] / t_stats['total_overs_faced'] if t_stats['total_overs_faced'] > 0 else 0.0
        conceded_rate = t_stats['total_runs_conceded'] / t_stats['total_overs_bowled'] if t_stats['total_overs_bowled'] > 0 else 0.0
        t_stats['nrr'] = round(scored_rate - conceded_rate, 3)
        points_table.append(t_stats)
        
    # Sort by Points (descending), then Net Run Rate (descending), then Wins
    points_table.sort(key=lambda x: (x['points'], x['nrr'], x['won']), reverse=True)
    
    # 4. Tournament Fixtures/Matches
    cursor.execute("""
        SELECT m.id, m.match_date, m.ground, m.match_format, m.status, m.result_margin,
               t1.name AS team1_name, t2.name AS team2_name,
               t1.logo_url AS team1_logo, t2.logo_url AS team2_logo
        FROM matches m
        JOIN teams t1 ON m.team1_id = t1.id
        JOIN teams t2 ON m.team2_id = t2.id
        WHERE m.tournament_id = ?
        ORDER BY m.id DESC
    """, (tournament_id,))
    fixtures = [dict(row) for row in cursor.fetchall()]
    
    # 5. Top Run Scorers (Leaderboard)
    cursor.execute("""
        SELECT p.id, p.name, p.avatar_url, t.name AS team_name,
               SUM(d.runs_batter) AS total_runs,
               COUNT(DISTINCT d.innings_id) AS innings_batted
        FROM deliveries d
        JOIN players p ON d.striker_id = p.id
        JOIN innings i ON d.innings_id = i.id
        JOIN matches m ON i.match_id = m.id
        JOIN teams t ON i.batting_team_id = t.id
        WHERE m.tournament_id = ?
        GROUP BY p.id
        ORDER BY total_runs DESC LIMIT 5
    """, (tournament_id,))
    top_scorers = [dict(row) for row in cursor.fetchall()]
    
    # 6. Top Wicket Takers (Leaderboard)
    cursor.execute("""
        SELECT p.id, p.name, p.avatar_url, t.name AS team_name,
               SUM(CASE WHEN d.is_wicket = 1 AND d.is_bowler_wicket = 1 THEN 1 ELSE 0 END) AS total_wickets
        FROM deliveries d
        JOIN players p ON d.bowler_id = p.id
        JOIN innings i ON d.innings_id = i.id
        JOIN matches m ON i.match_id = m.id
        JOIN teams t ON i.bowling_team_id = t.id
        WHERE m.tournament_id = ?
        GROUP BY p.id
        ORDER BY total_wickets DESC LIMIT 5
    """, (tournament_id,))
    top_bowlers = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    
    return {
        "info": tourney_info,
        "teams": teams,
        "points_table": points_table,
        "fixtures": fixtures,
        "top_scorers": top_scorers,
        "top_bowlers": top_bowlers
    }
