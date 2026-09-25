# admin.py
import json
import os
import datetime
from functools import wraps
from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, session, jsonify, Response, current_app, send_file
)
from werkzeug.security import generate_password_hash, check_password_hash
import database
from database import get_db_connection, rebuild_and_cache_match_state
import awards
import rankings

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

# --- CONFIG & DEFAULTS ---
DEFAULT_ADMIN_USER = os.environ.get("ADMIN_USERNAME", "admin")
DEFAULT_ADMIN_PASS = os.environ.get("ADMIN_PASSWORD", "admin123")

_admin_db_ready = False

def ensure_admin_db_ready():
    """Ensure that the database schema and default admin account exist."""
    global _admin_db_ready
    if not _admin_db_ready:
        try:
            database.init_db()
            ensure_admin_table_seeded()
            _admin_db_ready = True
        except Exception as e:
            print(f"Error initializing admin DB: {e}")


@admin_bp.before_request
def admin_before_request():
    ensure_admin_db_ready()


# --- AUTHENTICATION HELPERS ---

def ensure_admin_table_seeded():
    """Ensure at least one admin account exists in admin_users."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM admin_users")
        count = cursor.fetchone()[0]
        if count == 0:
            hashed = generate_password_hash(DEFAULT_ADMIN_PASS)
            cursor.execute(
                "INSERT INTO admin_users (username, password_hash) VALUES (?, ?)",
                (DEFAULT_ADMIN_USER, hashed)
            )
            conn.commit()
        conn.close()
    except Exception as e:
        print(f"Notice during admin table seeding: {e}")


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_logged_in'):
            flash("Please log in to access the Admin Panel.", "warning")
            return redirect(url_for('admin.login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function


def log_admin_action(action, target_type=None, target_id=None, details=None, result="success"):
    """Record administrative actions in the audit log."""
    username = session.get('admin_user', 'system')
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO admin_audit_logs (action, target_type, target_id, details, admin_username, result)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (action, target_type, str(target_id) if target_id is not None else None, str(details or ''), username, result))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error logging admin action: {e}")


def trigger_live_update(match_id):
    """Notify real-time SSE listeners if available."""
    try:
        from app import notify_match_update
        notify_match_update(match_id)
    except Exception:
        pass


# --- AUTH ROUTES ---

@admin_bp.route('/login', methods=['GET', 'POST'])
def login():
    ensure_admin_db_ready()

    if session.get('admin_logged_in'):
        return redirect(url_for('admin.dashboard'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()

        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM admin_users WHERE username = ?", (username,))
            user = cursor.fetchone()
            conn.close()

            if user and check_password_hash(user['password_hash'], password):
                session['admin_logged_in'] = True
                session['admin_user'] = user['username']
                session['admin_id'] = user['id']
                log_admin_action("admin_login", "admin_users", user['id'], f"Logged in from {request.remote_addr}")
                flash(f"Welcome back, {user['username']}!", "success")
                next_url = request.args.get('next')
                return redirect(next_url or url_for('admin.dashboard'))
            else:
                flash("Invalid admin username or password.", "danger")
        except Exception as e:
            flash(f"Database error during login: {e}", "danger")

    return render_template('admin/login.html')


@admin_bp.route('/logout')
def logout():
    log_admin_action("admin_logout", "admin_users", session.get('admin_id'), "Logged out")
    session.pop('admin_logged_in', None)
    session.pop('admin_user', None)
    session.pop('admin_id', None)
    flash("You have been logged out safely.", "info")
    return redirect(url_for('admin.login'))


# --- DASHBOARD ---

@admin_bp.route('')
@admin_bp.route('/')
@admin_bp.route('/dashboard')
@admin_required
def dashboard():
    ensure_admin_db_ready()

    total_players = 0
    total_teams = 0
    total_tournaments = 0
    total_matches = 0
    completed_matches = 0
    live_matches_count = 0
    upcoming_matches = 0
    total_innings = 0
    total_deliveries = 0
    total_runs = 0
    total_wickets = 0
    live_matches = []
    recent_logs = []
    recent_matches = []

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # System metrics
        try:
            cursor.execute("SELECT COUNT(*) FROM players")
            total_players = cursor.fetchone()[0]
        except Exception:
            pass

        try:
            cursor.execute("SELECT COUNT(*) FROM teams")
            total_teams = cursor.fetchone()[0]
        except Exception:
            pass

        try:
            cursor.execute("SELECT COUNT(*) FROM tournaments")
            total_tournaments = cursor.fetchone()[0]
        except Exception:
            pass

        try:
            cursor.execute("SELECT COUNT(*) FROM matches")
            total_matches = cursor.fetchone()[0]
        except Exception:
            pass

        try:
            cursor.execute("SELECT COUNT(*) FROM matches WHERE status = 'completed'")
            completed_matches = cursor.fetchone()[0]
        except Exception:
            pass

        try:
            cursor.execute("SELECT COUNT(*) FROM matches WHERE status IN ('live', 'toss_done')")
            live_matches_count = cursor.fetchone()[0]
        except Exception:
            pass

        try:
            cursor.execute("SELECT COUNT(*) FROM matches WHERE status = 'scheduled'")
            upcoming_matches = cursor.fetchone()[0]
        except Exception:
            pass

        try:
            cursor.execute("SELECT COUNT(*) FROM innings")
            total_innings = cursor.fetchone()[0]
        except Exception:
            pass

        try:
            cursor.execute("SELECT COUNT(*) FROM deliveries")
            total_deliveries = cursor.fetchone()[0]
        except Exception:
            pass

        # Aggregate runs & wickets across deliveries
        try:
            cursor.execute("SELECT COALESCE(SUM(runs_batter + runs_extras), 0), COALESCE(SUM(is_wicket), 0) FROM deliveries")
            runs_row = cursor.fetchone()
            total_runs = runs_row[0] if runs_row else 0
            total_wickets = runs_row[1] if runs_row else 0
        except Exception:
            pass

        # Live matches with rich info
        try:
            cursor.execute("""
                SELECT m.id, m.ground, m.match_format, m.status, m.overs_limit, m.current_innings_id,
                       t1.name AS team1_name, t2.name AS team2_name,
                       t1.logo_url AS team1_logo, t2.logo_url AS team2_logo,
                       i1.id AS i1_id, i1.total_runs AS i1_runs, i1.total_wickets AS i1_wkts, i1.balls_bowled AS i1_balls,
                       i2.id AS i2_id, i2.total_runs AS i2_runs, i2.total_wickets AS i2_wkts, i2.balls_bowled AS i2_balls,
                       i_curr.current_striker_id, i_curr.current_non_striker_id, i_curr.current_bowler_id,
                       p1.name AS striker_name, p2.name AS non_striker_name, pb.name AS bowler_name
                FROM matches m
                JOIN teams t1 ON m.team1_id = t1.id
                JOIN teams t2 ON m.team2_id = t2.id
                LEFT JOIN innings i1 ON m.id = i1.match_id AND i1.innings_number = 1
                LEFT JOIN innings i2 ON m.id = i2.match_id AND i2.innings_number = 2
                LEFT JOIN innings i_curr ON m.current_innings_id = i_curr.id
                LEFT JOIN players p1 ON i_curr.current_striker_id = p1.id
                LEFT JOIN players p2 ON i_curr.current_non_striker_id = p2.id
                LEFT JOIN players pb ON i_curr.current_bowler_id = pb.id
                WHERE m.status IN ('live', 'toss_done')
                ORDER BY m.id DESC
            """)
            live_matches = [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            print(f"Error fetching live matches for dashboard: {e}")

        # Recent Audit Logs
        try:
            cursor.execute("""
                SELECT * FROM admin_audit_logs ORDER BY timestamp DESC LIMIT 8
            """)
            recent_logs = [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            print(f"Error fetching audit logs for dashboard: {e}")

        # Recent completed matches
        try:
            cursor.execute("""
                SELECT m.id, m.ground, m.match_format, m.status, m.result_margin, m.match_date,
                       t1.name AS team1_name, t2.name AS team2_name,
                       tw.name AS winner_name
                FROM matches m
                JOIN teams t1 ON m.team1_id = t1.id
                JOIN teams t2 ON m.team2_id = t2.id
                LEFT JOIN teams tw ON m.winner_id = tw.id
                ORDER BY m.id DESC LIMIT 5
            """)
            recent_matches = [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            print(f"Error fetching recent matches for dashboard: {e}")

        conn.close()
    except Exception as e:
        print(f"Dashboard database connection error: {e}")

    metrics = {
        "players": total_players,
        "teams": total_teams,
        "tournaments": total_tournaments,
        "matches": total_matches,
        "completed": completed_matches,
        "live": live_matches_count,
        "upcoming": upcoming_matches,
        "innings": total_innings,
        "deliveries": total_deliveries,
        "total_runs": total_runs,
        "total_wickets": total_wickets
    }

    return render_template(
        'admin/dashboard.html',
        metrics=metrics,
        live_matches=live_matches,
        recent_logs=recent_logs,
        recent_matches=recent_matches
    )


# --- PLAYER MANAGEMENT ---

@admin_bp.route('/players')
@admin_required
def players_list():
    query = request.args.get('q', '').strip()
    role_filter = request.args.get('role', '').strip()
    team_filter = request.args.get('team_id', '').strip()
    page = int(request.args.get('page', 1))
    per_page = 20
    offset = (page - 1) * per_page

    conn = get_db_connection()
    cursor = conn.cursor()

    # Get teams for filter dropdown
    cursor.execute("SELECT id, name FROM teams ORDER BY name ASC")
    all_teams = [dict(row) for row in cursor.fetchall()]

    # Build SQL with dynamic filters
    sql_conditions = []
    sql_params = []

    if query:
        sql_conditions.append("(p.name LIKE ?)")
        sql_params.append(f"%{query}%")

    if role_filter == 'keeper':
        sql_conditions.append("p.is_keeper = 1")
    elif role_filter == 'batter':
        sql_conditions.append("(p.batting_style IS NOT NULL AND p.batting_style != 'None')")
    elif role_filter == 'bowler':
        sql_conditions.append("(p.bowling_style IS NOT NULL AND p.bowling_style != 'None')")

    if team_filter:
        sql_conditions.append("p.id IN (SELECT player_id FROM team_players WHERE team_id = ?)")
        sql_params.append(int(team_filter))

    where_clause = f"WHERE {' AND '.join(sql_conditions)}" if sql_conditions else ""

    # Count query
    count_sql = f"SELECT COUNT(*) FROM players p {where_clause}"
    cursor.execute(count_sql, sql_params)
    total_count = cursor.fetchone()[0]

    # Data query with stats summary
    data_sql = f"""
        SELECT p.id, p.name, p.batting_style, p.bowling_style, p.is_keeper, p.avatar_url,
               COALESCE((SELECT COUNT(DISTINCT match_id) FROM match_players WHERE player_id = p.id), 0) AS matches_played,
               COALESCE((SELECT SUM(runs_batter) FROM deliveries WHERE striker_id = p.id), 0) AS total_runs,
               COALESCE((SELECT COUNT(*) FROM deliveries WHERE bowler_id = p.id AND is_bowler_wicket = 1), 0) AS total_wickets,
               COALESCE((SELECT COUNT(*) FROM deliveries WHERE fielder_id = p.id AND is_wicket = 1), 0) AS total_catches
        FROM players p
        {where_clause}
        ORDER BY p.id ASC
        LIMIT ? OFFSET ?
    """
    cursor.execute(data_sql, sql_params + [per_page, offset])
    players = [dict(row) for row in cursor.fetchall()]

    # Get team associations
    for p in players:
        cursor.execute("""
            SELECT t.id, t.name FROM teams t
            JOIN team_players tp ON t.id = tp.team_id
            WHERE tp.player_id = ?
        """, (p['id'],))
        p['teams'] = [dict(row) for row in cursor.fetchall()]

    conn.close()

    total_pages = max(1, (total_count + per_page - 1) // per_page)

    return render_template(
        'admin/players.html',
        players=players,
        all_teams=all_teams,
        query=query,
        role_filter=role_filter,
        team_filter=team_filter,
        page=page,
        total_pages=total_pages,
        total_count=total_count
    )


@admin_bp.route('/players/new', methods=['GET', 'POST'])
@admin_required
def player_create():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        batting_style = request.form.get('batting_style', 'Right-hand bat')
        bowling_style = request.form.get('bowling_style', 'None')
        is_keeper = 1 if request.form.get('is_keeper') == '1' else 0
        avatar_url = request.form.get('avatar_url', '').strip()
        team_id = request.form.get('team_id')

        if not name:
            flash("Player name is required.", "danger")
            return redirect(url_for('admin.player_create'))

        if not avatar_url:
            avatar_url = f"https://api.dicebear.com/7.x/bottts/svg?seed={name.replace(' ', '')}"

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO players (name, batting_style, bowling_style, is_keeper, avatar_url)
            VALUES (?, ?, ?, ?, ?)
        """, (name, batting_style, bowling_style, is_keeper, avatar_url))
        player_id = cursor.lastrowid

        if team_id:
            cursor.execute("INSERT INTO team_players (team_id, player_id) VALUES (?, ?)", (int(team_id), player_id))

        conn.commit()
        conn.close()

        log_admin_action("create_player", "players", player_id, f"Created player '{name}'")
        flash(f"Player '{name}' successfully created!", "success")
        return redirect(url_for('admin.players_list'))

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM teams ORDER BY name ASC")
    teams = [dict(row) for row in cursor.fetchall()]
    conn.close()

    return render_template('admin/player_form.html', player=None, teams=teams, action_title="Add New Player")


@admin_bp.route('/players/<int:player_id>/edit', methods=['GET', 'POST'])
@admin_required
def player_edit(player_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM players WHERE id = ?", (player_id,))
    player_row = cursor.fetchone()

    if not player_row:
        conn.close()
        flash("Player not found.", "danger")
        return redirect(url_for('admin.players_list'))

    player = dict(player_row)

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        batting_style = request.form.get('batting_style', 'Right-hand bat')
        bowling_style = request.form.get('bowling_style', 'None')
        is_keeper = 1 if request.form.get('is_keeper') == '1' else 0
        avatar_url = request.form.get('avatar_url', '').strip()
        team_id = request.form.get('team_id')

        if not name:
            flash("Player name cannot be empty.", "danger")
            return redirect(url_for('admin.player_edit', player_id=player_id))

        if not avatar_url:
            avatar_url = f"https://api.dicebear.com/7.x/bottts/svg?seed={name.replace(' ', '')}"

        cursor.execute("""
            UPDATE players
            SET name = ?, batting_style = ?, bowling_style = ?, is_keeper = ?, avatar_url = ?
            WHERE id = ?
        """, (name, batting_style, bowling_style, is_keeper, avatar_url, player_id))

        # Update primary team if selected
        if team_id:
            cursor.execute("DELETE FROM team_players WHERE player_id = ?", (player_id,))
            cursor.execute("INSERT INTO team_players (team_id, player_id) VALUES (?, ?)", (int(team_id), player_id))

        conn.commit()
        conn.close()

        log_admin_action("update_player", "players", player_id, f"Updated player '{name}'")
        flash(f"Player '{name}' updated successfully!", "success")
        return redirect(url_for('admin.players_list'))

    # Get player's current teams
    cursor.execute("SELECT team_id FROM team_players WHERE player_id = ?", (player_id,))
    current_teams = [r['team_id'] for r in cursor.fetchall()]
    player['team_id'] = current_teams[0] if current_teams else None

    cursor.execute("SELECT id, name FROM teams ORDER BY name ASC")
    teams = [dict(row) for row in cursor.fetchall()]
    conn.close()

    return render_template('admin/player_form.html', player=player, teams=teams, action_title=f"Edit {player['name']}")


@admin_bp.route('/players/<int:player_id>/delete', methods=['POST'])
@admin_required
def player_delete(player_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM players WHERE id = ?", (player_id,))
    player = cursor.fetchone()

    if not player:
        conn.close()
        flash("Player not found.", "danger")
        return redirect(url_for('admin.players_list'))

    # Check if player has match delivery involvement
    cursor.execute("""
        SELECT COUNT(*) FROM deliveries
        WHERE striker_id = ? OR non_striker_id = ? OR bowler_id = ? OR player_dismissed_id = ? OR fielder_id = ?
    """, (player_id, player_id, player_id, player_id, player_id))
    del_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM match_players WHERE player_id = ?", (player_id,))
    match_count = cursor.fetchone()[0]

    if del_count > 0 or match_count > 0:
        conn.close()
        flash(
            f"Cannot delete player '{player['name']}' because they have active match participation records "
            f"({match_count} matches, {del_count} deliveries involved). Historical integrity requires preserving this player.",
            "danger"
        )
        return redirect(url_for('admin.players_list'))

    cursor.execute("DELETE FROM team_players WHERE player_id = ?", (player_id,))
    cursor.execute("DELETE FROM players WHERE id = ?", (player_id,))
    conn.commit()
    conn.close()

    log_admin_action("delete_player", "players", player_id, f"Deleted player '{player['name']}'")
    flash(f"Player '{player['name']}' removed successfully.", "success")
    return redirect(url_for('admin.players_list'))


# --- TEAM MANAGEMENT ---

@admin_bp.route('/teams')
@admin_required
def teams_list():
    query = request.args.get('q', '').strip()
    conn = get_db_connection()
    cursor = conn.cursor()

    sql = """
        SELECT t.id, t.name, t.logo_url,
               COALESCE((SELECT COUNT(*) FROM team_players WHERE team_id = t.id), 0) AS squad_size,
               COALESCE((SELECT COUNT(*) FROM matches WHERE (team1_id = t.id OR team2_id = t.id) AND status = 'completed'), 0) AS matches_played,
               COALESCE((SELECT COUNT(*) FROM matches WHERE winner_id = t.id AND status = 'completed'), 0) AS matches_won
        FROM teams t
    """
    params = []
    if query:
        sql += " WHERE t.name LIKE ?"
        params.append(f"%{query}%")
    sql += " ORDER BY t.id ASC"

    cursor.execute(sql, params)
    teams = [dict(row) for row in cursor.fetchall()]

    for t in teams:
        mp = t['matches_played']
        mw = t['matches_won']
        t['win_rate'] = round((mw / mp * 100), 1) if mp > 0 else 0.0

    conn.close()
    return render_template('admin/teams.html', teams=teams, query=query)


@admin_bp.route('/teams/new', methods=['GET', 'POST'])
@admin_required
def team_create():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        logo_url = request.form.get('logo_url', '').strip()
        selected_players = request.form.getlist('player_ids')

        if not name:
            flash("Team name is required.", "danger")
            return redirect(url_for('admin.team_create'))

        if not logo_url:
            logo_url = f"https://api.dicebear.com/7.x/identicon/svg?seed={name.replace(' ', '')}"

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO teams (name, logo_url) VALUES (?, ?)", (name, logo_url))
        team_id = cursor.lastrowid

        for pid in selected_players:
            cursor.execute("INSERT INTO team_players (team_id, player_id) VALUES (?, ?)", (team_id, int(pid)))

        conn.commit()
        conn.close()

        log_admin_action("create_team", "teams", team_id, f"Created team '{name}' with {len(selected_players)} players")
        flash(f"Team '{name}' successfully created!", "success")
        return redirect(url_for('admin.teams_list'))

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, batting_style, bowling_style FROM players ORDER BY name ASC")
    all_players = [dict(row) for row in cursor.fetchall()]
    conn.close()

    return render_template('admin/team_form.html', team=None, all_players=all_players, squad_player_ids=[], action_title="Add New Team")


@admin_bp.route('/teams/<int:team_id>/edit', methods=['GET', 'POST'])
@admin_required
def team_edit(team_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM teams WHERE id = ?", (team_id,))
    team_row = cursor.fetchone()

    if not team_row:
        conn.close()
        flash("Team not found.", "danger")
        return redirect(url_for('admin.teams_list'))

    team = dict(team_row)

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        logo_url = request.form.get('logo_url', '').strip()
        selected_players = [int(p) for p in request.form.getlist('player_ids')]

        if not name:
            flash("Team name cannot be empty.", "danger")
            return redirect(url_for('admin.team_edit', team_id=team_id))

        if not logo_url:
            logo_url = f"https://api.dicebear.com/7.x/identicon/svg?seed={name.replace(' ', '')}"

        cursor.execute("UPDATE teams SET name = ?, logo_url = ? WHERE id = ?", (name, logo_url, team_id))

        # Update squad membership without modifying historical match scorecards
        cursor.execute("DELETE FROM team_players WHERE team_id = ?", (team_id,))
        for pid in selected_players:
            cursor.execute("INSERT INTO team_players (team_id, player_id) VALUES (?, ?)", (team_id, pid))

        conn.commit()
        conn.close()

        log_admin_action("update_team", "teams", team_id, f"Updated team '{name}' (squad count: {len(selected_players)})")
        flash(f"Team '{name}' updated successfully! Note: Historical scorecards remain intact.", "success")
        return redirect(url_for('admin.teams_list'))

    # Get squad player IDs
    cursor.execute("SELECT player_id FROM team_players WHERE team_id = ?", (team_id,))
    squad_player_ids = [r['player_id'] for r in cursor.fetchall()]

    cursor.execute("SELECT id, name, batting_style, bowling_style FROM players ORDER BY name ASC")
    all_players = [dict(row) for row in cursor.fetchall()]
    conn.close()

    return render_template(
        'admin/team_form.html',
        team=team,
        all_players=all_players,
        squad_player_ids=squad_player_ids,
        action_title=f"Edit {team['name']}"
    )


@admin_bp.route('/teams/<int:team_id>/delete', methods=['POST'])
@admin_required
def team_delete(team_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM teams WHERE id = ?", (team_id,))
    team = cursor.fetchone()

    if not team:
        conn.close()
        flash("Team not found.", "danger")
        return redirect(url_for('admin.teams_list'))

    # Check if team is part of existing matches
    cursor.execute("SELECT COUNT(*) FROM matches WHERE team1_id = ? OR team2_id = ?", (team_id, team_id))
    match_count = cursor.fetchone()[0]

    if match_count > 0:
        conn.close()
        flash(f"Cannot delete team '{team['name']}' because it is associated with {match_count} match records.", "danger")
        return redirect(url_for('admin.teams_list'))

    cursor.execute("DELETE FROM team_players WHERE team_id = ?", (team_id,))
    cursor.execute("DELETE FROM tournament_teams WHERE team_id = ?", (team_id,))
    cursor.execute("DELETE FROM teams WHERE id = ?", (team_id,))
    conn.commit()
    conn.close()

    log_admin_action("delete_team", "teams", team_id, f"Deleted team '{team['name']}'")
    flash(f"Team '{team['name']}' removed successfully.", "success")
    return redirect(url_for('admin.teams_list'))


# --- TOURNAMENT MANAGEMENT ---

@admin_bp.route('/tournaments')
@admin_required
def tournaments_list():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT t.id, t.name, t.win_points, t.tie_points, t.nr_points,
               COALESCE((SELECT COUNT(*) FROM tournament_teams WHERE tournament_id = t.id), 0) AS team_count,
               COALESCE((SELECT COUNT(*) FROM matches WHERE tournament_id = t.id), 0) AS match_count,
               COALESCE((SELECT COUNT(*) FROM matches WHERE tournament_id = t.id AND status = 'completed'), 0) AS completed_match_count
        FROM tournaments t
        ORDER BY t.id DESC
    """)
    tournaments = [dict(row) for row in cursor.fetchall()]
    conn.close()

    return render_template('admin/tournaments.html', tournaments=tournaments)


@admin_bp.route('/tournaments/new', methods=['GET', 'POST'])
@admin_required
def tournament_create():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        win_points = int(request.form.get('win_points', 2))
        tie_points = int(request.form.get('tie_points', 1))
        nr_points = int(request.form.get('nr_points', 1))
        selected_teams = [int(t) for t in request.form.getlist('team_ids')]

        if not name:
            flash("Tournament name is required.", "danger")
            return redirect(url_for('admin.tournament_create'))

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO tournaments (name, win_points, tie_points, nr_points)
            VALUES (?, ?, ?, ?)
        """, (name, win_points, tie_points, nr_points))
        tourney_id = cursor.lastrowid

        for tid in selected_teams:
            cursor.execute("INSERT INTO tournament_teams (tournament_id, team_id) VALUES (?, ?)", (tourney_id, tid))

        conn.commit()
        conn.close()

        log_admin_action("create_tournament", "tournaments", tourney_id, f"Created tournament '{name}' with {len(selected_teams)} teams")
        flash(f"Tournament '{name}' created successfully!", "success")
        return redirect(url_for('admin.tournaments_list'))

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, logo_url FROM teams ORDER BY name ASC")
    all_teams = [dict(row) for row in cursor.fetchall()]
    conn.close()

    return render_template('admin/tournament_form.html', tournament=None, all_teams=all_teams, selected_team_ids=[], action_title="Add New Tournament")


@admin_bp.route('/tournaments/<int:tournament_id>/edit', methods=['GET', 'POST'])
@admin_required
def tournament_edit(tournament_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tournaments WHERE id = ?", (tournament_id,))
    t_row = cursor.fetchone()

    if not t_row:
        conn.close()
        flash("Tournament not found.", "danger")
        return redirect(url_for('admin.tournaments_list'))

    tournament = dict(t_row)

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        win_points = int(request.form.get('win_points', 2))
        tie_points = int(request.form.get('tie_points', 1))
        nr_points = int(request.form.get('nr_points', 1))
        selected_teams = [int(t) for t in request.form.getlist('team_ids')]

        if not name:
            flash("Tournament name cannot be empty.", "danger")
            return redirect(url_for('admin.tournament_edit', tournament_id=tournament_id))

        cursor.execute("""
            UPDATE tournaments
            SET name = ?, win_points = ?, tie_points = ?, nr_points = ?
            WHERE id = ?
        """, (name, win_points, tie_points, nr_points, tournament_id))

        # Update tournament teams
        cursor.execute("DELETE FROM tournament_teams WHERE tournament_id = ?", (tournament_id,))
        for tid in selected_teams:
            cursor.execute("INSERT INTO tournament_teams (tournament_id, team_id) VALUES (?, ?)", (tournament_id, tid))

        conn.commit()
        conn.close()

        log_admin_action("update_tournament", "tournaments", tournament_id, f"Updated tournament '{name}'")
        flash(f"Tournament '{name}' updated successfully!", "success")
        return redirect(url_for('admin.tournaments_list'))

    cursor.execute("SELECT team_id FROM tournament_teams WHERE tournament_id = ?", (tournament_id,))
    selected_team_ids = [r['team_id'] for r in cursor.fetchall()]

    cursor.execute("SELECT id, name, logo_url FROM teams ORDER BY name ASC")
    all_teams = [dict(row) for row in cursor.fetchall()]
    conn.close()

    return render_template(
        'admin/tournament_form.html',
        tournament=tournament,
        all_teams=all_teams,
        selected_team_ids=selected_team_ids,
        action_title=f"Edit {tournament['name']}"
    )


@admin_bp.route('/tournaments/<int:tournament_id>/standings')
@admin_required
def tournament_standings(tournament_id):
    details = database.get_tournament_details(tournament_id)
    if not details:
        flash("Tournament not found.", "danger")
        return redirect(url_for('admin.tournaments_list'))

    return render_template(
        'admin/tournament_standings.html',
        tournament=details.get('info', {}),
        points_table=details.get('points_table', []),
        matches=details.get('fixtures', [])
    )


@admin_bp.route('/tournaments/<int:tournament_id>/delete', methods=['POST'])
@admin_required
def tournament_delete(tournament_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM tournaments WHERE id = ?", (tournament_id,))
    t = cursor.fetchone()

    if not t:
        conn.close()
        flash("Tournament not found.", "danger")
        return redirect(url_for('admin.tournaments_list'))

    # Unlink matches from tournament or delete tournament
    cursor.execute("UPDATE matches SET tournament_id = NULL WHERE tournament_id = ?", (tournament_id,))
    cursor.execute("DELETE FROM tournament_teams WHERE tournament_id = ?", (tournament_id,))
    cursor.execute("DELETE FROM tournaments WHERE id = ?", (tournament_id,))
    conn.commit()
    conn.close()

    log_admin_action("delete_tournament", "tournaments", tournament_id, f"Deleted tournament '{t['name']}'")
    flash(f"Tournament '{t['name']}' deleted. (Associated matches were unlinked).", "success")
    return redirect(url_for('admin.tournaments_list'))


# --- MATCH MANAGEMENT ---

@admin_bp.route('/matches')
@admin_required
def matches_list():
    status_filter = request.args.get('status', 'all')
    tourney_filter = request.args.get('tournament_id', '')
    team_filter = request.args.get('team_id', '')
    query = request.args.get('q', '').strip()
    page = int(request.args.get('page', 1))
    per_page = 15
    offset = (page - 1) * per_page

    conn = get_db_connection()
    cursor = conn.cursor()

    # Dropdown data
    cursor.execute("SELECT id, name FROM tournaments ORDER BY name ASC")
    all_tournaments = [dict(row) for row in cursor.fetchall()]

    cursor.execute("SELECT id, name FROM teams ORDER BY name ASC")
    all_teams = [dict(row) for row in cursor.fetchall()]

    conditions = []
    params = []

    if status_filter != 'all':
        if status_filter == 'live':
            conditions.append("m.status IN ('live', 'toss_done')")
        else:
            conditions.append("m.status = ?")
            params.append(status_filter)

    if tourney_filter:
        conditions.append("m.tournament_id = ?")
        params.append(int(tourney_filter))

    if team_filter:
        conditions.append("(m.team1_id = ? OR m.team2_id = ?)")
        params.extend([int(team_filter), int(team_filter)])

    if query:
        conditions.append("(t1.name LIKE ? OR t2.name LIKE ? OR m.ground LIKE ?)")
        params.extend([f"%{query}%", f"%{query}%", f"%{query}%"])

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    # Count
    count_sql = f"""
        SELECT COUNT(*)
        FROM matches m
        JOIN teams t1 ON m.team1_id = t1.id
        JOIN teams t2 ON m.team2_id = t2.id
        {where_clause}
    """
    cursor.execute(count_sql, params)
    total_count = cursor.fetchone()[0]

    # Matches
    sql = f"""
        SELECT m.id, m.match_date, m.match_time, m.ground, m.match_format, m.overs_limit,
               m.status, m.result_margin, m.single_batting,
               t1.name AS team1_name, t2.name AS team2_name,
               t1.logo_url AS team1_logo, t2.logo_url AS team2_logo,
               tw.name AS winner_name,
               tour.name AS tournament_name,
               i1.total_runs AS i1_runs, i1.total_wickets AS i1_wkts, i1.balls_bowled AS i1_balls,
               i2.total_runs AS i2_runs, i2.total_wickets AS i2_wkts, i2.balls_bowled AS i2_balls,
               (SELECT COUNT(*) FROM deliveries d JOIN innings inn ON d.innings_id = inn.id WHERE inn.match_id = m.id) AS delivery_count
        FROM matches m
        JOIN teams t1 ON m.team1_id = t1.id
        JOIN teams t2 ON m.team2_id = t2.id
        LEFT JOIN teams tw ON m.winner_id = tw.id
        LEFT JOIN tournaments tour ON m.tournament_id = tour.id
        LEFT JOIN innings i1 ON m.id = i1.match_id AND i1.innings_number = 1
        LEFT JOIN innings i2 ON m.id = i2.match_id AND i2.innings_number = 2
        {where_clause}
        ORDER BY m.id DESC
        LIMIT ? OFFSET ?
    """
    cursor.execute(sql, params + [per_page, offset])
    matches = [dict(row) for row in cursor.fetchall()]
    conn.close()

    total_pages = max(1, (total_count + per_page - 1) // per_page)

    return render_template(
        'admin/matches.html',
        matches=matches,
        all_tournaments=all_tournaments,
        all_teams=all_teams,
        status_filter=status_filter,
        tourney_filter=tourney_filter,
        team_filter=team_filter,
        query=query,
        page=page,
        total_pages=total_pages,
        total_count=total_count
    )


@admin_bp.route('/matches/<int:match_id>', methods=['GET', 'POST'])
@admin_required
def match_detail(match_id):
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT m.*, t1.name AS team1_name, t2.name AS team2_name,
               t1.logo_url AS team1_logo, t2.logo_url AS team2_logo,
               tour.name AS tournament_name
        FROM matches m
        JOIN teams t1 ON m.team1_id = t1.id
        JOIN teams t2 ON m.team2_id = t2.id
        LEFT JOIN tournaments tour ON m.tournament_id = tour.id
        WHERE m.id = ?
    """, (match_id,))
    match_row = cursor.fetchone()

    if not match_row:
        conn.close()
        flash("Match not found.", "danger")
        return redirect(url_for('admin.matches_list'))

    match = dict(match_row)

    if request.method == 'POST':
        action = request.form.get('action_type', 'update_metadata')

        if action == 'update_metadata':
            match_format = request.form.get('match_format', 'T20')
            overs_limit = int(request.form.get('overs_limit', 20))
            ground = request.form.get('ground', '').strip()
            match_date = request.form.get('match_date', '')
            match_time = request.form.get('match_time', '')
            status = request.form.get('status', 'scheduled')
            winner_id = request.form.get('winner_id')
            winner_id = int(winner_id) if winner_id and winner_id != 'None' else None
            result_margin = request.form.get('result_margin', '').strip()
            single_batting = 1 if request.form.get('single_batting') == '1' else 0

            cursor.execute("""
                UPDATE matches
                SET match_format = ?, overs_limit = ?, ground = ?, match_date = ?, match_time = ?,
                    status = ?, winner_id = ?, result_margin = ?, single_batting = ?
                WHERE id = ?
            """, (match_format, overs_limit, ground, match_date, match_time, status, winner_id, result_margin, single_batting, match_id))
            conn.commit()

            log_admin_action("update_match_metadata", "matches", match_id, f"Updated metadata for Match #{match_id}")
            flash("Match metadata updated successfully!", "success")
            trigger_live_update(match_id)

        elif action == 'update_squad':
            team1_players = [int(p) for p in request.form.getlist('team1_players')]
            team2_players = [int(p) for p in request.form.getlist('team2_players')]

            cursor.execute("DELETE FROM match_players WHERE match_id = ?", (match_id,))
            for idx, pid in enumerate(team1_players):
                cursor.execute("INSERT INTO match_players (match_id, team_id, player_id, batting_order) VALUES (?, ?, ?, ?)",
                               (match_id, match['team1_id'], pid, idx + 1))
            for idx, pid in enumerate(team2_players):
                cursor.execute("INSERT INTO match_players (match_id, team_id, player_id, batting_order) VALUES (?, ?, ?, ?)",
                               (match_id, match['team2_id'], pid, idx + 1))
            conn.commit()

            log_admin_action("update_match_squad", "matches", match_id, f"Updated rosters for Match #{match_id}")
            flash("Match rosters updated successfully!", "success")

        conn.close()
        return redirect(url_for('admin.match_detail', match_id=match_id))

    # Fetch Innings summary
    cursor.execute("""
        SELECT * FROM innings WHERE match_id = ? ORDER BY innings_number ASC
    """, (match_id,))
    innings = [dict(row) for row in cursor.fetchall()]

    # Fetch Squad Players
    cursor.execute("""
        SELECT mp.team_id, mp.player_id, mp.batting_order, p.name, p.batting_style, p.bowling_style, p.is_keeper
        FROM match_players mp
        JOIN players p ON mp.player_id = p.id
        WHERE mp.match_id = ?
        ORDER BY mp.team_id, mp.batting_order ASC
    """, (match_id,))
    squad_rows = [dict(row) for row in cursor.fetchall()]
    t1_squad = [p for p in squad_rows if p['team_id'] == match['team1_id']]
    t2_squad = [p for p in squad_rows if p['team_id'] == match['team2_id']]

    # All available players for selection
    cursor.execute("SELECT id, name, batting_style, bowling_style FROM players ORDER BY name ASC")
    all_players = [dict(row) for row in cursor.fetchall()]

    # Delivery count
    cursor.execute("""
        SELECT COUNT(*) FROM deliveries d
        JOIN innings inn ON d.innings_id = inn.id
        WHERE inn.match_id = ?
    """, (match_id,))
    delivery_count = cursor.fetchone()[0]

    conn.close()

    return render_template(
        'admin/match_detail.html',
        match=match,
        innings=innings,
        t1_squad=t1_squad,
        t2_squad=t2_squad,
        all_players=all_players,
        delivery_count=delivery_count
    )


@admin_bp.route('/matches/<int:match_id>/end', methods=['POST'])
@admin_required
def match_end_admin(match_id):
    """Concludes the match, marks innings as completed, and triggers awards/rankings."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE matches SET status = 'completed' WHERE id = ?", (match_id,))
    cursor.execute("UPDATE innings SET status = 'completed' WHERE match_id = ? AND status = 'ongoing'", (match_id,))
    conn.commit()
    conn.close()

    try:
        rebuild_and_cache_match_state(match_id)
        trigger_live_update(match_id)
        log_admin_action("end_match", "matches", match_id, f"Manually concluded Match #{match_id}")
        flash(f"Match #{match_id} concluded and marked as completed.", "success")
    except Exception as e:
        flash(f"Error concluding match: {e}", "danger")
    return redirect(url_for('admin.match_detail', match_id=match_id))


@admin_bp.route('/matches/<int:match_id>/rebuild', methods=['POST'])
@admin_required
def match_rebuild_state(match_id):
    """Replays the delivery logs and updates precomputed match summaries and rankings."""
    try:
        rebuild_and_cache_match_state(match_id)
        log_admin_action("rebuild_match_state", "matches", match_id, f"Forced full state rebuild for Match #{match_id}")
        trigger_live_update(match_id)
        flash(f"Match #{match_id} state completely rebuilt and synchronized from ball logs!", "success")
    except Exception as e:
        flash(f"Error rebuilding match state: {e}", "danger")
    return redirect(url_for('admin.match_detail', match_id=match_id))


@admin_bp.route('/matches/<int:match_id>/delete', methods=['POST'])
@admin_required
def match_delete(match_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM matches WHERE id = ?", (match_id,))
    if not cursor.fetchone():
        conn.close()
        flash("Match not found.", "danger")
        return redirect(url_for('admin.matches_list'))

    # Delete cascading deliveries, substitutions, innings, and match
    cursor.execute("DELETE FROM match_players WHERE match_id = ?", (match_id,))
    cursor.execute("DELETE FROM substitutions WHERE match_id = ?", (match_id,))
    cursor.execute("""
        DELETE FROM deliveries WHERE innings_id IN (SELECT id FROM innings WHERE match_id = ?)
    """, (match_id,))
    cursor.execute("DELETE FROM innings WHERE match_id = ?", (match_id,))
    cursor.execute("DELETE FROM match_awards_override WHERE match_id = ?", (match_id,))
    cursor.execute("DELETE FROM matches WHERE id = ?", (match_id,))
    conn.commit()
    conn.close()

    log_admin_action("delete_match", "matches", match_id, f"Deleted Match #{match_id}")
    flash(f"Match #{match_id} and all related innings and delivery records deleted.", "success")
    return redirect(url_for('admin.matches_list'))


# --- DELIVERY / BALL-BY-BALL MANAGEMENT ---

@admin_bp.route('/matches/<int:match_id>/deliveries')
@admin_required
def match_deliveries(match_id):
    innings_num = int(request.args.get('innings', 1))
    over_filter = request.args.get('over', '')
    page = int(request.args.get('page', 1))
    per_page = 30
    offset = (page - 1) * per_page

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT m.id, m.ground, m.match_format, m.status,
               t1.name AS team1_name, t2.name AS team2_name,
               t1.id AS team1_id, t2.id AS team2_id
        FROM matches m
        JOIN teams t1 ON m.team1_id = t1.id
        JOIN teams t2 ON m.team2_id = t2.id
        WHERE m.id = ?
    """, (match_id,))
    match_row = cursor.fetchone()

    if not match_row:
        conn.close()
        flash("Match not found.", "danger")
        return redirect(url_for('admin.matches_list'))

    match = dict(match_row)

    # Get innings for this match
    cursor.execute("SELECT * FROM innings WHERE match_id = ? ORDER BY innings_number ASC", (match_id,))
    all_innings = [dict(row) for row in cursor.fetchall()]

    selected_innings = next((inn for inn in all_innings if inn['innings_number'] == innings_num), None)

    deliveries = []
    total_deliveries = 0

    if selected_innings:
        conditions = ["d.innings_id = ?"]
        params = [selected_innings['id']]

        if over_filter:
            conditions.append("d.over_number = ?")
            params.append(int(over_filter))

        where_clause = f"WHERE {' AND '.join(conditions)}"

        cursor.execute(f"SELECT COUNT(*) FROM deliveries d {where_clause}", params)
        total_deliveries = cursor.fetchone()[0]

        sql = f"""
            SELECT d.*,
                   ps.name AS striker_name,
                   pn.name AS non_striker_name,
                   pb.name AS bowler_name,
                   pd.name AS dismissed_name,
                   pf.name AS fielder_name
            FROM deliveries d
            LEFT JOIN players ps ON d.striker_id = ps.id
            LEFT JOIN players pn ON d.non_striker_id = pn.id
            LEFT JOIN players pb ON d.bowler_id = pb.id
            LEFT JOIN players pd ON d.player_dismissed_id = pd.id
            LEFT JOIN players pf ON d.fielder_id = pf.id
            {where_clause}
            ORDER BY d.id ASC
            LIMIT ? OFFSET ?
        """
        cursor.execute(sql, params + [per_page, offset])
        deliveries = [dict(row) for row in cursor.fetchall()]

    # Players list for dropdowns
    cursor.execute("SELECT id, name FROM players ORDER BY name ASC")
    all_players = [dict(row) for row in cursor.fetchall()]

    conn.close()

    total_pages = max(1, (total_deliveries + per_page - 1) // per_page)

    return render_template(
        'admin/deliveries.html',
        match=match,
        all_innings=all_innings,
        selected_innings=selected_innings,
        deliveries=deliveries,
        all_players=all_players,
        innings_num=innings_num,
        over_filter=over_filter,
        page=page,
        total_pages=total_pages,
        total_deliveries=total_deliveries
    )


@admin_bp.route('/deliveries/<int:delivery_id>/edit', methods=['GET', 'POST'])
@admin_required
def delivery_edit(delivery_id):
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT d.*, inn.match_id, inn.innings_number
        FROM deliveries d
        JOIN innings inn ON d.innings_id = inn.id
        WHERE d.id = ?
    """, (delivery_id,))
    del_row = cursor.fetchone()

    if not del_row:
        conn.close()
        flash("Delivery not found.", "danger")
        return redirect(url_for('admin.matches_list'))

    delivery = dict(del_row)
    match_id = delivery['match_id']

    if request.method == 'POST':
        striker_id = int(request.form.get('striker_id'))
        non_striker_id = int(request.form.get('non_striker_id'))
        bowler_id = int(request.form.get('bowler_id'))
        runs_batter = int(request.form.get('runs_batter', 0))
        runs_extras = int(request.form.get('runs_extras', 0))
        extra_type = request.form.get('extra_type') or None
        if extra_type == 'None' or extra_type == '':
            extra_type = None

        is_legal = 1 if request.form.get('is_legal') == '1' else 0
        is_wicket = 1 if request.form.get('is_wicket') == '1' else 0
        wicket_type = request.form.get('wicket_type') or None
        if wicket_type == 'None' or wicket_type == '':
            wicket_type = None

        player_dismissed_id = request.form.get('player_dismissed_id')
        player_dismissed_id = int(player_dismissed_id) if player_dismissed_id and player_dismissed_id != 'None' else None

        fielder_id = request.form.get('fielder_id')
        fielder_id = int(fielder_id) if fielder_id and fielder_id != 'None' else None

        is_bowler_wicket = 1 if is_wicket and wicket_type in ['bowled', 'caught', 'lbw', 'stumped', 'hit_wicket'] else 0
        commentary = request.form.get('commentary', '').strip()

        cursor.execute("""
            UPDATE deliveries
            SET striker_id = ?, non_striker_id = ?, bowler_id = ?,
                runs_batter = ?, runs_extras = ?, extra_type = ?, is_legal = ?,
                is_wicket = ?, wicket_type = ?, player_dismissed_id = ?, fielder_id = ?,
                is_bowler_wicket = ?, commentary = ?
            WHERE id = ?
        """, (
            striker_id, non_striker_id, bowler_id,
            runs_batter, runs_extras, extra_type, is_legal,
            is_wicket, wicket_type, player_dismissed_id, fielder_id,
            is_bowler_wicket, commentary, delivery_id
        ))
        conn.commit()
        conn.close()

        # Recalculate full match state from delivery log
        rebuild_and_cache_match_state(match_id)
        trigger_live_update(match_id)

        log_admin_action(
            "edit_delivery", "deliveries", delivery_id,
            f"Edited delivery #{delivery_id} in Match #{match_id} (Over {delivery['over_number']}.{delivery['ball_of_over']})"
        )
        flash(f"Delivery #{delivery_id} updated and match state recalculated successfully!", "success")
        return redirect(url_for('admin.match_deliveries', match_id=match_id, innings=delivery['innings_number']))

    # Match players for dropdowns
    cursor.execute("""
        SELECT mp.player_id, p.name FROM match_players mp
        JOIN players p ON mp.player_id = p.id
        WHERE mp.match_id = ?
        ORDER BY p.name ASC
    """, (match_id,))
    match_players = [dict(row) for row in cursor.fetchall()]

    if not match_players:
        cursor.execute("SELECT id AS player_id, name FROM players ORDER BY name ASC")
        match_players = [dict(row) for row in cursor.fetchall()]

    conn.close()

    return render_template(
        'admin/delivery_form.html',
        delivery=delivery,
        match_players=match_players,
        match_id=match_id
    )


@admin_bp.route('/deliveries/<int:delivery_id>/delete', methods=['POST'])
@admin_required
def delivery_delete(delivery_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT d.id, inn.match_id, inn.innings_number, d.over_number, d.ball_of_over
        FROM deliveries d
        JOIN innings inn ON d.innings_id = inn.id
        WHERE d.id = ?
    """, (delivery_id,))
    row = cursor.fetchone()

    if not row:
        conn.close()
        flash("Delivery not found.", "danger")
        return redirect(url_for('admin.matches_list'))

    match_id = row['match_id']
    inn_num = row['innings_number']
    ball_desc = f"Over {row['over_number']}.{row['ball_of_over']}"

    cursor.execute("DELETE FROM deliveries WHERE id = ?", (delivery_id,))
    conn.commit()
    conn.close()

    # Full recalculation
    rebuild_and_cache_match_state(match_id)
    trigger_live_update(match_id)

    log_admin_action("delete_delivery", "deliveries", delivery_id, f"Deleted ball {ball_desc} from Match #{match_id}")
    flash(f"Delivery #{delivery_id} deleted and match state updated successfully.", "success")
    return redirect(url_for('admin.match_deliveries', match_id=match_id, innings=inn_num))


# --- SCORECARD & INNINGS INSPECTOR ---

@admin_bp.route('/matches/<int:match_id>/scorecard')
@admin_required
def match_scorecard(match_id):
    match_state = database.load_match_state(match_id)
    if not match_state:
        flash("Match state could not be loaded.", "danger")
        return redirect(url_for('admin.matches_list'))

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT m.*, t1.name AS team1_name, t2.name AS team2_name,
               t1.logo_url AS team1_logo, t2.logo_url AS team2_logo
        FROM matches m
        JOIN teams t1 ON m.team1_id = t1.id
        JOIN teams t2 ON m.team2_id = t2.id
        WHERE m.id = ?
    """, (match_id,))
    match_row = cursor.fetchone()
    conn.close()

    return render_template(
        'admin/scorecard.html',
        match=dict(match_row),
        match_state=match_state
    )


# --- AWARDS MANAGEMENT & OVERRIDES ---

@admin_bp.route('/awards')
@admin_required
def awards_list():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT m.id, m.match_date, m.ground, m.match_format, m.result_margin,
               t1.name AS team1_name, t2.name AS team2_name,
               tw.name AS winner_name,
               o.potm_id AS override_potm_id,
               po.name AS override_potm_name,
               o.notes AS override_notes
        FROM matches m
        JOIN teams t1 ON m.team1_id = t1.id
        JOIN teams t2 ON m.team2_id = t2.id
        LEFT JOIN teams tw ON m.winner_id = tw.id
        LEFT JOIN match_awards_override o ON m.id = o.match_id
        LEFT JOIN players po ON o.potm_id = po.id
        WHERE m.status = 'completed'
        ORDER BY m.id DESC
    """)
    completed_matches = [dict(row) for row in cursor.fetchall()]

    # Calculate automatic awards for preview
    for m in completed_matches:
        match_state = database.load_match_state(m['id'])
        if match_state:
            calc_awards = awards.calculate_awards(match_state)
            m['calculated_potm'] = calc_awards.get('potm', {})
            m['calculated_mvp'] = calc_awards.get('mvp', {})
        else:
            m['calculated_potm'] = {}
            m['calculated_mvp'] = {}

    conn.close()
    return render_template('admin/awards.html', matches=completed_matches)


@admin_bp.route('/matches/<int:match_id>/awards', methods=['GET', 'POST'])
@admin_required
def match_awards_detail(match_id):
    match_state = database.load_match_state(match_id)
    if not match_state:
        flash("Match state could not be loaded.", "danger")
        return redirect(url_for('admin.awards_list'))

    calculated = awards.calculate_awards(match_state)

    conn = get_db_connection()
    cursor = conn.cursor()

    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'save_override':
            potm_id = request.form.get('potm_id')
            potm_id = int(potm_id) if potm_id and potm_id != 'None' else None
            best_batter_id = request.form.get('best_batter_id')
            best_batter_id = int(best_batter_id) if best_batter_id and best_batter_id != 'None' else None
            best_bowler_id = request.form.get('best_bowler_id')
            best_bowler_id = int(best_bowler_id) if best_bowler_id and best_bowler_id != 'None' else None
            best_fielder_id = request.form.get('best_fielder_id')
            best_fielder_id = int(best_fielder_id) if best_fielder_id and best_fielder_id != 'None' else None
            mvp_id = request.form.get('mvp_id')
            mvp_id = int(mvp_id) if mvp_id and mvp_id != 'None' else None
            notes = request.form.get('notes', '').strip()

            cursor.execute("DELETE FROM match_awards_override WHERE match_id = ?", (match_id,))
            cursor.execute("""
                INSERT INTO match_awards_override (match_id, potm_id, best_batter_id, best_bowler_id, best_fielder_id, mvp_id, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (match_id, potm_id, best_batter_id, best_bowler_id, best_fielder_id, mvp_id, notes))
            conn.commit()

            log_admin_action("override_awards", "match_awards_override", match_id, f"Saved manual awards override for Match #{match_id}")
            flash("Match awards override saved successfully!", "success")

        elif action == 'clear_override':
            cursor.execute("DELETE FROM match_awards_override WHERE match_id = ?", (match_id,))
            conn.commit()
            log_admin_action("clear_awards_override", "match_awards_override", match_id, f"Reset awards to automatic calculation for Match #{match_id}")
            flash("Awards override cleared. Automatic calculations restored.", "info")

        conn.close()
        return redirect(url_for('admin.match_awards_detail', match_id=match_id))

    # Fetch existing override if any
    cursor.execute("SELECT * FROM match_awards_override WHERE match_id = ?", (match_id,))
    override_row = cursor.fetchone()
    override = dict(override_row) if override_row else None

    # Fetch Match metadata
    cursor.execute("""
        SELECT m.*, t1.name AS team1_name, t2.name AS team2_name
        FROM matches m
        JOIN teams t1 ON m.team1_id = t1.id
        JOIN teams t2 ON m.team2_id = t2.id
        WHERE m.id = ?
    """, (match_id,))
    match_row = cursor.fetchone()

    # Squad players for dropdowns
    cursor.execute("""
        SELECT mp.player_id, p.name FROM match_players mp
        JOIN players p ON mp.player_id = p.id
        WHERE mp.match_id = ?
        ORDER BY p.name ASC
    """, (match_id,))
    match_players = [dict(row) for row in cursor.fetchall()]
    if not match_players:
        cursor.execute("SELECT id AS player_id, name FROM players ORDER BY name ASC")
        match_players = [dict(row) for row in cursor.fetchall()]

    conn.close()

    return render_template(
        'admin/match_awards_detail.html',
        match=dict(match_row),
        calculated=calculated,
        override=override,
        match_players=match_players
    )


# --- CAREER RANKINGS & INACTIVITY ---

@admin_bp.route('/rankings')
@admin_required
def rankings_view():
    player_rankings = rankings.calculate_player_rankings()
    return render_template(
        'admin/rankings.html',
        rankings=player_rankings
    )


@admin_bp.route('/rankings/recalculate', methods=['POST'])
@admin_required
def rankings_recalculate():
    try:
        player_rankings = rankings.calculate_player_rankings()
        log_admin_action("recalculate_rankings", "rankings", None, "Full career rankings recalculation executed")
        flash("Career player rankings successfully recalculated and verified!", "success")
    except Exception as e:
        flash(f"Error recalculating rankings: {e}", "danger")
    return redirect(url_for('admin.rankings_view'))


@admin_bp.route('/inactivity')
@admin_required
def inactivity_view():
    player_rankings = rankings.calculate_player_rankings()
    inactivity_list = player_rankings.get('inactivity_tracking', [])
    return render_template(
        'admin/inactivity.html',
        inactivity_list=inactivity_list,
        total_completed=player_rankings.get('total_completed_matches', 0)
    )


# --- DATA HEALTH & DIAGNOSTICS ---

@admin_bp.route('/data-health')
@admin_required
def data_health():
    conn = get_db_connection()
    cursor = conn.cursor()

    diagnostics = {
        "status": "healthy",
        "issues_found": 0,
        "checks": []
    }

    # 1. DB Connectivity Check
    start_t = datetime.datetime.now()
    cursor.execute("SELECT 1")
    latency_ms = round((datetime.datetime.now() - start_t).total_seconds() * 1000, 2)
    diagnostics["checks"].append({
        "name": "Database Connectivity",
        "status": "PASS",
        "detail": f"Connected successfully (Latency: {latency_ms} ms)"
    })

    # 2. Check for orphaned deliveries (deliveries without valid innings)
    cursor.execute("""
        SELECT COUNT(*) FROM deliveries d
        LEFT JOIN innings inn ON d.innings_id = inn.id
        WHERE inn.id IS NULL
    """)
    orphaned_deliveries = cursor.fetchone()[0]
    if orphaned_deliveries > 0:
        diagnostics["status"] = "warning"
        diagnostics["issues_found"] += orphaned_deliveries
        diagnostics["checks"].append({
            "name": "Orphaned Deliveries",
            "status": "FAIL",
            "detail": f"Found {orphaned_deliveries} deliveries referencing non-existent innings."
        })
    else:
        diagnostics["checks"].append({
            "name": "Orphaned Deliveries Check",
            "status": "PASS",
            "detail": "All deliveries belong to valid innings."
        })

    # 3. Check for innings score vs delivery sum discrepancy
    cursor.execute("""
        SELECT inn.id, inn.match_id, inn.innings_number, inn.total_runs,
               COALESCE(SUM(d.runs_batter + d.runs_extras), 0) AS calc_runs,
               inn.total_wickets,
               COALESCE(SUM(d.is_wicket), 0) AS calc_wkts
        FROM innings inn
        LEFT JOIN deliveries d ON inn.id = d.innings_id
        GROUP BY inn.id, inn.match_id, inn.innings_number, inn.total_runs, inn.total_wickets
        HAVING inn.total_runs != COALESCE(SUM(d.runs_batter + d.runs_extras), 0)
            OR inn.total_wickets != COALESCE(SUM(d.is_wicket), 0)
    """)
    mismatched_innings = cursor.fetchall()
    if mismatched_innings:
        diagnostics["status"] = "warning"
        diagnostics["issues_found"] += len(mismatched_innings)
        diagnostics["checks"].append({
            "name": "Innings State Consistency",
            "status": "FAIL",
            "detail": f"Found {len(mismatched_innings)} innings with score mismatches against delivery logs. Use Auto-Heal below to re-synchronize."
        })
    else:
        diagnostics["checks"].append({
            "name": "Innings State Consistency",
            "status": "PASS",
            "detail": "All innings totals match delivery logs perfectly."
        })

    # 4. Check for orphaned match players
    cursor.execute("""
        SELECT COUNT(*) FROM match_players mp
        LEFT JOIN matches m ON mp.match_id = m.id
        WHERE m.id IS NULL
    """)
    orphaned_mp = cursor.fetchone()[0]
    if orphaned_mp > 0:
        diagnostics["issues_found"] += orphaned_mp
        diagnostics["checks"].append({
            "name": "Orphaned Squad Rosters",
            "status": "FAIL",
            "detail": f"Found {orphaned_mp} match_player records without a valid match."
        })
    else:
        diagnostics["checks"].append({
            "name": "Squad Rosters Integrity",
            "status": "PASS",
            "detail": "All squad records have valid match associations."
        })

    # 5. Check for players without valid names
    cursor.execute("SELECT COUNT(*) FROM players WHERE name IS NULL OR TRIM(name) = ''")
    blank_players = cursor.fetchone()[0]
    if blank_players > 0:
        diagnostics["issues_found"] += blank_players
        diagnostics["checks"].append({
            "name": "Player Data Hygiene",
            "status": "FAIL",
            "detail": f"Found {blank_players} players with empty or invalid names."
        })
    else:
        diagnostics["checks"].append({
            "name": "Player Data Hygiene",
            "status": "PASS",
            "detail": "All registered players have valid names."
        })

    conn.close()
    return render_template('admin/data_health.html', diagnostics=diagnostics)


@admin_bp.route('/data-health/heal', methods=['POST'])
@admin_required
def data_health_heal():
    """Auto-heals cached state inconsistencies by recalculating all matches."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM matches")
    match_ids = [r['id'] for r in cursor.fetchall()]
    conn.close()

    rebuilt_count = 0
    for mid in match_ids:
        try:
            rebuild_and_cache_match_state(mid)
            rebuilt_count += 1
        except Exception as e:
            print(f"Error healing match #{mid}: {e}")

    # Recalculate rankings
    try:
        rankings.calculate_player_rankings()
    except Exception:
        pass

    log_admin_action("auto_heal_database", "system", None, f"Executed Auto-Heal over {rebuilt_count} matches")
    flash(f"Auto-Heal complete! Successfully re-synchronized {rebuilt_count} matches and verified all cached states.", "success")
    return redirect(url_for('admin.data_health'))


# --- BACKUPS & JSON EXPORT ---

@admin_bp.route('/backups')
@admin_required
def backups():
    conn = get_db_connection()
    cursor = conn.cursor()

    stats = {}
    for tbl in ['players', 'teams', 'tournaments', 'matches', 'innings', 'deliveries', 'admin_audit_logs']:
        try:
            cursor.execute(f"SELECT COUNT(*) FROM {tbl}")
            stats[tbl] = cursor.fetchone()[0]
        except Exception:
            stats[tbl] = 0

    conn.close()
    return render_template('admin/backups.html', stats=stats)


@admin_bp.route('/backups/export')
@admin_required
def backup_export():
    """Dumps all key tables to a JSON payload for download."""
    conn = get_db_connection()
    cursor = conn.cursor()

    data = {
        "timestamp": datetime.datetime.now().isoformat(),
        "application": "CricScorer",
        "version": "2.0"
    }

    tables = [
        'players', 'teams', 'tournaments', 'team_players', 'tournament_teams',
        'matches', 'match_players', 'innings', 'substitutions', 'deliveries',
        'match_awards_override'
    ]

    for tbl in tables:
        try:
            cursor.execute(f"SELECT * FROM {tbl}")
            data[tbl] = [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            data[tbl] = []

    conn.close()

    log_admin_action("export_backup", "system", None, f"Exported full JSON backup ({sum(len(v) for k, v in data.items() if isinstance(v, list))} total records)")
    filename = f"cricscorer_backup_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

    return Response(
        json.dumps(data, indent=2, default=str),
        mimetype="application/json",
        headers={"Content-Disposition": f"attachment;filename={filename}"}
    )


# --- AUDIT LOGS ---

@admin_bp.route('/audit-log')
@admin_required
def audit_log():
    page = int(request.args.get('page', 1))
    action_filter = request.args.get('action', '').strip()
    per_page = 25
    offset = (page - 1) * per_page

    conn = get_db_connection()
    cursor = conn.cursor()

    conditions = []
    params = []

    if action_filter:
        conditions.append("action LIKE ?")
        params.append(f"%{action_filter}%")

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    cursor.execute(f"SELECT COUNT(*) FROM admin_audit_logs {where_clause}", params)
    total_count = cursor.fetchone()[0]

    cursor.execute(f"""
        SELECT * FROM admin_audit_logs
        {where_clause}
        ORDER BY timestamp DESC
        LIMIT ? OFFSET ?
    """, params + [per_page, offset])
    logs = [dict(row) for row in cursor.fetchall()]

    conn.close()
    total_pages = max(1, (total_count + per_page - 1) // per_page)

    return render_template(
        'admin/audit_log.html',
        logs=logs,
        action_filter=action_filter,
        page=page,
        total_pages=total_pages,
        total_count=total_count
    )


@admin_bp.route('/audit-log/clear', methods=['POST'])
@admin_required
def audit_log_clear():
    days = int(request.form.get('days', 30))
    cutoff = (datetime.datetime.now() - datetime.timedelta(days=days)).isoformat()

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM admin_audit_logs WHERE timestamp < ?", (cutoff,))
    deleted = cursor.rowcount if hasattr(cursor, 'rowcount') else 0
    conn.commit()
    conn.close()

    log_admin_action("clear_audit_logs", "admin_audit_logs", None, f"Purged audit logs older than {days} days")
    flash(f"Audit logs older than {days} days cleared.", "info")
    return redirect(url_for('admin.audit_log'))


# --- GLOBAL ADMIN SEARCH ---

@admin_bp.route('/search')
@admin_required
def search():
    q = request.args.get('q', '').strip()
    if not q:
        return render_template('admin/search.html', query='', results={})

    results = database.search_all(q)
    return render_template('admin/search.html', query=q, results=results)
