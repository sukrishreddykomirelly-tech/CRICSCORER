# app.py
import os
import json
import queue
import mimetypes
from flask import Flask, render_template, request, jsonify, Response, redirect, url_for, g
import database
from database import get_db_connection, save_delivery, delete_last_delivery, rebuild_and_cache_match_state
from admin import admin_bp

# Fix Windows registry MIME type association bug
mimetypes.add_type('text/css', '.css')
mimetypes.add_type('application/javascript', '.js')

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'cricscorer-super-secret-key-2026')
app.register_blueprint(admin_bp)

# Initialize database schema and default admin account on startup (WSGI & CLI safe)
try:
    database.init_db()
    database.seed_db()
    from admin import ensure_admin_table_seeded
    ensure_admin_table_seeded()
except Exception as _startup_e:
    print(f"Startup DB init notice: {_startup_e}")

@app.route('/health')
def health_check():
    return jsonify({"status": "healthy"}), 200

# Real-time SSE Pub-Sub
match_subscribers = {}

def subscribe_to_match(match_id):
    q = queue.Queue(maxsize=10)
    if match_id not in match_subscribers:
        match_subscribers[match_id] = []
    match_subscribers[match_id].append(q)
    return q

def unsubscribe_from_match(match_id, q):
    if match_id in match_subscribers:
        if q in match_subscribers[match_id]:
            match_subscribers[match_id].remove(q)
        if not match_subscribers[match_id]:
            del match_subscribers[match_id]

def notify_match_update(match_id):
    if match_id in match_subscribers:
        for q in match_subscribers[match_id]:
            try:
                q.put_nowait(True)
            except queue.Full:
                pass

# --- MATCH JSON SERIALIZER ---

def get_match_json_state(match_id):
    match_state = database.load_match_state(match_id)
    if not match_state:
        return None
        
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get team names & logos
    cursor.execute("SELECT name, logo_url FROM teams WHERE id = ?", (match_state.team1_id,))
    t1_row = cursor.fetchone()
    cursor.execute("SELECT name, logo_url FROM teams WHERE id = ?", (match_state.team2_id,))
    t2_row = cursor.fetchone()
    
    team1_name = t1_row['name'] if t1_row else "Team 1"
    team1_logo = t1_row['logo_url'] if t1_row else ""
    team2_name = t2_row['name'] if t2_row else "Team 2"
    team2_logo = t2_row['logo_url'] if t2_row else ""
    
    # Get match details
    cursor.execute("SELECT ground, match_date, match_time, tournament_id FROM matches WHERE id = ?", (match_id,))
    m_details = cursor.fetchone()
    
    # Retrieve Squad Rosters
    cursor.execute("""
        SELECT mp.team_id, mp.player_id, p.name 
        FROM match_players mp
        JOIN players p ON mp.player_id = p.id
        WHERE mp.match_id = ?
    """, (match_id,))
    mp_rows = cursor.fetchall()
    team1_squad = []
    team2_squad = []
    for row in mp_rows:
        p_dict = {"id": row['player_id'], "name": row['name']}
        if row['team_id'] == match_state.team1_id:
            team1_squad.append(p_dict)
        else:
            team2_squad.append(p_dict)
            
    conn.close()
    
    innings_list = []
    for inn in match_state.innings:
        # Resolve striker, non-striker, bowler details
        striker_name = match_state.player_names.get(inn.striker_id, "")
        non_striker_name = match_state.player_names.get(inn.non_striker_id, "")
        bowler_name = match_state.player_names.get(inn.bowler_id, "")
        
        # Calculate recent over deliveries (visual format)
        # We group deliveries of the active over
        current_over_number = (inn.balls_bowled // 6) + 1
        over_balls_log = []
        for d in inn.deliveries:
            if d.get("over_number") == current_over_number:
                # Format ball visually
                ball_str = ""
                if d.get("extra_type") == "wide":
                    extra_runs = d.get("runs_extras", 0)
                    ball_str = f"{1 + extra_runs}Wd"
                elif d.get("extra_type") == "noball":
                    runs_bat = d.get("runs_batter", 0)
                    runs_ext = d.get("runs_extras", 0)
                    # Show nb
                    nb_total = 1 + runs_bat + runs_ext
                    ball_str = f"{nb_total}Nb"
                elif d.get("is_wicket"):
                    ball_str = "W"
                elif d.get("extra_type") == "bye":
                    ball_str = f"{d.get('runs_extras')}B"
                elif d.get("extra_type") == "legbye":
                    ball_str = f"{d.get('runs_extras')}Lb"
                else:
                    ball_runs = d.get("runs_batter", 0)
                    ball_str = "•" if ball_runs == 0 else str(ball_runs)
                over_balls_log.append(ball_str)
                
        # Hydrate Batter crease scorecard details
        striker_stats = None
        if inn.striker_id:
            s_data = inn.batting_scores.get(inn.striker_id, {
                "runs": 0,
                "balls": 0,
                "fours": 0,
                "sixes": 0
            })
            striker_stats = {
                "id": inn.striker_id,
                "name": striker_name,
                "runs": s_data["runs"],
                "balls": s_data["balls"],
                "fours": s_data["fours"],
                "sixes": s_data["sixes"],
                "sr": round((s_data["runs"] * 100) / s_data["balls"], 1) if s_data["balls"] > 0 else 0.0
            }
            
        non_striker_stats = None
        if inn.non_striker_id:
            ns_data = inn.batting_scores.get(inn.non_striker_id, {
                "runs": 0,
                "balls": 0,
                "fours": 0,
                "sixes": 0
            })
            non_striker_stats = {
                "id": inn.non_striker_id,
                "name": non_striker_name,
                "runs": ns_data["runs"],
                "balls": ns_data["balls"],
                "fours": ns_data["fours"],
                "sixes": ns_data["sixes"],
                "sr": round((ns_data["runs"] * 100) / ns_data["balls"], 1) if ns_data["balls"] > 0 else 0.0
            }
            
        # Hydrate Bowler crease scorecard details
        bowler_stats = None
        if inn.bowler_id:
            b_data = inn.bowling_scores.get(inn.bowler_id, {
                "balls": 0,
                "maidens": 0,
                "runs_conceded": 0,
                "wickets": 0
            })
            bowler_stats = {
                "id": inn.bowler_id,
                "name": bowler_name,
                "overs": f"{b_data['balls'] // 6}.{b_data['balls'] % 6}",
                "maidens": b_data["maidens"],
                "runs": b_data["runs_conceded"],
                "wickets": b_data["wickets"],
                "econ": round((b_data["runs_conceded"] * 6) / b_data["balls"], 2) if b_data["balls"] > 0 else 0.00
            }
            
        # Compile full scorecard representation
        batting_scorecard = []
        for p_id, b_data in inn.batting_scores.items():
            p_name = match_state.player_names.get(p_id, f"Player {p_id}")
            
            # Construct dismissal text
            dismissal_str = "not out"
            if b_data["status"] == "out":
                w_type = b_data["dismissal_type"]
                fielder_n = match_state.player_names.get(b_data["fielder_id"], "")
                bowler_n = match_state.player_names.get(b_data["bowler_id"], "")
                
                if w_type == "bowled":
                    dismissal_str = f"b {bowler_n}"
                elif w_type == "caught":
                    dismissal_str = f"c {fielder_n} b {bowler_n}"
                elif w_type == "lbw":
                    dismissal_str = f"lbw b {bowler_n}"
                elif w_type == "stumped":
                    dismissal_str = f"stumped {fielder_n} b {bowler_n}"
                elif w_type == "run_out":
                    if fielder_n:
                        dismissal_str = f"run out ({fielder_n})"
                    else:
                        dismissal_str = "run out"
                elif w_type == "hit_wicket":
                    dismissal_str = f"hit wicket b {bowler_n}"
                elif w_type == "retired_out":
                    dismissal_str = "retired out"
                elif w_type == "obstructing_field":
                    dismissal_str = "obstructing field"
            elif b_data["status"] == "retired_hurt":
                dismissal_str = "retired hurt"
            elif b_data["status"] == "yet_to_bat":
                continue # don't show yet
                
            batting_scorecard.append({
                "id": p_id,
                "name": p_name,
                "status": b_data["status"],
                "dismissal": dismissal_str,
                "runs": b_data["runs"],
                "balls": b_data["balls"],
                "fours": b_data["fours"],
                "sixes": b_data["sixes"],
                "sr": round((b_data["runs"] * 100) / b_data["balls"], 1) if b_data["balls"] > 0 else 0.0
            })
            
        bowling_scorecard = []
        for p_id, b_data in inn.bowling_scores.items():
            p_name = match_state.player_names.get(p_id, f"Player {p_id}")
            bowling_scorecard.append({
                "id": p_id,
                "name": p_name,
                "overs": f"{b_data['balls'] // 6}.{b_data['balls'] % 6}",
                "maidens": b_data["maidens"],
                "runs": b_data["runs_conceded"],
                "wickets": b_data["wickets"],
                "wides": b_data["wides"],
                "noballs": b_data["noballs"],
                "econ": round((b_data["runs_conceded"] * 6) / b_data["balls"], 2) if b_data["balls"] > 0 else 0.00
            })
            
        # Get commentary in reverse order (newest first)
        # Get commentary in reverse order (newest first)
        commentary_feed = []
        for d in reversed(inn.deliveries):
            commentary_feed.append({
                "overs": f"{d.get('over_number') - 1}.{d.get('ball_of_over')}",
                "event": d.get("commentary", ""),
                "runs": d.get("runs_batter", 0) + d.get("runs_extras", 0),
                "is_wicket": d.get("is_wicket", 0),
                "extra_type": d.get("extra_type")
            })

        last_bowler_id = None
        if inn.deliveries:
            last_bowler_id = inn.deliveries[-1].get('bowler_id')

        innings_list.append({
            "innings_id": inn.innings_id,
            "innings_number": inn.innings_number,
            "batting_team_id": inn.batting_team_id,
            "batting_team_name": team1_name if inn.batting_team_id == match_state.team1_id else team2_name,
            "bowling_team_id": inn.bowling_team_id,
            "bowling_team_name": team2_name if inn.bowling_team_id == match_state.team2_id else team1_name,
            "total_runs": inn.total_runs,
            "total_wickets": inn.total_wickets,
            "balls_bowled": inn.balls_bowled,
            "overs": f"{inn.balls_bowled // 6}.{inn.balls_bowled % 6}",
            "wides": inn.wides,
            "noballs": inn.noballs,
            "byes": inn.byes,
            "legbyes": inn.legbyes,
            "status": inn.status,
            "target": getattr(inn, 'target', None),
            "striker": striker_stats,
            "non_striker": non_striker_stats,
            "bowler": bowler_stats,
            "over_balls_log": over_balls_log,
            "free_hit": inn.free_hit,
            "batting_scorecard": batting_scorecard,
            "bowling_scorecard": bowling_scorecard,
            "commentary": commentary_feed,
            "partnerships": inn.partnerships,
            "fall_of_wickets": inn.fall_of_wickets,
            "last_bowler_id": last_bowler_id
        })
        
    res_dict = {
        "match_id": match_state.match_id,
        "team1_id": match_state.team1_id,
        "team1_name": team1_name,
        "team1_logo": team1_logo,
        "team1_squad": team1_squad,
        "team2_id": match_state.team2_id,
        "team2_name": team2_name,
        "team2_logo": team2_logo,
        "team2_squad": team2_squad,
        "match_format": match_state.match_format,
        "overs_limit": match_state.overs_limit,
        "status": match_state.status,
        "toss_winner_id": match_state.toss_winner_id,
        "toss_decision": match_state.toss_decision,
        "winner_id": match_state.winner_id,
        "result_margin": match_state.result_margin,
        "is_super_over": match_state.is_super_over,
        "single_batting": int(match_state.single_batting),
        "ground": m_details['ground'] if m_details else "",
        "match_date": m_details['match_date'] if m_details else "",
        "match_time": m_details['match_time'] if m_details else "",
        "tournament_id": m_details['tournament_id'] if m_details else None,
        "innings": innings_list,
        "current_innings_idx": match_state.current_innings_idx,
        "substitutions": getattr(match_state, 'substitutions', [])
    }
    
    try:
        from awards import calculate_awards
        res_dict["awards"] = calculate_awards(match_state)
    except Exception as e:
        print(f"Error calculating awards: {e}")
        res_dict["awards"] = None
        
    return res_dict

# --- PAGE ROUTING ---

@app.route('/')
def index():
    live_matches = database.get_live_matches()
    recent_matches = database.get_recent_matches(5)
    
    # Get top active players & teams to show on home dashboard
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, batting_style, avatar_url FROM players ORDER BY id DESC LIMIT 5")
    players = [dict(row) for row in cursor.fetchall()]
    cursor.execute("SELECT id, name, logo_url FROM teams ORDER BY id DESC LIMIT 5")
    teams = [dict(row) for row in cursor.fetchall()]
    cursor.execute("SELECT id, name FROM tournaments ORDER BY id DESC LIMIT 5")
    tournaments = [dict(row) for row in cursor.fetchall()]
    conn.close()

    # Calculate career rankings
    try:
        rankings = database.get_player_rankings()
    except Exception as e:
        print(f"Error fetching rankings: {e}")
        rankings = {
            "total_completed_matches": 0,
            "min_participation": 0,
            "batsmen": [],
            "bowlers": [],
            "fielders": []
        }
    
    return render_template(
        "index.html",
        live_matches=live_matches,
        recent_matches=recent_matches,
        players=players,
        teams=teams,
        tournaments=tournaments,
        rankings=rankings
    )

@app.route('/rankings')
def rankings_page():
    try:
        rankings = database.get_player_rankings()
    except Exception as e:
        print(f"Error fetching rankings: {e}")
        rankings = {
            "total_completed_matches": 0,
            "min_participation": 0,
            "batsmen": [],
            "bowlers": [],
            "fielders": []
        }
    return render_template("rankings.html", rankings=rankings)

@app.route('/api/rankings')
def api_rankings():
    try:
        rankings = database.get_player_rankings()
        return jsonify({"success": True, "data": rankings})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/search')
def search():
    query = request.args.get('q', '')
    results = database.search_all(query)
    return render_template("search.html", results=results, query=query)

# --- PLAYER PROFILE & CREATION ---

@app.route('/player/create', methods=['GET', 'POST'])
def player_create():
    if request.method == 'POST':
        name = request.form['name']
        batting_style = request.form['batting_style']
        bowling_style = request.form['bowling_style']
        is_keeper = 1 if 'is_keeper' in request.form else 0
        avatar_url = f"https://api.dicebear.com/7.x/bottts/svg?seed={name.replace(' ', '')}"
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO players (name, batting_style, bowling_style, is_keeper, avatar_url)
            VALUES (?, ?, ?, ?, ?)
        """, (name, batting_style, bowling_style, is_keeper, avatar_url))
        player_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        return redirect(url_for('player_profile', player_id=player_id))
    return render_template("player_create.html")

@app.route('/player/<int:player_id>')
def player_profile(player_id):
    profile = database.get_player_profile(player_id)
    if not profile:
        return "Player not found", 404
    return render_template("player_profile.html", p=profile)

# --- TEAM PROFILE & CREATION ---

@app.route('/team/create', methods=['GET', 'POST'])
def team_create():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM players ORDER BY name ASC")
    all_players = [dict(row) for row in cursor.fetchall()]
    conn.close()

    if request.method == 'POST':
        name = request.form['name']
        selected_players = request.form.getlist('players')
        logo_url = f"https://api.dicebear.com/7.x/identicon/svg?seed={name.replace(' ', '')}"
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO teams (name, logo_url) VALUES (?, ?)", (name, logo_url))
        team_id = cursor.lastrowid
        
        # Add roster players
        for p_id in selected_players:
            cursor.execute("INSERT INTO team_players (team_id, player_id) VALUES (?, ?)", (team_id, p_id))
            
        conn.commit()
        conn.close()
        
        return redirect(url_for('team_profile', team_id=team_id))
        
    return render_template("team_create.html", all_players=all_players)

@app.route('/team/<int:team_id>')
def team_profile(team_id):
    team_data = database.get_team_profile(team_id)
    if not team_data:
        return "Team not found", 404
        
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, name FROM players 
        WHERE id NOT IN (SELECT player_id FROM team_players WHERE team_id = ?)
        ORDER BY name
    """, (team_id,))
    available_players = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    return render_template("team_profile.html", t=team_data, available_players=available_players)

@app.route('/team/<int:team_id>/add_player', methods=['POST'])
def team_add_player(team_id):
    name = request.form.get('name')
    existing_player_id = request.form.get('existing_player_id')
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if existing_player_id:
        player_id = int(existing_player_id)
        cursor.execute("SELECT COUNT(*) FROM team_players WHERE team_id = ? AND player_id = ?", (team_id, player_id))
        if cursor.fetchone()[0] == 0:
            cursor.execute("INSERT INTO team_players (team_id, player_id) VALUES (?, ?)", (team_id, player_id))
    elif name:
        batting_style = request.form.get('batting_style', 'Right-hand bat')
        bowling_style = request.form.get('bowling_style', 'None')
        is_keeper = 1 if 'is_keeper' in request.form else 0
        avatar_url = f"https://api.dicebear.com/7.x/bottts/svg?seed={name.replace(' ', '')}"
        
        cursor.execute("""
            INSERT INTO players (name, batting_style, bowling_style, is_keeper, avatar_url)
            VALUES (?, ?, ?, ?, ?)
        """, (name, batting_style, bowling_style, is_keeper, avatar_url))
        player_id = cursor.lastrowid
        
        cursor.execute("INSERT INTO team_players (team_id, player_id) VALUES (?, ?)", (team_id, player_id))
        
    conn.commit()
    conn.close()
    return redirect(url_for('team_profile', team_id=team_id))

# --- TOURNAMENTS ---

@app.route('/tournaments', methods=['GET', 'POST'])
def tournaments_list():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if request.method == 'POST':
        name = request.form['name']
        win_pts = int(request.form.get('win_points', 2))
        tie_pts = int(request.form.get('tie_points', 1))
        nr_pts = int(request.form.get('nr_points', 1))
        selected_teams = request.form.getlist('teams')
        
        cursor.execute("INSERT INTO tournaments (name, win_points, tie_points, nr_points) VALUES (?, ?, ?, ?)",
                       (name, win_pts, tie_pts, nr_pts))
        t_id = cursor.lastrowid
        
        for team_id in selected_teams:
            cursor.execute("INSERT INTO tournament_teams (tournament_id, team_id) VALUES (?, ?)", (t_id, team_id))
            
        conn.commit()
        conn.close()
        return redirect(url_for('tournament_detail', tournament_id=t_id))
        
    cursor.execute("SELECT * FROM tournaments ORDER BY id DESC")
    tournaments = [dict(row) for row in cursor.fetchall()]
    cursor.execute("SELECT id, name FROM teams ORDER BY name ASC")
    teams = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    return render_template("tournaments.html", tournaments=tournaments, teams=teams)

@app.route('/tournament/<int:tournament_id>')
def tournament_detail(tournament_id):
    details = database.get_tournament_details(tournament_id)
    if not details:
        return "Tournament not found", 404
    return render_template("tournament_detail.html", tourney=details)

# --- MATCH SETUP & TOSS ---

@app.route('/match/create', methods=['GET', 'POST'])
def match_create():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if request.method == 'POST':
        team1_id = int(request.form['team1'])
        team2_id = int(request.form['team2'])
        match_format = request.form['format']
        overs_limit = int(request.form['overs_limit'])
        ground = request.form['ground']
        match_date = request.form['match_date']
        match_time = request.form['match_time']
        tournament_id = request.form.get('tournament')
        tournament_id = int(tournament_id) if tournament_id else None
        
        team1_xi = request.form.getlist('team1_xi')
        team2_xi = request.form.getlist('team2_xi')
        single_batting = 1 if 'single_batting' in request.form else 0
        
        cursor.execute("""
            INSERT INTO matches (tournament_id, team1_id, team2_id, match_format, overs_limit, ground, match_date, match_time, status, single_batting)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'scheduled', ?)
        """, (tournament_id, team1_id, team2_id, match_format, overs_limit, ground, match_date, match_time, single_batting))
        match_id = cursor.lastrowid
        
        # Insert playing XI rosters
        inserted_players = set()
        for order, p_id in enumerate(team1_xi):
            key = (team1_id, int(p_id))
            if key not in inserted_players:
                cursor.execute("INSERT INTO match_players (match_id, team_id, player_id, batting_order) VALUES (?, ?, ?, ?)",
                               (match_id, team1_id, p_id, order + 1))
                inserted_players.add(key)
        for order, p_id in enumerate(team2_xi):
            key = (team2_id, int(p_id))
            if key not in inserted_players:
                cursor.execute("INSERT INTO match_players (match_id, team_id, player_id, batting_order) VALUES (?, ?, ?, ?)",
                               (match_id, team2_id, p_id, order + 1))
                inserted_players.add(key)
            
        conn.commit()
        conn.close()
        return redirect(url_for('match_toss', match_id=match_id))
        
    cursor.execute("SELECT id, name FROM teams ORDER BY name ASC")
    teams = [dict(row) for row in cursor.fetchall()]
    cursor.execute("SELECT id, name FROM tournaments ORDER BY name ASC")
    tourneys = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    return render_template("match_create.html", teams=teams, tournaments=tourneys)

@app.route('/match/<int:match_id>/toss', methods=['GET', 'POST'])
def match_toss(match_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM matches WHERE id = ?", (match_id,))
    match_row = cursor.fetchone()
    if not match_row:
        conn.close()
        return "Match not found", 404
        
    cursor.execute("SELECT name FROM teams WHERE id = ?", (match_row['team1_id'],))
    t1_name = cursor.fetchone()['name']
    cursor.execute("SELECT name FROM teams WHERE id = ?", (match_row['team2_id'],))
    t2_name = cursor.fetchone()['name']
    
    if request.method == 'POST':
        toss_winner_id = int(request.form['toss_winner'])
        toss_decision = request.form['toss_decision']
        
        cursor.execute("""
            UPDATE matches 
            SET toss_winner_id = ?, toss_decision = ?, status = 'toss_done'
            WHERE id = ?
        """, (toss_winner_id, toss_decision, match_id))
        conn.commit()
        conn.close()
        return redirect(url_for('match_setup_crease', match_id=match_id))
        
    conn.close()
    return render_template(
        "match_toss.html",
        match=dict(match_row),
        t1_id=match_row['team1_id'],
        t1_name=t1_name,
        t2_id=match_row['team2_id'],
        t2_name=t2_name
    )

@app.route('/match/<int:match_id>/setup_crease', methods=['GET', 'POST'])
def match_setup_crease(match_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Load match to identify batting team and lists of players
    cursor.execute("SELECT * FROM matches WHERE id = ?", (match_id,))
    match_row = cursor.fetchone()
    if not match_row:
        conn.close()
        return "Match not found", 404
        
    t1, t2 = match_row['team1_id'], match_row['team2_id']
    toss_winner = match_row['toss_winner_id']
    decision = match_row['toss_decision']
    
    # Determine batting/bowling teams for Innings 1
    # If Team A wins toss and decides to bat -> Team A bats, Team B bowls
    # If Team A wins toss and decides to bowl -> Team B bats, Team A bowls
    if toss_winner == t1:
        bat_team = t1 if decision == 'bat' else t2
        bowl_team = t2 if decision == 'bat' else t1
    else:
        bat_team = t2 if decision == 'bat' else t1
        bowl_team = t1 if decision == 'bat' else t2
        
    # Get player squad lists
    cursor.execute("""
        SELECT mp.player_id, p.name 
        FROM match_players mp
        JOIN players p ON mp.player_id = p.id
        WHERE mp.match_id = ? AND mp.team_id = ?
    """, (match_id, bat_team))
    batters = [dict(row) for row in cursor.fetchall()]
    
    cursor.execute("""
        SELECT mp.player_id, p.name 
        FROM match_players mp
        JOIN players p ON mp.player_id = p.id
        WHERE mp.match_id = ? AND mp.team_id = ?
    """, (match_id, bowl_team))
    bowlers = [dict(row) for row in cursor.fetchall()]
    
    if request.method == 'POST':
        striker_id = int(request.form['striker'])
        non_striker_id = int(request.form['non_striker'])
        bowler_id = int(request.form['bowler'])
        
        # Create Innings 1 row
        cursor.execute("""
            INSERT INTO innings (match_id, innings_number, batting_team_id, bowling_team_id, status)
            VALUES (?, 1, ?, ?, 'ongoing')
        """, (match_id, bat_team, bowl_team))
        innings_id = cursor.lastrowid
        
        # Update match status to live and current innings ID
        cursor.execute("UPDATE matches SET status = 'live', current_innings_id = ? WHERE id = ?", (innings_id, match_id))
        conn.commit()
        
        # We need to save an initial setup delivery or just set crease
        # In our hydrated loader, we read the crease batters from the FIRST delivery in the DB.
        # So we MUST write a dummy setup entry or save crease.
        # To handle crease assignment beautifully, we write a "zero" delivery representing the crease setup!
        # This is clean and matches the replay engine expectations.
        # But wait! If we do that, we have a delivery with 0 runs, not a wicket, etc.
        # Let's save a "dead" delivery that contains the starting batsman and bowler!
        # Wait, if we just save a setup ball where everything is zero and is_legal is 0? No, that would progress score.
        # Better: let's save a record that designates the crease setup, or we can just save it as delivery 0.
        # Let's write the first real delivery in the scoring console. In the console, the striker/non-striker/bowler
        # are posted with the ball event. So we don't need a dummy ball! The very first ball posted will define the starting crease.
        # But wait, to show the scoring screen *before* the first ball is bowled, we need to know who is batting.
        # Let's store the current striker, non-striker, and bowler IDs as fields in the `innings` table!
        # Yes! Let's alter the innings table schema to include these, or just write them to a small cache.
        # Set them for the first innings
        cursor.execute("""
            UPDATE innings 
            SET current_striker_id = ?, current_non_striker_id = ?, current_bowler_id = ?
            WHERE id = ?
        """, (striker_id, non_striker_id, bowler_id, innings_id))
        
        conn.commit()
        conn.close()
        
        return redirect(url_for('match_scoring_console', match_id=match_id))
        
    conn.close()
    return render_template("match_setup_crease.html", match_id=match_id, batters=batters, bowlers=bowlers)

@app.route('/match/<int:match_id>/score')
def match_scoring_console(match_id):
    # dedicated scoring console
    # Fetch match details
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT status, current_innings_id FROM matches WHERE id = ?", (match_id,))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return "Match not found", 404
    if row['status'] == 'completed':
        return redirect(url_for('match_view', match_id=match_id))
        
    return render_template("scoring.html", match_id=match_id, innings_id=row['current_innings_id'])

@app.route('/match/<int:match_id>')
def match_view(match_id):
    # Public live scorecard viewer
    return render_template("match_view.html", match_id=match_id)


# --- SSE AND API ENDPOINTS ---

@app.route('/api/match/<int:match_id>/live_stream')
def live_stream(match_id):
    def event_stream():
        q = subscribe_to_match(match_id)
        # Send initial state
        state = get_match_json_state(match_id)
        if state:
            yield f"data: {json.dumps(state)}\n\n"
        
        try:
            while True:
                # Wait for notifications
                try:
                    updated = q.get(timeout=20.0)
                    if updated:
                        state = get_match_json_state(match_id)
                        if state:
                            yield f"data: {json.dumps(state)}\n\n"
                except queue.Empty:
                    # Heartbeat to keep connection alive
                    yield ": ping\n\n"
        except GeneratorExit:
            pass
        finally:
            unsubscribe_from_match(match_id, q)
            
    return Response(event_stream(), mimetype="text/event-stream")

@app.route('/api/match/<int:match_id>/state')
def api_match_state(match_id):
    state = get_match_json_state(match_id)
    if not state:
        return jsonify({"error": "Match not found"}), 404
    return jsonify(state)

@app.route('/api/match/<int:match_id>/delivery', methods=['POST'])
def api_add_delivery(match_id):
    req = request.get_json()
    innings_id = req['innings_id']
    
    # Save the delivery details to database
    save_delivery(innings_id, req)
    
    notify_match_update(match_id)
    return jsonify({"success": True})

@app.route('/api/match/<int:match_id>/undo', methods=['POST'])
def api_undo_delivery(match_id):
    req = request.get_json()
    innings_id = req['innings_id']
    
    delete_last_delivery(innings_id)
    
    notify_match_update(match_id)
    return jsonify({"success": True})

@app.route('/api/match/<int:match_id>/change_bowler', methods=['POST'])
def api_change_bowler(match_id):
    req = request.get_json()
    innings_id = req['innings_id']
    bowler_id = req['bowler_id']
    
    # Set the bowler in the innings cache
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE innings SET current_bowler_id = ? WHERE id = ?", (bowler_id, innings_id))
    conn.commit()
    conn.close()
    
    notify_match_update(match_id)
    return jsonify({"success": True})

@app.route('/api/match/<int:match_id>/change_batsman', methods=['POST'])
def api_change_batsman(match_id):
    req = request.get_json()
    innings_id = req['innings_id']
    striker_id = req.get('striker_id')
    non_striker_id = req.get('non_striker_id')
    
    conn = get_db_connection()
    cursor = conn.cursor()
    if striker_id:
        cursor.execute("UPDATE innings SET current_striker_id = ? WHERE id = ?", (striker_id, innings_id))
    if non_striker_id:
        cursor.execute("UPDATE innings SET current_non_striker_id = ? WHERE id = ?", (non_striker_id, innings_id))
    conn.commit()
    conn.close()
    
    notify_match_update(match_id)
    return jsonify({"success": True})

@app.route('/api/match/<int:match_id>/start_second_innings', methods=['POST'])
def api_start_second_innings(match_id):
    req = request.get_json()
    striker_id = req['striker_id']
    non_striker_id = req['non_striker_id']
    bowler_id = req['bowler_id']
    
    # Get match details to identify team IDs
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM matches WHERE id = ?", (match_id,))
    m_row = cursor.fetchone()
    
    # Innings 1 was batted by:
    cursor.execute("SELECT batting_team_id, bowling_team_id FROM innings WHERE match_id = ? AND innings_number = 1", (match_id,))
    inn1_row = cursor.fetchone()
    
    # Innings 2 batting team is Innings 1 bowling team
    bat_team = inn1_row['bowling_team_id']
    bowl_team = inn1_row['batting_team_id']
    
    # Create Innings 2 row
    cursor.execute("""
        INSERT INTO innings (match_id, innings_number, batting_team_id, bowling_team_id, status, current_striker_id, current_non_striker_id, current_bowler_id)
        VALUES (?, 2, ?, ?, 'ongoing', ?, ?, ?)
    """, (match_id, bat_team, bowl_team, striker_id, non_striker_id, bowler_id))
    innings_id = cursor.lastrowid
    
    cursor.execute("UPDATE matches SET current_innings_id = ? WHERE id = ?", (innings_id, match_id))
    conn.commit()
    conn.close()
    
    # Rebuild summaries
    rebuild_and_cache_match_state(match_id)
    notify_match_update(match_id)
    return jsonify({"success": True, "innings_id": innings_id})

@app.route('/api/match/<int:match_id>/substitute_player', methods=['POST'])
def api_substitute_player(match_id):
    req = request.get_json()
    outgoing_id = int(req['outgoing_id'])
    incoming_id = int(req['incoming_id'])
    team_id = int(req['team_id'])
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Update match_players table
    cursor.execute("""
        UPDATE match_players
        SET player_id = ?
        WHERE match_id = ? AND team_id = ? AND player_id = ?
    """, (incoming_id, match_id, team_id, outgoing_id))
    
    # 2. Log substitution in substitutions table
    cursor.execute("SELECT current_innings_id FROM matches WHERE id = ?", (match_id,))
    curr_inn_row = cursor.fetchone()
    innings_id = curr_inn_row['current_innings_id'] if curr_inn_row else 0
    
    cursor.execute("""
        INSERT INTO substitutions (match_id, innings_id, outgoing_id, incoming_id)
        VALUES (?, ?, ?, ?)
    """, (match_id, innings_id, outgoing_id, incoming_id))
    
    # 3. If the outgoing player was active at the crease (striker, non-striker, bowler),
    # we should also update the innings crease cache!
    if innings_id:
        cursor.execute("SELECT current_striker_id, current_non_striker_id, current_bowler_id FROM innings WHERE id = ?", (innings_id,))
        inn_row = cursor.fetchone()
        if inn_row:
            if inn_row['current_striker_id'] == outgoing_id:
                cursor.execute("UPDATE innings SET current_striker_id = ? WHERE id = ?", (incoming_id, innings_id))
            if inn_row['current_non_striker_id'] == outgoing_id:
                cursor.execute("UPDATE innings SET current_non_striker_id = ? WHERE id = ?", (incoming_id, innings_id))
            if inn_row['current_bowler_id'] == outgoing_id:
                cursor.execute("UPDATE innings SET current_bowler_id = ? WHERE id = ?", (incoming_id, innings_id))
                
    conn.commit()
    conn.close()
    
    # Rebuild match state cache
    database.rebuild_and_cache_match_state(match_id)
    notify_match_update(match_id)
    return jsonify({"success": True})

@app.route('/api/team/<int:team_id>/players')
def api_team_players(team_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT p.id, p.name 
        FROM team_players tp
        JOIN players p ON tp.player_id = p.id
        WHERE tp.team_id = ?
        ORDER BY p.name ASC
    """, (team_id,))
    players = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify(players)

@app.route('/api/player/<int:player_id>/profile')
def api_player_profile(player_id):
    profile = database.get_player_profile(player_id)
    if not profile:
        return jsonify({"success": False, "error": "Player not found"}), 404
    return jsonify(profile)


@app.route('/api/match/<int:match_id>/end_match', methods=['POST'])
def api_end_match(match_id):
    req = request.get_json() or {}
    outcome_type = req.get('outcome_type', 'completed')
    custom_winner_id = req.get('winner_id')
    custom_margin = req.get('result_margin', '').strip()

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM matches WHERE id = ?", (match_id,))
    match_row = cursor.fetchone()
    if not match_row:
        conn.close()
        return jsonify({"error": "Match not found"}), 404

    # Load match state
    match_state = database.load_match_state(match_id)
    winner_id = match_state.winner_id if match_state else None
    result_margin = match_state.result_margin if match_state else "Match completed"
    status = "completed"

    if outcome_type == 'abandoned':
        status = 'abandoned'
        winner_id = None
        result_margin = custom_margin or "Match abandoned (No result)"
    elif outcome_type == 'tied':
        status = 'completed'
        winner_id = None
        result_margin = custom_margin or "Match tied"
    elif outcome_type == 'custom':
        status = 'completed'
        winner_id = int(custom_winner_id) if custom_winner_id and str(custom_winner_id).lower() != 'none' else winner_id
        result_margin = custom_margin or result_margin
    else:
        # Default auto completion
        status = 'completed'
        cursor.execute("SELECT batting_team_id, bowling_team_id, total_runs FROM innings WHERE match_id = ? ORDER BY innings_number ASC", (match_id,))
        inns = cursor.fetchall()
        if len(inns) >= 2:
            t1_runs = inns[0]['total_runs']
            t2_runs = inns[1]['total_runs']
            if t1_runs > t2_runs:
                winner_id = inns[0]['batting_team_id']
                result_margin = f"Won by {t1_runs - t2_runs} runs"
            elif t2_runs > t1_runs:
                winner_id = inns[1]['batting_team_id']
                result_margin = "Won by wickets"
            else:
                winner_id = None
                result_margin = "Match tied"
        elif len(inns) == 1:
            winner_id = inns[0]['batting_team_id']
            result_margin = f"Completed (1st Inn: {inns[0]['total_runs']})"

    # Update match and innings status
    cursor.execute("""
        UPDATE matches
        SET status = ?, winner_id = ?, result_margin = ?
        WHERE id = ?
    """, (status, winner_id, result_margin, match_id))

    cursor.execute("""
        UPDATE innings
        SET status = 'completed'
        WHERE match_id = ? AND status = 'ongoing'
    """, (match_id,))

    conn.commit()
    conn.close()

    # Rebuild state caches and trigger awards/tournament updates
    database.rebuild_and_cache_match_state(match_id)
    notify_match_update(match_id)

    return jsonify({
        "success": True,
        "match_id": match_id,
        "status": status,
        "winner_id": winner_id,
        "result_margin": result_margin
    })


# --- DYNAMIC INNINGS CREASE HYDRATION IN LOAD STATE ---
# We override load_match_state in database.py to read the active crease values 
# from the innings cache if no deliveries have been bowled yet!
# This is a critical glue step so that the crease players are known before the first delivery.

original_load_match_state = database.load_match_state

def custom_load_match_state(match_id, is_rebuilding=False):
    match_state = original_load_match_state(match_id, is_rebuilding)
    if not match_state or is_rebuilding:
        return match_state
        
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Sync active crease from database cache
    for inn in match_state.innings:
        cursor.execute("""
            SELECT current_striker_id, current_non_striker_id, current_bowler_id 
            FROM innings WHERE id = ?
        """, (inn.innings_id,))
        row = cursor.fetchone()
        if row:
            # Overwrite crease batsmen with cache values (which handles manual swaps and wicket selections)
            if row['current_striker_id'] is not None:
                inn.striker_id = row['current_striker_id']
            else:
                inn.striker_id = None
                
            if row['current_non_striker_id'] is not None:
                inn.non_striker_id = row['current_non_striker_id']
            else:
                inn.non_striker_id = None
                
            if row['current_bowler_id'] is not None:
                # Find the bowler who bowled the last delivery in this innings
                last_bowler_id = None
                if inn.deliveries:
                    last_bowler_id = inn.deliveries[-1].get('bowler_id')
                
                # If an over just completed, only restore if the database has a newly selected bowler
                if inn.balls_bowled > 0 and inn.balls_bowled % 6 == 0:
                    if row['current_bowler_id'] != last_bowler_id:
                        inn.bowler_id = row['current_bowler_id']
                else:
                    inn.bowler_id = row['current_bowler_id']
                
    conn.close()
    return match_state

# Inject custom loader into database module
database.load_match_state = custom_load_match_state


if __name__ == '__main__':
    import os
    # Initialize DB on start
    database.init_db()
    database.seed_db()
    
    port = int(os.environ.get('PORT', 5000))
    debug_mode = os.environ.get('FLASK_DEBUG', 'False').lower() in ('true', '1', 't')
    app.run(debug=debug_mode, host='0.0.0.0', port=port)
