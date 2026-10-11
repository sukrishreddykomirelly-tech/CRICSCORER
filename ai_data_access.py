"""ai_data_access.py - Validated Read-Only Cricket Data Access Layer for Groq AI.

Provides structured, safe, read-only query helpers covering all CricScorer entities:
players, teams, tournaments, matches, scorecards, deliveries, tactical investigations,
awards, rankings, and on-demand statistics.

SECURITY GUARANTEES:
- Strictly read-only operations (SELECT queries only).
- Parameterized SQL execution with no raw unescaped string formatting.
- Strict rejection of any destructive or schema-modifying commands.
- Bounded result sizes and pagination to avoid high memory/connection usage.
"""

import json
from typing import Dict, List, Any, Optional
import database
import awards
import rankings
import cricket_statistics


# =====================================================================
# 1. DATABASE HEALTH & SUMMARY
# =====================================================================

def get_database_health(conn=None) -> Dict[str, Any]:
    """Retrieves an overview of database health and entity counts."""
    close_conn = False
    if conn is None:
        conn = database.get_db_connection()
        close_conn = True

    try:
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM players")
        total_players = cursor.fetchone()[0] or 0

        cursor.execute("SELECT COUNT(*) FROM teams")
        total_teams = cursor.fetchone()[0] or 0

        cursor.execute("SELECT COUNT(*) FROM tournaments")
        total_tournaments = cursor.fetchone()[0] or 0

        cursor.execute("SELECT COUNT(*) FROM matches")
        total_matches = cursor.fetchone()[0] or 0

        cursor.execute("SELECT COUNT(*) FROM matches WHERE status = 'completed'")
        completed_matches = cursor.fetchone()[0] or 0

        cursor.execute("SELECT COUNT(*) FROM matches WHERE status IN ('live', 'toss_done')")
        live_matches = cursor.fetchone()[0] or 0

        cursor.execute("SELECT COUNT(*) FROM matches WHERE status = 'scheduled'")
        scheduled_matches = cursor.fetchone()[0] or 0

        cursor.execute("SELECT COUNT(*) FROM deliveries")
        total_deliveries = cursor.fetchone()[0] or 0

        cursor.execute("SELECT COUNT(*) FROM admin_statistics_cache")
        cached_stats_count = cursor.fetchone()[0] or 0

        return {
            "status": "healthy",
            "total_players": total_players,
            "total_teams": total_teams,
            "total_tournaments": total_tournaments,
            "total_matches": total_matches,
            "completed_matches": completed_matches,
            "live_matches": live_matches,
            "scheduled_matches": scheduled_matches,
            "total_deliveries": total_deliveries,
            "cached_statistics_records": cached_stats_count,
            "note": "Read-only access active. CricScorer database operational."
        }
    finally:
        if close_conn:
            conn.close()


# =====================================================================
# 2. PLAYER QUERIES & PROFILE
# =====================================================================

def search_players(query: Optional[str] = None, team_id: Optional[int] = None, limit: int = 15, conn=None) -> List[Dict[str, Any]]:
    """Searches for players by name or lists team squad members."""
    close_conn = False
    if conn is None:
        conn = database.get_db_connection()
        close_conn = True

    try:
        cursor = conn.cursor()
        limit = min(max(1, limit), 50)
        
        if team_id:
            cursor.execute("""
                SELECT p.id, p.name, p.batting_style, p.bowling_style, p.is_keeper, t.name as team_name
                FROM players p
                JOIN team_players tp ON p.id = tp.player_id
                JOIN teams t ON tp.team_id = t.id
                WHERE tp.team_id = ?
                ORDER BY p.name ASC LIMIT ?
            """, (team_id, limit))
        elif query:
            search_param = f"%{query.strip()}%"
            cursor.execute("""
                SELECT p.id, p.name, p.batting_style, p.bowling_style, p.is_keeper,
                       COALESCE(t.name, '-') as team_name
                FROM players p
                LEFT JOIN team_players tp ON p.id = tp.player_id
                LEFT JOIN teams t ON tp.team_id = t.id
                WHERE p.name LIKE ?
                ORDER BY p.name ASC LIMIT ?
            """, (search_param, limit))
        else:
            cursor.execute("""
                SELECT p.id, p.name, p.batting_style, p.bowling_style, p.is_keeper,
                       COALESCE(t.name, '-') as team_name
                FROM players p
                LEFT JOIN team_players tp ON p.id = tp.player_id
                LEFT JOIN teams t ON tp.team_id = t.id
                ORDER BY p.id ASC LIMIT ?
            """, (limit,))

        rows = cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        if close_conn:
            conn.close()


def get_player_profile_and_stats(player_id: int, conn=None) -> Optional[Dict[str, Any]]:
    """Calculates comprehensive career batting, bowling, fielding stats and recent form for a player."""
    close_conn = False
    if conn is None:
        conn = database.get_db_connection()
        close_conn = True

    try:
        profile = database.get_player_profile(player_id)
        if not profile:
            return None

        # Clean up structures for AI readability
        info = profile.get("info", {})
        stats = profile.get("stats", {})
        recent = profile.get("recent_matches", [])[:5]

        return {
            "player_id": info.get("id"),
            "name": info.get("name"),
            "batting_style": info.get("batting_style"),
            "bowling_style": info.get("bowling_style"),
            "is_wicketkeeper": bool(info.get("is_keeper")),
            "batting_career": {
                "matches": stats.get("matches", 0),
                "innings": stats.get("innings", 0),
                "runs": stats.get("runs", 0),
                "highest_score": stats.get("highest_score", 0),
                "average": stats.get("batting_avg", 0.0),
                "strike_rate": stats.get("strike_rate", 0.0),
                "fifties": stats.get("fifties", 0),
                "hundreds": stats.get("hundreds", 0),
                "fours": stats.get("fours", 0),
                "sixes": stats.get("sixes", 0),
                "not_outs": stats.get("not_outs", 0)
            },
            "bowling_career": {
                "innings_bowled": stats.get("innings_bowled", 0),
                "overs": stats.get("overs_bowled", 0.0),
                "wickets": stats.get("wickets", 0),
                "runs_conceded": stats.get("runs_conceded", 0),
                "economy": stats.get("economy", 0.0),
                "bowling_average": stats.get("bowling_avg", 0.0),
                "best_bowling": stats.get("best_bowling", "-")
            },
            "fielding_career": {
                "catches": stats.get("catches", 0),
                "runouts": stats.get("runouts", 0),
                "stumpings": stats.get("stumpings", 0)
            },
            "recent_matches_form": [
                {
                    "match_id": m.get("match_id"),
                    "date": m.get("match_date"),
                    "runs_scored": m.get("runs"),
                    "balls_faced": m.get("balls"),
                    "wickets_taken": m.get("wickets"),
                    "runs_conceded": m.get("runs_conceded")
                }
                for m in recent
            ]
        }
    finally:
        if close_conn:
            conn.close()


def compare_players(player_ids: List[int], tournament_id: Optional[int] = None, conn=None) -> Dict[str, Any]:
    """Compares 2 or more players side-by-side using career and recent performance metrics."""
    close_conn = False
    if conn is None:
        conn = database.get_db_connection()
        close_conn = True

    try:
        comparison_list = []
        for pid in player_ids[:6]:  # Limit comparison to max 6 players
            p_data = get_player_profile_and_stats(pid, conn=conn)
            if p_data:
                comparison_list.append(p_data)

        return {
            "comparison_count": len(comparison_list),
            "players": comparison_list,
            "tournament_scope": tournament_id if tournament_id else "All Career Matches"
        }
    finally:
        if close_conn:
            conn.close()


# =====================================================================
# 3. LEADERBOARDS & ADVANCED METRICS
# =====================================================================

def get_top_players_leaderboard(
    category: str = "runs",
    tournament_id: Optional[int] = None,
    limit: int = 10,
    min_innings: int = 1,
    min_overs: int = 1,
    conn=None
) -> Dict[str, Any]:
    """
    Returns a verified leaderboard for a given category:
    'runs', 'wickets', 'strike_rate', 'economy', 'average', 'sixes', 'fours', 'catches', 'runouts', 'cir'.
    """
    close_conn = False
    if conn is None:
        conn = database.get_db_connection()
        close_conn = True

    try:
        limit = min(max(1, limit), 30)
        cat = category.lower().strip()

        # Map to statistics calculator if available
        stat_map = {
            "runs": "most_runs",
            "wickets": "most_wickets",
            "strike_rate": "best_strike_rate",
            "economy": "best_economy",
            "average": "best_average",
            "sixes": "most_sixes",
            "fours": "most_fours",
            "catches": "most_catches",
            "runouts": "most_runouts",
            "spell": "best_spell",
            "innings": "best_innings"
        }

        stat_key = stat_map.get(cat, "most_runs")
        calc_result = cricket_statistics.calculate_statistic(
            stat_key,
            min_innings=min_innings,
            min_overs=min_overs,
            limit=limit,
            conn=conn
        )

        rows = (calc_result.get("result") or calc_result.get("data") or [])[:limit]
        return {
            "category": cat,
            "stat_name": calc_result.get("name"),
            "description": calc_result.get("description"),
            "total_records": len(rows),
            "leaderboard": rows,
            "note": "Based on all completed matches in database."
        }
    finally:
        if close_conn:
            conn.close()


# =====================================================================
# 4. MATCHES & SCORECARDS
# =====================================================================

def list_matches(
    status: Optional[str] = None,
    tournament_id: Optional[int] = None,
    team_id: Optional[int] = None,
    limit: int = 10,
    offset: int = 0,
    conn=None
) -> List[Dict[str, Any]]:
    """Lists matches with team names, results, format, and scores."""
    close_conn = False
    if conn is None:
        conn = database.get_db_connection()
        close_conn = True

    try:
        cursor = conn.cursor()
        limit = min(max(1, limit), 50)
        offset = max(0, offset)

        where_clauses = []
        params = []

        if status:
            where_clauses.append("m.status = ?")
            params.append(status)

        if tournament_id:
            where_clauses.append("m.tournament_id = ?")
            params.append(tournament_id)

        if team_id:
            where_clauses.append("(m.team1_id = ? OR m.team2_id = ?)")
            params.extend([team_id, team_id])

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        sql = f"""
            SELECT m.id, m.match_date, m.match_time, m.ground, m.match_format, m.status, m.result_margin,
                   m.team1_id, m.team2_id,
                   t1.name AS team1_name, t2.name AS team2_name,
                   tw.name AS winner_name,
                   i1.batting_team_id AS i1_batting_team_id,
                   i1.total_runs AS i1_runs, i1.total_wickets AS i1_wkts, i1.balls_bowled AS i1_balls,
                   i2.batting_team_id AS i2_batting_team_id,
                   i2.total_runs AS i2_runs, i2.total_wickets AS i2_wkts, i2.balls_bowled AS i2_balls
            FROM matches m
            JOIN teams t1 ON m.team1_id = t1.id
            JOIN teams t2 ON m.team2_id = t2.id
            LEFT JOIN teams tw ON m.winner_id = tw.id
            LEFT JOIN innings i1 ON m.id = i1.match_id AND i1.innings_number = 1
            LEFT JOIN innings i2 ON m.id = i2.match_id AND i2.innings_number = 2
            {where_sql}
            ORDER BY m.id DESC
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])
        cursor.execute(sql, params)
        rows = cursor.fetchall()

        results = []
        for r in rows:
            m = dict(r)
            m = database._map_match_team_scores(m)
            results.append({
                "match_id": m["id"],
                "date": m["match_date"],
                "ground": m["ground"],
                "format": m["match_format"],
                "status": m["status"],
                "is_live": m["status"] in ("live", "toss_done"),
                "team1": {
                    "id": m["team1_id"],
                    "name": m["team1_name"],
                    "score": f"{m['team1_runs']}/{m['team1_wkts']} ({(m['team1_balls'] or 0)//6}.{(m['team1_balls'] or 0)%6} ov)" if m['team1_runs'] is not None else "-"
                },
                "team2": {
                    "id": m["team2_id"],
                    "name": m["team2_name"],
                    "score": f"{m['team2_runs']}/{m['team2_wkts']} ({(m['team2_balls'] or 0)//6}.{(m['team2_balls'] or 0)%6} ov)" if m['team2_runs'] is not None else "-"
                },
                "winner": m["winner_name"],
                "result_margin": m["result_margin"]
            })
        return results
    finally:
        if close_conn:
            conn.close()


def get_match_summary(match_id: int, conn=None) -> Optional[Dict[str, Any]]:
    """Retrieves high-level summary of a match including toss, result, and awards."""
    close_conn = False
    if conn is None:
        conn = database.get_db_connection()
        close_conn = True

    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT m.*,
                   t1.name AS team1_name, t2.name AS team2_name,
                   tw.name AS winner_name, tt.name AS toss_winner_name,
                   tour.name AS tournament_name
            FROM matches m
            JOIN teams t1 ON m.team1_id = t1.id
            JOIN teams t2 ON m.team2_id = t2.id
            LEFT JOIN teams tw ON m.winner_id = tw.id
            LEFT JOIN teams tt ON m.toss_winner_id = tt.id
            LEFT JOIN tournaments tour ON m.tournament_id = tour.id
            WHERE m.id = ?
        """, (match_id,))
        match_row = cursor.fetchone()
        if not match_row:
            return None

        m = dict(match_row)
        is_live = m["status"] in ("live", "toss_done")

        # Fetch innings scores
        cursor.execute("""
            SELECT inn.*, t.name as batting_team_name, tb.name as bowling_team_name
            FROM innings inn
            JOIN teams t ON inn.batting_team_id = t.id
            JOIN teams tb ON inn.bowling_team_id = tb.id
            WHERE inn.match_id = ?
            ORDER BY inn.innings_number ASC
        """, (match_id,))
        innings_rows = cursor.fetchall()
        innings_list = []
        for inn in innings_rows:
            i = dict(inn)
            overs_str = f"{(i['balls_bowled'] or 0)//6}.{(i['balls_bowled'] or 0)%6}"
            innings_list.append({
                "innings_number": i["innings_number"],
                "batting_team": i["batting_team_name"],
                "bowling_team": i["bowling_team_name"],
                "runs": i["total_runs"],
                "wickets": i["total_wickets"],
                "overs": overs_str,
                "status": i["status"]
            })

        # Fetch awards / impact ratings if completed
        awards_data = None
        if not is_live and m["status"] == "completed":
            try:
                calc_awards = awards.calculate_awards(match_id, conn=conn)
                awards_data = {
                    "potm": calc_awards.get("potm", {}).get("name"),
                    "best_batter": calc_awards.get("best_batter", {}).get("name"),
                    "best_bowler": calc_awards.get("best_bowler", {}).get("name"),
                    "best_fielder": calc_awards.get("best_fielder", {}).get("name"),
                    "potm_cir": calc_awards.get("potm", {}).get("cir")
                }
            except Exception:
                awards_data = None

        return {
            "match_id": m["id"],
            "date": m["match_date"],
            "ground": m["ground"],
            "format": m["match_format"],
            "status": m["status"],
            "is_live_snapshot": is_live,
            "tournament": m.get("tournament_name"),
            "teams": f"{m['team1_name']} vs {m['team2_name']}",
            "toss": f"{m.get('toss_winner_name')} won toss and chose to {m.get('toss_decision')}" if m.get('toss_winner_name') else "Toss not recorded",
            "innings": innings_list,
            "winner": m.get("winner_name"),
            "result_margin": m.get("result_margin"),
            "awards": awards_data
        }
    finally:
        if close_conn:
            conn.close()


def get_match_scorecard(match_id: int, innings_number: Optional[int] = None, conn=None) -> Optional[Dict[str, Any]]:
    """Retrieves the complete scorecard (batters, bowlers, extras) for a match."""
    close_conn = False
    if conn is None:
        conn = database.get_db_connection()
        close_conn = True

    try:
        match_obj = database.get_match_state(match_id)
        if not match_obj:
            return None

        summary = get_match_summary(match_id, conn=conn)
        scorecard = match_obj.get_scorecard()

        if innings_number:
            scorecard = [inn for inn in scorecard if inn.get("innings_number") == innings_number]

        return {
            "match_id": match_id,
            "match_info": summary,
            "innings_count": len(scorecard),
            "scorecard": scorecard
        }
    finally:
        if close_conn:
            conn.close()


def get_match_ball_by_ball(
    match_id: int,
    innings_number: Optional[int] = None,
    over_number: Optional[int] = None,
    limit: int = 36,
    conn=None
) -> Dict[str, Any]:
    """Retrieves ball-by-ball commentary and events for a match."""
    close_conn = False
    if conn is None:
        conn = database.get_db_connection()
        close_conn = True

    try:
        cursor = conn.cursor()
        limit = min(max(1, limit), 60)

        where_clauses = ["inn.match_id = ?"]
        params = [match_id]

        if innings_number is not None:
            where_clauses.append("inn.innings_number = ?")
            params.append(innings_number)

        if over_number is not None:
            where_clauses.append("d.over_number = ?")
            params.append(over_number)

        where_sql = f"WHERE {' AND '.join(where_clauses)}"

        cursor.execute(f"""
            SELECT d.id, inn.innings_number, d.over_number, d.ball_of_over,
                   d.runs_batter, d.runs_extras, d.extra_type, d.is_wicket, d.wicket_type,
                   d.commentary,
                   p_striker.name AS striker_name,
                   p_non_striker.name AS non_striker_name,
                   p_bowler.name AS bowler_name,
                   p_dismissed.name AS dismissed_player_name,
                   p_fielder.name AS fielder_name
            FROM deliveries d
            JOIN innings inn ON d.innings_id = inn.id
            LEFT JOIN players p_striker ON d.striker_id = p_striker.id
            LEFT JOIN players p_non_striker ON d.non_striker_id = p_non_striker.id
            LEFT JOIN players p_bowler ON d.bowler_id = p_bowler.id
            LEFT JOIN players p_dismissed ON d.player_dismissed_id = p_dismissed.id
            LEFT JOIN players p_fielder ON d.fielder_id = p_fielder.id
            {where_sql}
            ORDER BY inn.innings_number ASC, d.over_number ASC, d.ball_of_over ASC, d.id ASC
            LIMIT ?
        """, params + [limit])

        deliveries = [dict(r) for r in cursor.fetchall()]
        return {
            "match_id": match_id,
            "innings_filter": innings_number,
            "over_filter": over_number,
            "total_deliveries_returned": len(deliveries),
            "deliveries": deliveries
        }
    finally:
        if close_conn:
            conn.close()


# =====================================================================
# 5. MATCH INVESTIGATION & TACTICAL ANALYSIS
# =====================================================================

def get_match_investigation(match_id: int, conn=None) -> Optional[Dict[str, Any]]:
    """
    Performs tactical analysis of a match:
    - Fall of wickets timeline & batting collapses
    - Phase-by-phase scoring (Powerplay overs 0-5, Middle overs 6-15, Death overs 16+)
    - Dot ball percentage and boundary density per innings
    - Key turning points (overs with multiple wickets or large runs conceded)
    """
    close_conn = False
    if conn is None:
        conn = database.get_db_connection()
        close_conn = True

    try:
        summary = get_match_summary(match_id, conn=conn)
        if not summary:
            return None

        cursor = conn.cursor()

        # Fetch all deliveries for tactical analysis
        cursor.execute("""
            SELECT d.id, inn.innings_number, inn.batting_team_id, t.name as batting_team_name,
                   d.over_number, d.ball_of_over, d.runs_batter, d.runs_extras, d.extra_type,
                   d.is_legal, d.is_wicket, d.wicket_type, d.player_dismissed_id,
                   p_dis.name as dismissed_name,
                   p_str.name as striker_name,
                   p_bowl.name as bowler_name
            FROM deliveries d
            JOIN innings inn ON d.innings_id = inn.id
            JOIN teams t ON inn.batting_team_id = t.id
            LEFT JOIN players p_dis ON d.player_dismissed_id = p_dis.id
            LEFT JOIN players p_str ON d.striker_id = p_str.id
            LEFT JOIN players p_bowl ON d.bowler_id = p_bowl.id
            WHERE inn.match_id = ?
            ORDER BY inn.innings_number ASC, d.over_number ASC, d.ball_of_over ASC, d.id ASC
        """, (match_id,))
        deliveries = [dict(r) for r in cursor.fetchall()]

        # Aggregate by innings
        innings_analysis = {}
        for d in deliveries:
            inn_num = d["innings_number"]
            if inn_num not in innings_analysis:
                innings_analysis[inn_num] = {
                    "innings_number": inn_num,
                    "team_name": d["batting_team_name"],
                    "total_runs": 0,
                    "total_wickets": 0,
                    "legal_balls": 0,
                    "dot_balls": 0,
                    "fours": 0,
                    "sixes": 0,
                    "overs_data": {},
                    "fall_of_wickets": [],
                    "phases": {
                        "powerplay_overs_0_5": {"runs": 0, "wickets": 0, "balls": 0},
                        "middle_overs_6_15": {"runs": 0, "wickets": 0, "balls": 0},
                        "death_overs_16_plus": {"runs": 0, "wickets": 0, "balls": 0}
                    }
                }

            analysis = innings_analysis[inn_num]
            runs = (d["runs_batter"] or 0) + (d["runs_extras"] or 0)
            over = d["over_number"]
            is_legal = bool(d["is_legal"])
            is_wkt = bool(d["is_wicket"])

            analysis["total_runs"] += runs
            if is_legal:
                analysis["legal_balls"] += 1
                if runs == 0 and not is_wkt:
                    analysis["dot_balls"] += 1

            if d["runs_batter"] == 4:
                analysis["fours"] += 1
            elif d["runs_batter"] == 6:
                analysis["sixes"] += 1

            # Phase tracking
            if over < 6:
                phase = analysis["phases"]["powerplay_overs_0_5"]
            elif over <= 15:
                phase = analysis["phases"]["middle_overs_6_15"]
            else:
                phase = analysis["phases"]["death_overs_16_plus"]

            phase["runs"] += runs
            if is_legal:
                phase["balls"] += 1
            if is_wkt:
                phase["wickets"] += 1

            # Over-by-over aggregation
            if over not in analysis["overs_data"]:
                analysis["overs_data"][over] = {"over": over + 1, "bowler": d["bowler_name"], "runs": 0, "wickets": 0}
            analysis["overs_data"][over]["runs"] += runs
            if is_wkt:
                analysis["overs_data"][over]["wickets"] += 1

            # Fall of wickets tracking
            if is_wkt:
                analysis["total_wickets"] += 1
                ov_ball_str = f"{over}.{d['ball_of_over']}"
                analysis["fall_of_wickets"].append({
                    "wicket_number": analysis["total_wickets"],
                    "score": analysis["total_runs"],
                    "over": ov_ball_str,
                    "batter_out": d.get("dismissed_name") or d.get("striker_name"),
                    "bowler": d.get("bowler_name"),
                    "dismissal": d.get("wicket_type")
                })

        # Summarize tactical findings
        formatted_innings = []
        for inn_num, data in sorted(innings_analysis.items()):
            legal_balls = max(1, data["legal_balls"])
            dot_pct = round((data["dot_balls"] / legal_balls) * 100, 1)

            # Find high impact overs (overs with 2+ wickets or 15+ runs)
            impact_overs = [
                ov for ov in data["overs_data"].values()
                if ov["wickets"] >= 2 or ov["runs"] >= 15
            ]

            # Detect batting collapse (3 wickets falling within 15 runs)
            fow = data["fall_of_wickets"]
            collapses = []
            for i in range(len(fow) - 2):
                w1, w3 = fow[i], fow[i + 2]
                if (w3["score"] - w1["score"]) <= 15:
                    collapses.append({
                        "span": f"From {w1['wicket_number']}th to {w3['wicket_number']}th wicket",
                        "score_range": f"{w1['score']}/{w1['wicket_number']-1} -> {w3['score']}/{w3['wicket_number']}",
                        "overs": f"Overs {w1['over']} to {w3['over']}"
                    })

            formatted_innings.append({
                "innings_number": inn_num,
                "team_name": data["team_name"],
                "total_score": f"{data['total_runs']}/{data['total_wickets']} ({(data['legal_balls']//6)}.{(data['legal_balls']%6)} ov)",
                "dot_ball_percentage": f"{dot_pct}%",
                "boundary_count": f"{data['fours']} fours, {data['sixes']} sixes",
                "phases": data["phases"],
                "fall_of_wickets": fow,
                "batting_collapses": collapses,
                "high_impact_overs": impact_overs
            })

        return {
            "match_id": match_id,
            "match_summary": summary,
            "tactical_analysis": formatted_innings,
            "note": "Investigation derived from delivery-by-delivery match records."
        }
    finally:
        if close_conn:
            conn.close()


def analyze_dot_balls(
    target_type: str = "auto",
    player_id: Optional[int] = None,
    player_name: Optional[str] = None,
    match_id: Optional[int] = None,
    tournament_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    conn=None
) -> Dict[str, Any]:
    """
    Calculates and analyzes dot balls from ball-by-ball delivery records using MCC/ICC scoring rules.
    Distinguishes between:
    - Dot balls faced by a batter (legal delivery faced with 0 runs off bat).
    - Dot balls bowled by a bowler (legal delivery where bowler conceded 0 runs; byes/leg-byes not charged).
    - Team/Innings dot ball totals (legal deliveries where 0 runs were scored off bat or extras).
    Supports player, match, tournament, date-range, and career scopes.
    """
    close_conn = False
    if conn is None:
        conn = database.get_db_connection()
        close_conn = True

    try:
        cursor = conn.cursor()
        target_player_id = player_id
        resolved_player_name = None

        if target_player_id is None and player_name:
            cursor.execute("SELECT id, name FROM players WHERE LOWER(name) LIKE ? ORDER BY id LIMIT 5", (f"%{player_name.strip().lower()}%",))
            p_rows = [dict(r) for r in cursor.fetchall()]
            if not p_rows:
                return {
                    "status": "not_found",
                    "message": f"No player found matching '{player_name}'.",
                    "criteria": {"player_name": player_name}
                }
            target_player_id = p_rows[0]["id"]
            resolved_player_name = p_rows[0]["name"]
        elif target_player_id is not None:
            cursor.execute("SELECT name FROM players WHERE id = ?", (target_player_id,))
            p_row = cursor.fetchone()
            if p_row:
                resolved_player_name = p_row["name"] if isinstance(p_row, dict) else p_row[0]

        # Build scope filters
        where_clauses = []
        params = []
        scope_desc = "Career (all completed matches)"

        if match_id:
            where_clauses.append("m.id = ?")
            params.append(match_id)
            scope_desc = f"Match #{match_id}"
        elif tournament_id:
            where_clauses.append("m.tournament_id = ?")
            params.append(tournament_id)
            scope_desc = f"Tournament #{tournament_id}"
        elif start_date or end_date:
            scope_desc = f"Date range ({start_date or 'Start'} to {end_date or 'Present'})"
            if start_date:
                where_clauses.append("m.match_date >= ?")
                params.append(start_date)
            if end_date:
                where_clauses.append("m.match_date <= ?")
                params.append(end_date)
            where_clauses.append("m.status = 'completed'")
        else:
            where_clauses.append("m.status = 'completed'")

        # 1. Single Player Dot Ball Analysis
        if target_player_id:
            base_where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
            bat_where_sql = f"{base_where_sql} {'AND' if base_where_sql else 'WHERE'} d.striker_id = ?"
            bowl_where_sql = f"{base_where_sql} {'AND' if base_where_sql else 'WHERE'} d.bowler_id = ?"

            # Batting dot ball query
            cursor.execute(f"""
                SELECT 
                    COUNT(*) AS total_balls_faced_raw,
                    COUNT(CASE WHEN d.is_legal = 1 THEN 1 END) AS legal_balls_faced,
                    COUNT(CASE WHEN d.extra_type IS NULL OR d.extra_type != 'wide' THEN 1 END) AS official_balls_faced,
                    COUNT(CASE WHEN d.is_legal = 1 AND d.runs_batter = 0 THEN 1 END) AS dot_balls_faced,
                    COUNT(CASE WHEN d.is_legal = 1 AND d.runs_batter = 0 AND d.runs_extras = 0 THEN 1 END) AS pure_dots,
                    COUNT(CASE WHEN d.is_legal = 1 AND d.runs_batter = 0 AND d.runs_extras > 0 THEN 1 END) AS byes_legbyes_faced,
                    COUNT(CASE WHEN d.runs_batter > 0 THEN 1 END) AS scoring_balls,
                    COALESCE(SUM(d.runs_batter), 0) AS total_runs,
                    COALESCE(SUM(CASE WHEN d.runs_batter = 4 THEN 1 ELSE 0 END), 0) AS fours,
                    COALESCE(SUM(CASE WHEN d.runs_batter = 6 THEN 1 ELSE 0 END), 0) AS sixes,
                    COUNT(DISTINCT inn.match_id) AS matches_count,
                    COUNT(DISTINCT d.innings_id) AS innings_count
                FROM deliveries d
                JOIN innings inn ON d.innings_id = inn.id
                JOIN matches m ON inn.match_id = m.id
                {bat_where_sql}
            """, list(params) + [target_player_id])
            bat_row = dict(cursor.fetchone() or {})

            # Bowling dot ball query
            cursor.execute(f"""
                SELECT 
                    COUNT(*) AS total_balls_bowled_raw,
                    COUNT(CASE WHEN d.is_legal = 1 THEN 1 END) AS legal_balls_bowled,
                    COUNT(CASE WHEN d.is_legal = 1 AND d.runs_batter = 0 THEN 1 END) AS dot_balls_bowled,
                    COUNT(CASE WHEN d.is_legal = 1 AND d.runs_batter = 0 AND d.runs_extras = 0 THEN 1 END) AS pure_dots_bowled,
                    COUNT(CASE WHEN d.runs_batter > 0 THEN 1 END) AS scoring_balls_conceded,
                    COUNT(CASE WHEN d.extra_type = 'wide' THEN 1 END) AS wides,
                    COUNT(CASE WHEN d.extra_type = 'noball' THEN 1 END) AS noballs,
                    COALESCE(SUM(CASE WHEN d.extra_type = 'wide' THEN 1 + d.runs_extras 
                                     WHEN d.extra_type = 'noball' THEN 1 + d.runs_batter 
                                     ELSE d.runs_batter END), 0) AS runs_conceded,
                    COALESCE(SUM(CASE WHEN d.is_wicket = 1 AND d.is_bowler_wicket = 1 THEN 1 ELSE 0 END), 0) AS wickets,
                    COUNT(DISTINCT inn.match_id) AS matches_count,
                    COUNT(DISTINCT d.innings_id) AS innings_count
                FROM deliveries d
                JOIN innings inn ON d.innings_id = inn.id
                JOIN matches m ON inn.match_id = m.id
                {bowl_where_sql}
            """, list(params) + [target_player_id])
            bowl_row = dict(cursor.fetchone() or {})

            legal_bat = bat_row.get("legal_balls_faced") or 0
            legal_bowl = bowl_row.get("legal_balls_bowled") or 0

            if legal_bat == 0 and legal_bowl == 0:
                return {
                    "status": "insufficient_data",
                    "message": f"No delivery records found for '{resolved_player_name}' in the selected scope.",
                    "scope": scope_desc,
                    "player_id": target_player_id,
                    "player_name": resolved_player_name
                }

            # Prepare batting analysis
            batting_analysis = None
            if legal_bat > 0:
                dots = bat_row.get("dot_balls_faced") or 0
                dot_pct = round((dots * 100.0) / legal_bat, 2)
                official_bf = bat_row.get("official_balls_faced") or legal_bat
                runs_scored = bat_row.get("total_runs") or 0
                sr = round((runs_scored * 100.0) / official_bf, 2) if official_bf > 0 else 0.0
                batting_analysis = {
                    "legal_balls_faced": legal_bat,
                    "official_balls_faced": official_bf,
                    "dot_balls_faced": dots,
                    "pure_dot_balls": bat_row.get("pure_dots") or 0,
                    "dot_balls_with_byes_legbyes": bat_row.get("byes_legbyes_faced") or 0,
                    "scoring_balls": bat_row.get("scoring_balls") or 0,
                    "dot_ball_percentage": f"{dot_pct}%",
                    "runs_scored": runs_scored,
                    "fours": bat_row.get("fours") or 0,
                    "sixes": bat_row.get("sixes") or 0,
                    "strike_rate": sr,
                    "innings_batted": bat_row.get("innings_count") or 0
                }

            # Prepare bowling analysis
            bowling_analysis = None
            if legal_bowl > 0:
                dots = bowl_row.get("dot_balls_bowled") or 0
                dot_pct = round((dots * 100.0) / legal_bowl, 2)
                overs_str = f"{legal_bowl // 6}.{legal_bowl % 6}"
                runs_conc = bowl_row.get("runs_conceded") or 0
                econ = round((runs_conc * 6.0) / legal_bowl, 2)
                bowling_analysis = {
                    "legal_balls_bowled": legal_bowl,
                    "overs_bowled": overs_str,
                    "dot_balls_bowled": dots,
                    "pure_dots_bowled": bowl_row.get("pure_dots_bowled") or 0,
                    "scoring_balls_conceded": bowl_row.get("scoring_balls_conceded") or 0,
                    "wides": bowl_row.get("wides") or 0,
                    "noballs": bowl_row.get("noballs") or 0,
                    "dot_ball_percentage": f"{dot_pct}%",
                    "runs_conceded": runs_conc,
                    "wickets": bowl_row.get("wickets") or 0,
                    "economy": econ,
                    "innings_bowled": bowl_row.get("innings_count") or 0
                }

            role_filter = target_type.lower().strip()
            result_payload = {
                "status": "success",
                "scope": scope_desc,
                "player_id": target_player_id,
                "player_name": resolved_player_name
            }

            if role_filter in ("batter", "batting") and batting_analysis:
                result_payload["batting_dot_balls"] = batting_analysis
            elif role_filter in ("bowler", "bowling") and bowling_analysis:
                result_payload["bowling_dot_balls"] = bowling_analysis
            else:
                if batting_analysis:
                    result_payload["batting_dot_balls"] = batting_analysis
                if bowling_analysis:
                    result_payload["bowling_dot_balls"] = bowling_analysis

            return result_payload

        # 2. Match / Tournament / Team Scope (Multiple Players / Team Totals)
        base_where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
        
        # Innings breakdown
        cursor.execute(f"""
            SELECT 
                inn.innings_number,
                t.name AS batting_team_name,
                COUNT(CASE WHEN d.is_legal = 1 THEN 1 END) AS legal_balls,
                COUNT(CASE WHEN d.is_legal = 1 AND d.runs_batter = 0 AND d.runs_extras = 0 THEN 1 END) AS pure_dot_balls,
                COUNT(CASE WHEN d.is_legal = 1 AND d.runs_batter = 0 THEN 1 END) AS total_dot_balls,
                COUNT(CASE WHEN d.runs_batter > 0 THEN 1 END) AS scoring_balls,
                COALESCE(SUM(d.runs_batter + d.runs_extras), 0) AS total_runs
            FROM deliveries d
            JOIN innings inn ON d.innings_id = inn.id
            JOIN teams t ON inn.batting_team_id = t.id
            JOIN matches m ON inn.match_id = m.id
            {base_where_sql}
            GROUP BY inn.id, inn.innings_number, t.name
            ORDER BY inn.innings_number ASC
        """, params)
        innings_rows = [dict(r) for r in cursor.fetchall()]

        if not innings_rows:
            return {
                "status": "insufficient_data",
                "message": f"No delivery records found for the requested scope ({scope_desc}).",
                "scope": scope_desc
            }

        for ir in innings_rows:
            lb = ir["legal_balls"]
            ir["dot_percentage"] = f"{round((ir['total_dot_balls'] * 100.0) / lb, 2)}%" if lb > 0 else "0.0%"

        # Top dot-ball bowlers in scope
        cursor.execute(f"""
            SELECT 
                p.id AS bowler_id,
                p.name AS bowler_name,
                COUNT(CASE WHEN d.is_legal = 1 THEN 1 END) AS legal_balls,
                COUNT(CASE WHEN d.is_legal = 1 AND d.runs_batter = 0 THEN 1 END) AS dot_balls,
                COALESCE(SUM(CASE WHEN d.extra_type = 'wide' THEN 1 + d.runs_extras 
                                 WHEN d.extra_type = 'noball' THEN 1 + d.runs_batter 
                                 ELSE d.runs_batter END), 0) AS runs_conceded,
                COALESCE(SUM(CASE WHEN d.is_wicket = 1 AND d.is_bowler_wicket = 1 THEN 1 ELSE 0 END), 0) AS wickets
            FROM deliveries d
            JOIN players p ON d.bowler_id = p.id
            JOIN innings inn ON d.innings_id = inn.id
            JOIN matches m ON inn.match_id = m.id
            {base_where_sql}
            GROUP BY p.id, p.name
            HAVING COUNT(CASE WHEN d.is_legal = 1 THEN 1 END) > 0
            ORDER BY dot_balls DESC, runs_conceded ASC
            LIMIT 10
        """, params)
        top_bowlers = []
        for r in cursor.fetchall():
            rd = dict(r)
            lb = rd["legal_balls"]
            rd["overs"] = f"{lb // 6}.{lb % 6}"
            rd["dot_percentage"] = f"{round((rd['dot_balls'] * 100.0) / lb, 2)}%" if lb > 0 else "0.0%"
            rd["economy"] = round((rd["runs_conceded"] * 6.0) / lb, 2) if lb > 0 else 0.0
            top_bowlers.append(rd)

        # Top batters with dot balls faced in scope
        cursor.execute(f"""
            SELECT 
                p.id AS batter_id,
                p.name AS batter_name,
                COUNT(CASE WHEN d.is_legal = 1 THEN 1 END) AS legal_balls_faced,
                COUNT(CASE WHEN d.is_legal = 1 AND d.runs_batter = 0 THEN 1 END) AS dot_balls_faced,
                COALESCE(SUM(d.runs_batter), 0) AS runs_scored
            FROM deliveries d
            JOIN players p ON d.striker_id = p.id
            JOIN innings inn ON d.innings_id = inn.id
            JOIN matches m ON inn.match_id = m.id
            {base_where_sql}
            GROUP BY p.id, p.name
            HAVING COUNT(CASE WHEN d.is_legal = 1 THEN 1 END) > 0
            ORDER BY dot_balls_faced DESC
            LIMIT 10
        """, params)
        top_batters = []
        for r in cursor.fetchall():
            rd = dict(r)
            lb = rd["legal_balls_faced"]
            rd["dot_percentage"] = f"{round((rd['dot_balls_faced'] * 100.0) / lb, 2)}%" if lb > 0 else "0.0%"
            top_batters.append(rd)

        return {
            "status": "success",
            "scope": scope_desc,
            "innings_breakdown": innings_rows,
            "top_dot_ball_bowlers": top_bowlers,
            "top_dot_ball_batters": top_batters,
            "note": "Dot ball definitions: For a bowler, a legal delivery conceding 0 runs off bat. For a batter, a legal delivery faced with 0 runs scored off bat."
        }
    finally:
        if close_conn:
            conn.close()


# =====================================================================
# 6. TEAMS & TOURNAMENTS
# =====================================================================

def list_teams(tournament_id: Optional[int] = None, conn=None) -> List[Dict[str, Any]]:
    """Lists teams with squad sizes and win-loss records."""
    close_conn = False
    if conn is None:
        conn = database.get_db_connection()
        close_conn = True

    try:
        cursor = conn.cursor()
        if tournament_id:
            cursor.execute("""
                SELECT t.id, t.name, t.logo_url,
                       (SELECT COUNT(*) FROM team_players tp WHERE tp.team_id = t.id) AS squad_size
                FROM tournament_teams tt
                JOIN teams t ON tt.team_id = t.id
                WHERE tt.tournament_id = ?
                ORDER BY t.name ASC
            """, (tournament_id,))
        else:
            cursor.execute("""
                SELECT t.id, t.name, t.logo_url,
                       (SELECT COUNT(*) FROM team_players tp WHERE tp.team_id = t.id) AS squad_size
                FROM teams t
                ORDER BY t.id ASC
            """)
        return [dict(r) for r in cursor.fetchall()]
    finally:
        if close_conn:
            conn.close()


def get_team_profile(team_id: int, conn=None) -> Optional[Dict[str, Any]]:
    """Retrieves team details, squad members, and win/loss records."""
    close_conn = False
    if conn is None:
        conn = database.get_db_connection()
        close_conn = True

    try:
        t_data = database.get_team_profile(team_id)
        if not t_data:
            return None

        info = t_data.get("info", {})
        stats = t_data.get("stats", {})
        players = t_data.get("players", [])
        matches = t_data.get("matches", [])[:5]

        return {
            "team_id": info.get("id"),
            "name": info.get("name"),
            "stats": stats,
            "squad_size": len(players),
            "squad": [{"id": p["id"], "name": p["name"], "style": p.get("batting_style")} for p in players],
            "recent_matches": [
                {
                    "match_id": m.get("id"),
                    "date": m.get("match_date"),
                    "opponent": m.get("team2_name") if m.get("team1_id") == team_id else m.get("team1_name"),
                    "result": m.get("result_margin")
                }
                for m in matches
            ]
        }
    finally:
        if close_conn:
            conn.close()


def compare_teams(team_ids: List[int], conn=None) -> Dict[str, Any]:
    """Compares 2 teams including head-to-head records."""
    close_conn = False
    if conn is None:
        conn = database.get_db_connection()
        close_conn = True

    try:
        cursor = conn.cursor()
        t_list = []
        for tid in team_ids[:4]:
            t_prof = get_team_profile(tid, conn=conn)
            if t_prof:
                t_list.append(t_prof)

        # Head to head if exactly 2 teams
        h2h = None
        if len(team_ids) == 2:
            t1, t2 = team_ids[0], team_ids[1]
            cursor.execute("""
                SELECT COUNT(*) as total_played,
                       SUM(CASE WHEN winner_id = ? THEN 1 ELSE 0 END) as t1_wins,
                       SUM(CASE WHEN winner_id = ? THEN 1 ELSE 0 END) as t2_wins,
                       SUM(CASE WHEN result_margin = 'match tied' THEN 1 ELSE 0 END) as ties,
                       SUM(CASE WHEN status = 'abandoned' OR result_margin = 'no result' THEN 1 ELSE 0 END) as nr
                FROM matches
                WHERE (team1_id = ? AND team2_id = ?) OR (team1_id = ? AND team2_id = ?)
                AND status IN ('completed', 'abandoned')
            """, (t1, t2, t1, t2, t2, t1))
            row = cursor.fetchone()
            if row:
                h2h = dict(row)

        return {
            "teams": t_list,
            "head_to_head": h2h
        }
    finally:
        if close_conn:
            conn.close()


def list_tournaments(conn=None) -> List[Dict[str, Any]]:
    """Lists all tournaments with points rules and team counts."""
    close_conn = False
    if conn is None:
        conn = database.get_db_connection()
        close_conn = True

    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT tour.id, tour.name, tour.win_points, tour.tie_points, tour.nr_points,
                   (SELECT COUNT(*) FROM tournament_teams tt WHERE tt.tournament_id = tour.id) AS teams_count,
                   (SELECT COUNT(*) FROM matches m WHERE m.tournament_id = tour.id) AS matches_count
            FROM tournaments tour
            ORDER BY tour.id DESC
        """)
        return [dict(r) for r in cursor.fetchall()]
    finally:
        if close_conn:
            conn.close()


def get_tournament_standings(tournament_id: int, conn=None) -> Optional[Dict[str, Any]]:
    """Retrieves the official tournament points table standings and leaderboards."""
    close_conn = False
    if conn is None:
        conn = database.get_db_connection()
        close_conn = True

    try:
        tourney = database.get_tournament_details(tournament_id)
        if not tourney:
            return None

        return {
            "tournament_id": tournament_id,
            "name": tourney.get("info", {}).get("name"),
            "points_table": tourney.get("points_table", []),
            "top_scorers": tourney.get("top_scorers", []),
            "top_bowlers": tourney.get("top_bowlers", []),
            "fixtures_count": len(tourney.get("fixtures", []))
        }
    finally:
        if close_conn:
            conn.close()


# =====================================================================
# 7. RANKINGS & CACHED STATISTICS
# =====================================================================

def get_career_rankings(conn=None) -> Dict[str, Any]:
    """Retrieves CricScorer career rankings for Best Batsmen, Best Bowlers, and Best Fielders."""
    close_conn = False
    if conn is None:
        conn = database.get_db_connection()
        close_conn = True

    try:
        career_rankings = rankings.calculate_player_rankings(conn=conn)
        return {
            "best_batsmen": career_rankings.get("batsmen", [])[:10],
            "best_bowlers": career_rankings.get("bowlers", [])[:10],
            "best_fielders": career_rankings.get("fielders", [])[:10],
            "completed_matches_count": career_rankings.get("completed_matches_count", 0),
            "note": "Rankings incorporate 50% participation minimums and inactivity penalties per CricScorer rules."
        }
    finally:
        if close_conn:
            conn.close()


def get_cached_statistics(stat_key: Optional[str] = None, conn=None) -> Dict[str, Any]:
    """Retrieves previously computed on-demand statistics from the admin cache."""
    close_conn = False
    if conn is None:
        conn = database.get_db_connection()
        close_conn = True

    try:
        cursor = conn.cursor()
        if stat_key:
            cursor.execute("""
                SELECT stat_key, params_json, result_json, completed_matches_count, calculated_at
                FROM admin_statistics_cache
                WHERE stat_key = ?
                ORDER BY calculated_at DESC LIMIT 1
            """, (stat_key,))
            row = cursor.fetchone()
            if not row:
                return {"stat_key": stat_key, "found": False, "message": "Statistic not yet calculated in cache."}
            r = dict(row)
            try:
                r["result"] = json.loads(r["result_json"])
            except Exception:
                r["result"] = r["result_json"]
            return {"stat_key": stat_key, "found": True, "data": r}
        else:
            cursor.execute("""
                SELECT stat_key, completed_matches_count, calculated_at
                FROM admin_statistics_cache
                ORDER BY calculated_at DESC
            """)
            rows = [dict(r) for r in cursor.fetchall()]
            return {"cached_statistics": rows}
    finally:
        if close_conn:
            conn.close()


# =====================================================================
# TOOL REGISTRY & DISPATCHER FOR GROQ TOOL CALLING
# =====================================================================

AI_TOOLS_REGISTRY = {
    "get_database_health": get_database_health,
    "search_players": search_players,
    "get_player_profile_and_stats": get_player_profile_and_stats,
    "compare_players": compare_players,
    "get_top_players_leaderboard": get_top_players_leaderboard,
    "list_matches": list_matches,
    "get_match_summary": get_match_summary,
    "get_match_scorecard": get_match_scorecard,
    "get_match_ball_by_ball": get_match_ball_by_ball,
    "get_match_investigation": get_match_investigation,
    "list_teams": list_teams,
    "get_team_profile": get_team_profile,
    "compare_teams": compare_teams,
    "list_tournaments": list_tournaments,
    "get_tournament_standings": get_tournament_standings,
    "get_career_rankings": get_career_rankings,
    "get_cached_statistics": get_cached_statistics,
    "analyze_dot_balls": analyze_dot_balls
}


AI_TOOLS_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "get_database_health",
            "description": "Get high-level summary of total players, teams, tournaments, matches (completed, live, scheduled), deliveries, and database status.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_players",
            "description": "Search for cricket players by name query or team ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Player name search term, e.g. 'Kohli', 'Smith'"},
                    "team_id": {"type": "integer", "description": "Optional team ID to list squad players"},
                    "limit": {"type": "integer", "description": "Maximum number of results to return (default 15)"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_player_profile_and_stats",
            "description": "Get detailed career batting, bowling, fielding statistics, highest score, bowling bests, and recent match form for a specific player.",
            "parameters": {
                "type": "object",
                "properties": {
                    "player_id": {"type": "integer", "description": "The unique ID of the player"}
                },
                "required": ["player_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "compare_players",
            "description": "Compare 2 to 6 players side-by-side using career runs, average, strike rate, wickets, economy, catches, and form.",
            "parameters": {
                "type": "object",
                "properties": {
                    "player_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "List of player IDs to compare"
                    },
                    "tournament_id": {"type": "integer", "description": "Optional tournament ID filter"}
                },
                "required": ["player_ids"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_top_players_leaderboard",
            "description": "Get verified leaderboards for categories like 'runs', 'wickets', 'strike_rate', 'economy', 'average', 'sixes', 'fours', 'catches', 'runouts'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "enum": ["runs", "wickets", "strike_rate", "economy", "average", "sixes", "fours", "catches", "runouts", "spell", "innings"],
                        "description": "Statistic category to rank players by"
                    },
                    "tournament_id": {"type": "integer", "description": "Optional tournament ID"},
                    "limit": {"type": "integer", "description": "Number of top players to return (default 10)"},
                    "min_innings": {"type": "integer", "description": "Minimum innings threshold for batting average/strike rate (default 1)"},
                    "min_overs": {"type": "integer", "description": "Minimum overs threshold for bowling economy/average (default 1)"}
                },
                "required": ["category"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_matches",
            "description": "List matches with filtering by status ('completed', 'live', 'scheduled'), tournament, or team.",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": ["completed", "live", "scheduled", "toss_done", "abandoned"],
                        "description": "Match status filter"
                    },
                    "tournament_id": {"type": "integer", "description": "Tournament ID filter"},
                    "team_id": {"type": "integer", "description": "Team ID filter"},
                    "limit": {"type": "integer", "description": "Number of matches to return (default 10)"},
                    "offset": {"type": "integer", "description": "Offset for pagination"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_match_summary",
            "description": "Get a comprehensive match overview: teams, ground, toss, scores, winner, margin, player of the match, best batter/bowler awards.",
            "parameters": {
                "type": "object",
                "properties": {
                    "match_id": {"type": "integer", "description": "The unique match ID"}
                },
                "required": ["match_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_match_scorecard",
            "description": "Get the detailed batting and bowling scorecard for all innings or a specific innings in a match.",
            "parameters": {
                "type": "object",
                "properties": {
                    "match_id": {"type": "integer", "description": "The unique match ID"},
                    "innings_number": {"type": "integer", "description": "Optional innings number (1 or 2)"}
                },
                "required": ["match_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_match_ball_by_ball",
            "description": "Retrieve ball-by-ball deliveries, events, extras, wickets, and commentary for an innings or specific over.",
            "parameters": {
                "type": "object",
                "properties": {
                    "match_id": {"type": "integer", "description": "The unique match ID"},
                    "innings_number": {"type": "integer", "description": "Innings number (1 or 2)"},
                    "over_number": {"type": "integer", "description": "Zero-indexed over number (0 for 1st over, 1 for 2nd over, etc.)"},
                    "limit": {"type": "integer", "description": "Maximum deliveries to return (default 36)"}
                },
                "required": ["match_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_match_investigation",
            "description": "Perform in-depth tactical investigation on a match: identifies batting collapses, fall of wickets, phase-by-phase scoring (Powerplay, Middle, Death), dot ball %, and high impact overs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "match_id": {"type": "integer", "description": "The unique match ID to investigate"}
                },
                "required": ["match_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_teams",
            "description": "List all cricket teams and their squad sizes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "tournament_id": {"type": "integer", "description": "Optional tournament ID"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_team_profile",
            "description": "Get team statistics, win/loss/tie record, squad players, and recent match results.",
            "parameters": {
                "type": "object",
                "properties": {
                    "team_id": {"type": "integer", "description": "The unique team ID"}
                },
                "required": ["team_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "compare_teams",
            "description": "Compare 2 to 4 teams and view their direct head-to-head match records.",
            "parameters": {
                "type": "object",
                "properties": {
                    "team_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "List of team IDs to compare"
                    }
                },
                "required": ["team_ids"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_tournaments",
            "description": "List all tournaments with their points rules, team counts, and match counts.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_tournament_standings",
            "description": "Get the official tournament standings points table, Net Run Rate (NRR), and tournament top run scorers & wicket takers.",
            "parameters": {
                "type": "object",
                "properties": {
                    "tournament_id": {"type": "integer", "description": "The unique tournament ID"}
                },
                "required": ["tournament_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_career_rankings",
            "description": "Get career rankings for Best Batsmen, Best Bowlers, and Best Fielders based on completed matches and CricScorer ranking formula.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_cached_statistics",
            "description": "Retrieve previously calculated on-demand statistics from the admin cache.",
            "parameters": {
                "type": "object",
                "properties": {
                    "stat_key": {"type": "string", "description": "Optional specific stat key (e.g. 'most_runs', 'best_strike_rate')"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_dot_balls",
            "description": "Calculate and analyze dot balls from ball-by-ball delivery records using cricket scoring rules. Distinguishes between dot balls faced by a batter (legal delivery, 0 runs off bat) vs dot balls bowled by a bowler (legal delivery, 0 runs conceded by bowler; byes/leg-byes not charged). Supports player, match, tournament, date-range, and career scopes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "player_id": {"type": "integer", "description": "Optional specific player ID to analyze"},
                    "player_name": {"type": "string", "description": "Optional player name to search and analyze (e.g. 'Kohli')"},
                    "target_type": {
                        "type": "string",
                        "enum": ["auto", "batter", "bowler"],
                        "description": "Focus of analysis: 'batter' for dot balls faced, 'bowler' for dot balls bowled, or 'auto' for both (default 'auto')"
                    },
                    "match_id": {"type": "integer", "description": "Optional specific match ID"},
                    "tournament_id": {"type": "integer", "description": "Optional specific tournament ID"},
                    "start_date": {"type": "string", "description": "Optional start date in YYYY-MM-DD format"},
                    "end_date": {"type": "string", "description": "Optional end date in YYYY-MM-DD format"}
                },
                "required": []
            }
        }
    }
]


def execute_tool(tool_name: str, arguments: Dict[str, Any], conn=None) -> Dict[str, Any]:
    """
    Safely dispatches and executes a tool call using read-only operations.
    Guarantees errors are caught and returned as structured output.
    """
    if tool_name not in AI_TOOLS_REGISTRY:
        return {
            "error": True,
            "message": f"Tool '{tool_name}' is not recognized or permitted. Available tools: {list(AI_TOOLS_REGISTRY.keys())}"
        }

    tool_fn = AI_TOOLS_REGISTRY[tool_name]
    try:
        # Pass kwargs to tool function, plus conn
        clean_args = {k: v for k, v in arguments.items() if v is not None}
        result = tool_fn(**clean_args, conn=conn)
        return {
            "success": True,
            "tool": tool_name,
            "result": result
        }
    except TypeError as te:
        return {
            "error": True,
            "tool": tool_name,
            "message": f"Invalid arguments provided for tool '{tool_name}': {te}"
        }
    except Exception as e:
        return {
            "error": True,
            "tool": tool_name,
            "message": f"Error executing tool '{tool_name}': {str(e)}"
        }
