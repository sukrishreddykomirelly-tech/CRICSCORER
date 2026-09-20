"""
rankings.py - Player Career Ranking System for CricScorer.

Implements three independent career rankings (Best Batsman, Best Bowler, Best Fielder)
based on completed matches, existing MVP points, 50% participation eligibility rule,
and global inactivity penalties.
"""

import math
from typing import Dict, List, Any, Optional
from awards import calculate_awards
import database


def calculate_player_rankings(conn=None) -> Dict[str, Any]:
    """
    Computes career rankings for Best Batsmen, Best Bowlers, and Best Fielders.
    Based on completed matches only.
    """
    close_conn = False
    if conn is None:
        conn = database.get_db_connection()
        close_conn = True

    try:
        cursor = conn.cursor()

        # 1. Fetch all registered players
        cursor.execute("SELECT id, name, avatar_url, batting_style, bowling_style, is_keeper FROM players ORDER BY id ASC")
        players_rows = cursor.fetchall()
        players_dict = {
            row['id']: {
                "id": row['id'],
                "name": row['name'],
                "avatar_url": row['avatar_url'] or f"https://api.dicebear.com/7.x/bottts/svg?seed={row['name'].replace(' ', '')}",
                "batting_style": row['batting_style'] or "",
                "bowling_style": row['bowling_style'] or "",
                "is_keeper": row['is_keeper'] or 0,
                "team_name": "-",
                "team_logo": ""
            }
            for row in players_rows
        }

        # Fetch player latest team mappings
        cursor.execute("""
            SELECT tp.player_id, t.name as team_name, t.logo_url as team_logo
            FROM team_players tp
            JOIN teams t ON tp.team_id = t.id
            ORDER BY tp.team_id DESC
        """)
        for r in cursor.fetchall():
            pid = r['player_id']
            if pid in players_dict:
                players_dict[pid]["team_name"] = r['team_name']
                players_dict[pid]["team_logo"] = r['team_logo'] or ""

        # 2. Fetch all completed matches ordered chronologically by ID
        cursor.execute("""
            SELECT id, match_date, match_time, match_format, overs_limit
            FROM matches
            WHERE status = 'completed'
            ORDER BY id ASC
        """)
        completed_matches = cursor.fetchall()
        total_completed = len(completed_matches)

        if total_completed == 0:
            return {
                "total_completed_matches": 0,
                "min_participation": 0,
                "batsmen": [],
                "bowlers": [],
                "fielders": []
            }

        # 50% Rule Eligibility Calculation
        if total_completed < 4:
            min_participation = 1
        else:
            min_participation = math.ceil(total_completed * 0.5)

        # Initialize tracking dictionaries for all registered players
        total_participations: Dict[int, int] = {pid: 0 for pid in players_dict}
        inactivity_streak: Dict[int, int] = {pid: 0 for pid in players_dict}

        # Batting stats
        batting_total_points: Dict[int, float] = {pid: 0.0 for pid in players_dict}
        batting_matches_count: Dict[int, int] = {pid: 0 for pid in players_dict}

        # Bowling stats
        bowling_total_points: Dict[int, float] = {pid: 0.0 for pid in players_dict}
        bowling_matches_count: Dict[int, int] = {pid: 0 for pid in players_dict}

        # Fielding stats
        fielding_total_points: Dict[int, float] = {pid: 0.0 for pid in players_dict}
        fielding_matches_count: Dict[int, int] = {pid: 0 for pid in players_dict}

        # 3. Process completed matches chronologically
        for m_row in completed_matches:
            match_id = m_row['id']
            match_state = database.load_match_state(match_id)
            if not match_state:
                continue

            # Fetch Playing XI player IDs for this match
            cursor.execute("SELECT player_id FROM match_players WHERE match_id = ?", (match_id,))
            playing_xi_ids = {r['player_id'] for r in cursor.fetchall()}

            # Run existing awards computation for this match
            awards = calculate_awards(match_state)
            perf_table = awards.get("performance_table", [])
            perf_by_id = {p["id"]: p for p in perf_table}

            # Identify all players who participated in this match
            match_participating_ids = set(playing_xi_ids)

            # Also check deliveries and scorecards for any participation
            for inn in match_state.innings:
                for p_id, b_data in inn.batting_scores.items():
                    p_id = int(p_id)
                    if b_data.get("balls", 0) > 0 or b_data.get("runs", 0) > 0 or b_data.get("status") in ["batting", "out", "not_out", "retired_hurt"]:
                        match_participating_ids.add(p_id)

                for p_id, bowl_data in inn.bowling_scores.items():
                    p_id = int(p_id)
                    if bowl_data.get("balls", 0) > 0:
                        match_participating_ids.add(p_id)

                for p_id, f_data in inn.fielding_scores.items():
                    p_id = int(p_id)
                    if (f_data.get("catches", 0) > 0 or f_data.get("stumpings", 0) > 0 or f_data.get("run_outs", 0) > 0):
                        match_participating_ids.add(p_id)

                for d in inn.deliveries:
                    if d.get("fielder_id"):
                        match_participating_ids.add(int(d["fielder_id"]))

            # Update global participation count and inactivity streak for ALL registered players
            for pid in players_dict:
                if pid in match_participating_ids:
                    total_participations[pid] += 1
                    inactivity_streak[pid] = 0
                else:
                    inactivity_streak[pid] += 1

            # Accumulate category MVP points and category participation
            # A) Batting: Only matches in which the player actually batted
            for pid in players_dict:
                p_stat = perf_by_id.get(pid)
                did_bat = False

                if p_stat and (p_stat.get("batting_balls", 0) > 0 or p_stat.get("batting_runs", 0) > 0):
                    did_bat = True
                else:
                    for inn in match_state.innings:
                        b_data = inn.batting_scores.get(pid) or inn.batting_scores.get(str(pid))
                        if b_data and (b_data.get("balls", 0) > 0 or b_data.get("runs", 0) > 0 or b_data.get("status") in ["batting", "out", "not_out", "retired_hurt"]):
                            did_bat = True
                            break

                if did_bat:
                    bat_pts = p_stat.get("batting_impact", 0) if p_stat else 0
                    batting_total_points[pid] += bat_pts
                    batting_matches_count[pid] += 1

            # B) Bowling: Only matches in which the player actually bowled
            for pid in players_dict:
                p_stat = perf_by_id.get(pid)
                did_bowl = False

                if p_stat and p_stat.get("bowling_balls", 0) > 0:
                    did_bowl = True
                else:
                    for inn in match_state.innings:
                        bowl_data = inn.bowling_scores.get(pid) or inn.bowling_scores.get(str(pid))
                        if bowl_data and bowl_data.get("balls", 0) > 0:
                            did_bowl = True
                            break

                if did_bowl:
                    bowl_pts = p_stat.get("bowling_impact", 0) if p_stat else 0
                    bowling_total_points[pid] += bowl_pts
                    bowling_matches_count[pid] += 1

            # C) Fielding: Matches in which the player participated in fielding (Playing XI counts)
            for pid in players_dict:
                if pid in match_participating_ids:
                    p_stat = perf_by_id.get(pid)
                    field_pts = p_stat.get("fielding_impact", 0) if p_stat else 0
                    fielding_total_points[pid] += field_pts
                    fielding_matches_count[pid] += 1

        # 4. Construct Rankings with Base Ratings, Inactivity Penalties, and 50% Rule
        batsmen_list = []
        bowlers_list = []
        fielders_list = []

        for pid, p_info in players_dict.items():
            participations = total_participations[pid]
            is_eligible = (participations >= min_participation)
            streak = inactivity_streak[pid]
            has_penalty = (streak >= 2)

            # 1. Batting Ranking
            if is_eligible and batting_matches_count[pid] > 0:
                b_matches = batting_matches_count[pid]
                b_pts = batting_total_points[pid]
                b_avg = b_pts / b_matches
                b_base_rating = b_avg * 10
                b_final_rating = b_base_rating * 0.95 if has_penalty else b_base_rating

                batsmen_list.append({
                    "player_id": pid,
                    "name": p_info["name"],
                    "avatar_url": p_info["avatar_url"],
                    "batting_style": p_info["batting_style"],
                    "team_name": p_info["team_name"],
                    "team_logo": p_info["team_logo"],
                    "matches_batted": b_matches,
                    "total_participations": participations,
                    "total_points": round(b_pts, 1),
                    "average_points": round(b_avg, 2),
                    "base_rating": round(b_base_rating, 1),
                    "rating": round(b_final_rating, 1),
                    "inactivity_streak": streak,
                    "has_penalty": has_penalty
                })

            # 2. Bowling Ranking
            if is_eligible and bowling_matches_count[pid] > 0:
                bw_matches = bowling_matches_count[pid]
                bw_pts = bowling_total_points[pid]
                bw_avg = bw_pts / bw_matches
                bw_base_rating = bw_avg * 10
                bw_final_rating = bw_base_rating * 0.95 if has_penalty else bw_base_rating

                bowlers_list.append({
                    "player_id": pid,
                    "name": p_info["name"],
                    "avatar_url": p_info["avatar_url"],
                    "bowling_style": p_info["bowling_style"],
                    "team_name": p_info["team_name"],
                    "team_logo": p_info["team_logo"],
                    "matches_bowled": bw_matches,
                    "total_participations": participations,
                    "total_points": round(bw_pts, 1),
                    "average_points": round(bw_avg, 2),
                    "base_rating": round(bw_base_rating, 1),
                    "rating": round(bw_final_rating, 1),
                    "inactivity_streak": streak,
                    "has_penalty": has_penalty
                })

            # 3. Fielding Ranking
            if is_eligible and fielding_matches_count[pid] > 0:
                f_matches = fielding_matches_count[pid]
                f_pts = fielding_total_points[pid]
                f_avg = f_pts / f_matches
                f_base_rating = f_avg * 10
                f_final_rating = f_base_rating * 0.95 if has_penalty else f_base_rating

                fielders_list.append({
                    "player_id": pid,
                    "name": p_info["name"],
                    "avatar_url": p_info["avatar_url"],
                    "is_keeper": p_info["is_keeper"],
                    "team_name": p_info["team_name"],
                    "team_logo": p_info["team_logo"],
                    "matches_fielded": f_matches,
                    "total_participations": participations,
                    "total_points": round(f_pts, 1),
                    "average_points": round(f_avg, 2),
                    "base_rating": round(f_base_rating, 1),
                    "rating": round(f_final_rating, 1),
                    "inactivity_streak": streak,
                    "has_penalty": has_penalty
                })

        # Sort each ranking from highest rating to lowest
        batsmen_list.sort(key=lambda x: (x["rating"], x["average_points"], x["total_points"], x["matches_batted"]), reverse=True)
        bowlers_list.sort(key=lambda x: (x["rating"], x["average_points"], x["total_points"], x["matches_bowled"]), reverse=True)
        fielders_list.sort(key=lambda x: (x["rating"], x["average_points"], x["total_points"], x["matches_fielded"]), reverse=True)

        for i, item in enumerate(batsmen_list, 1):
            item["rank"] = i
        for i, item in enumerate(bowlers_list, 1):
            item["rank"] = i
        for i, item in enumerate(fielders_list, 1):
            item["rank"] = i

        return {
            "total_completed_matches": total_completed,
            "min_participation": min_participation,
            "batsmen": batsmen_list,
            "bowlers": bowlers_list,
            "fielders": fielders_list
        }
    finally:
        if close_conn:
            conn.close()


def get_player_career_ranking_summary(player_id: int, rankings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Returns the career ranking position, ratings, and stats for a specific player across all 3 categories.
    """
    if rankings is None:
        rankings = calculate_player_rankings()

    bat_entry = next((b for b in rankings["batsmen"] if b["player_id"] == player_id), None)
    bowl_entry = next((bw for bw in rankings["bowlers"] if bw["player_id"] == player_id), None)
    field_entry = next((f for f in rankings["fielders"] if f["player_id"] == player_id), None)

    return {
        "batting": bat_entry,
        "bowling": bowl_entry,
        "fielding": field_entry,
        "total_completed_matches": rankings["total_completed_matches"],
        "min_participation": rankings["min_participation"]
    }
