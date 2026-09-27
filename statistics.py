# statistics.py
"""
On-Demand Advanced Statistics Service for CricScorer.

CRITICAL PERFORMANCE GUARANTEES:
- These statistics are NEVER calculated automatically during ball-scoring,
  live match updates, SSE streams, or live viewer refreshes.
- Each statistic is calculated strictly ON-DEMAND when an administrator requests it.
- Calculations run only against completed matches (m.status = 'completed').
- Results are cached in `admin_statistics_cache` and invalidated (marked OUTDATED)
  when new completed matches are added.
"""

import json
import math
from datetime import datetime
from typing import Dict, List, Any, Optional
import database
from database import get_db_connection


# --- METADATA REGISTRY ---

STATISTICS_REGISTRY = {
    "most_runs": {
        "key": "most_runs",
        "title": "Most Runs",
        "category": "Batting",
        "icon": "fa-solid fa-baseball-bat-ball",
        "color": "#10b981",
        "description": "Total career runs scored across all completed matches.",
        "has_params": False,
        "default_params": {},
        "columns": ["Rank", "Player", "Runs", "Matches", "Innings", "Balls", "4s", "6s", "Strike Rate"]
    },
    "most_wickets": {
        "key": "most_wickets",
        "title": "Most Wickets",
        "category": "Bowling",
        "icon": "fa-solid fa-bowling-ball",
        "color": "#6366f1",
        "description": "Total career wickets taken across all completed matches.",
        "has_params": False,
        "default_params": {},
        "columns": ["Rank", "Player", "Wickets", "Matches", "Overs", "Runs Conceded", "Economy", "BBI"]
    },
    "best_strike_rate": {
        "key": "best_strike_rate",
        "title": "Best Strike Rate",
        "category": "Batting",
        "icon": "fa-solid fa-bolt",
        "color": "#fbbf24",
        "description": "Highest career batting strike rate with configurable minimum balls faced.",
        "has_params": True,
        "param_name": "min_balls",
        "param_label": "Minimum Balls",
        "param_type": "int",
        "default_params": {"min_balls": 20},
        "preset_options": [10, 20, 50, 100],
        "columns": ["Rank", "Player", "Strike Rate", "Runs", "Balls", "4s", "6s"]
    },
    "best_average": {
        "key": "best_average",
        "title": "Best Batting Average",
        "category": "Batting",
        "icon": "fa-solid fa-chart-line",
        "color": "#38bdf8",
        "description": "Highest batting average (Runs / Dismissals) with configurable minimum matches.",
        "has_params": True,
        "param_name": "min_matches",
        "param_label": "Minimum Matches",
        "param_type": "int",
        "default_params": {"min_matches": 2},
        "preset_options": [1, 2, 3, 5, 10],
        "columns": ["Rank", "Player", "Average", "Runs", "Innings", "Not Outs", "Matches"]
    },
    "best_economy": {
        "key": "best_economy",
        "title": "Best Economy",
        "category": "Bowling",
        "icon": "fa-solid fa-gauge-high",
        "color": "#ec4899",
        "description": "Lowest bowling economy rate (Runs / Overs) with configurable minimum overs.",
        "has_params": True,
        "param_name": "min_overs",
        "param_label": "Minimum Overs",
        "param_type": "float",
        "default_params": {"min_overs": 5.0},
        "preset_options": [1, 2, 5, 10, 20],
        "columns": ["Rank", "Player", "Economy", "Overs", "Runs Conceded", "Wickets"]
    },
    "most_catches": {
        "key": "most_catches",
        "title": "Most Catches",
        "category": "Fielding",
        "icon": "fa-solid fa-hands",
        "color": "#14b8a6",
        "description": "Total catches taken by fielders and wicketkeepers in completed matches.",
        "has_params": False,
        "default_params": {},
        "columns": ["Rank", "Player", "Catches", "Matches", "Stumpings", "Run-Outs", "Total Dismissals"]
    },
    "most_runouts": {
        "key": "most_runouts",
        "title": "Most Run-Outs",
        "category": "Fielding",
        "icon": "fa-solid fa-person-running",
        "color": "#f97316",
        "description": "Total run-outs credited to the fielder across completed matches.",
        "has_params": False,
        "default_params": {},
        "columns": ["Rank", "Player", "Run-Outs", "Matches"]
    },
    "most_boundaries": {
        "key": "most_boundaries",
        "title": "Most Boundaries (4s + 6s)",
        "category": "Batting",
        "icon": "fa-solid fa-burst",
        "color": "#a855f7",
        "description": "Total career boundary count (combined 4s and 6s) in completed matches.",
        "has_params": False,
        "default_params": {},
        "columns": ["Rank", "Player", "Total Boundaries", "4s", "6s", "Total Runs"]
    },
    "most_sixes": {
        "key": "most_sixes",
        "title": "Most Sixes",
        "category": "Batting",
        "icon": "fa-solid fa-6",
        "color": "#f43f5e",
        "description": "Total sixes hit across all completed matches.",
        "has_params": False,
        "default_params": {},
        "columns": ["Rank", "Player", "Sixes", "Runs", "Matches", "Innings"]
    },
    "most_fours": {
        "key": "most_fours",
        "title": "Most Fours",
        "category": "Batting",
        "icon": "fa-solid fa-4",
        "color": "#0ea5e9",
        "description": "Total fours hit across all completed matches.",
        "has_params": False,
        "default_params": {},
        "columns": ["Rank", "Player", "Fours", "Runs", "Matches", "Innings"]
    },
    "best_spell": {
        "key": "best_spell",
        "title": "Best Bowling Spell",
        "category": "Bowling",
        "icon": "fa-solid fa-bullseye",
        "color": "#8b5cf6",
        "description": "Best individual bowling performance in a single innings of a completed match.",
        "has_params": False,
        "default_params": {},
        "columns": ["Rank", "Player", "Figures", "Overs", "Runs", "Wickets", "Economy", "Match", "Date", "Opponent"]
    },
    "best_innings": {
        "key": "best_innings",
        "title": "Best Batting Innings",
        "category": "Batting",
        "icon": "fa-solid fa-trophy",
        "color": "#eab308",
        "description": "Highest individual score in a single innings of a completed match.",
        "has_params": False,
        "default_params": {},
        "columns": ["Rank", "Player", "Runs", "Balls", "4s", "6s", "Strike Rate", "Status", "Match", "Date", "Opponent"]
    }
}


# --- HELPER / CACHE FUNCTIONS ---

def get_completed_matches_count(conn=None) -> int:
    """Return total number of completed matches in the database."""
    close = False
    if conn is None:
        conn = get_db_connection()
        close = True
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM matches WHERE status = 'completed'")
        row = cursor.fetchone()
        return row[0] if row else 0
    finally:
        if close:
            conn.close()


def normalize_params(params: Optional[dict]) -> dict:
    """Normalize parameters dictionary for stable JSON serialization."""
    if not params:
        return {}
    normalized = {}
    for k, v in params.items():
        if isinstance(v, float) and v.is_integer():
            normalized[k] = int(v)
        else:
            normalized[k] = v
    return normalized


def get_cached_statistic(stat_key: str, params: Optional[dict] = None, conn=None) -> Optional[Dict[str, Any]]:
    """Fetch cached result for a given statistic key and params."""
    close = False
    if conn is None:
        conn = get_db_connection()
        close = True
    try:
        norm_params = normalize_params(params)
        params_json = json.dumps(norm_params, sort_keys=True)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT stat_key, params_json, result_json, completed_matches_count, calculated_at
            FROM admin_statistics_cache
            WHERE stat_key = ? AND params_json = ?
        """, (stat_key, params_json))
        row = cursor.fetchone()
        if not row:
            # Fallback: if params were omitted/empty, check if any recent calculation exists for stat_key
            if not norm_params:
                cursor.execute("""
                    SELECT stat_key, params_json, result_json, completed_matches_count, calculated_at
                    FROM admin_statistics_cache
                    WHERE stat_key = ?
                    ORDER BY calculated_at DESC LIMIT 1
                """, (stat_key,))
                row = cursor.fetchone()

        if row:
            result_data = json.loads(row['result_json']) if isinstance(row['result_json'], str) else row['result_json']
            p_data = json.loads(row['params_json']) if isinstance(row['params_json'], str) else row['params_json']
            calc_at = row['calculated_at']
            if isinstance(calc_at, datetime):
                calc_str = calc_at.strftime('%Y-%m-%d %H:%M')
            else:
                calc_str = str(calc_at)[:16] if calc_at else 'Unknown'

            return {
                "stat_key": row['stat_key'],
                "params": p_data,
                "result": result_data,
                "completed_matches_count": row['completed_matches_count'],
                "calculated_at": calc_str
            }
        return None
    except Exception as e:
        print(f"Error fetching cached statistic '{stat_key}': {e}")
        return None
    finally:
        if close:
            conn.close()


def save_cached_statistic(stat_key: str, params: dict, result: list, completed_matches_count: int, conn=None):
    """Save or update statistic calculation result in cache."""
    close = False
    if conn is None:
        conn = get_db_connection()
        close = True
    try:
        norm_params = normalize_params(params)
        params_json = json.dumps(norm_params, sort_keys=True)
        result_json = json.dumps(result)
        cursor = conn.cursor()

        # Check existing row
        cursor.execute("""
            SELECT id FROM admin_statistics_cache
            WHERE stat_key = ? AND params_json = ?
        """, (stat_key, params_json))
        existing = cursor.fetchone()

        if existing:
            cursor.execute("""
                UPDATE admin_statistics_cache
                SET result_json = ?, completed_matches_count = ?, calculated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (result_json, completed_matches_count, existing['id']))
        else:
            cursor.execute("""
                INSERT INTO admin_statistics_cache (stat_key, params_json, result_json, completed_matches_count, calculated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (stat_key, params_json, result_json, completed_matches_count))

        conn.commit()
    except Exception as e:
        print(f"Error saving cached statistic '{stat_key}': {e}")
    finally:
        if close:
            conn.close()


def get_all_statistics_overview(conn=None) -> List[Dict[str, Any]]:
    """Return overview metadata and cache freshness status for all 12 statistics."""
    close = False
    if conn is None:
        conn = get_db_connection()
        close = True
    try:
        current_completed_count = get_completed_matches_count(conn)
        cursor = conn.cursor()

        # Fetch latest cache entry for all statistics
        cursor.execute("""
            SELECT stat_key, params_json, completed_matches_count, calculated_at,
                   LENGTH(result_json) as data_len
            FROM admin_statistics_cache
            ORDER BY calculated_at DESC
        """)
        cache_rows = cursor.fetchall()
        cache_by_key = {}
        for r in cache_rows:
            k = r['stat_key']
            if k not in cache_by_key:
                cache_by_key[k] = r

        overview = []
        for key, meta in STATISTICS_REGISTRY.items():
            entry = dict(meta)
            cached = cache_by_key.get(key)
            if cached:
                matches_inc = cached['completed_matches_count']
                calc_at = cached['calculated_at']
                if isinstance(calc_at, datetime):
                    calc_str = calc_at.strftime('%d %b %Y %H:%M')
                else:
                    calc_str = str(calc_at)[:16] if calc_at else 'Unknown'

                is_outdated = (matches_inc < current_completed_count)
                status = "outdated" if is_outdated else "fresh"
                status_label = "OUTDATED" if is_outdated else "UP TO DATE"
                
                try:
                    p_parsed = json.loads(cached['params_json'])
                except Exception:
                    p_parsed = {}

                entry.update({
                    "is_calculated": True,
                    "status": status,
                    "status_label": status_label,
                    "last_calculated": calc_str,
                    "matches_included": matches_inc,
                    "current_completed_count": current_completed_count,
                    "last_params": p_parsed
                })
            else:
                entry.update({
                    "is_calculated": False,
                    "status": "never",
                    "status_label": "NOT CALCULATED",
                    "last_calculated": "Never",
                    "matches_included": 0,
                    "current_completed_count": current_completed_count,
                    "last_params": entry.get("default_params", {})
                })
            overview.append(entry)

        return overview
    finally:
        if close:
            conn.close()


# --- ON-DEMAND CALCULATOR IMPLEMENTATIONS ---

def calculate_most_runs(conn=None) -> List[Dict[str, Any]]:
    """Calculate career Most Runs across completed matches only."""
    close = False
    if conn is None:
        conn = get_db_connection()
        close = True
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                p.id as player_id,
                p.name as player_name,
                p.avatar_url,
                COALESCE(SUM(d.runs_batter), 0) as runs,
                COALESCE(SUM(CASE WHEN d.runs_batter = 4 THEN 1 ELSE 0 END), 0) as fours,
                COALESCE(SUM(CASE WHEN d.runs_batter = 6 THEN 1 ELSE 0 END), 0) as sixes,
                COALESCE(COUNT(CASE WHEN d.extra_type != 'wide' OR d.extra_type IS NULL THEN 1 END), 0) as balls,
                COUNT(DISTINCT i.id) as innings,
                COUNT(DISTINCT m.id) as matches
            FROM players p
            JOIN deliveries d ON d.striker_id = p.id
            JOIN innings i ON d.innings_id = i.id
            JOIN matches m ON i.match_id = m.id
            WHERE m.status = 'completed'
            GROUP BY p.id, p.name, p.avatar_url
            HAVING SUM(d.runs_batter) > 0 OR COUNT(d.id) > 0
            ORDER BY runs DESC, fours DESC, sixes DESC
        """)
        rows = cursor.fetchall()
        results = []
        for idx, r in enumerate(rows):
            runs = int(r['runs'])
            balls = int(r['balls'])
            sr = round((runs * 100.0) / balls, 2) if balls > 0 else 0.0
            results.append({
                "rank": idx + 1,
                "player_id": r['player_id'],
                "player_name": r['player_name'],
                "avatar_url": r['avatar_url'] or f"https://api.dicebear.com/7.x/bottts/svg?seed={r['player_name'].replace(' ', '')}",
                "runs": runs,
                "matches": int(r['matches']),
                "innings": int(r['innings']),
                "balls": balls,
                "fours": int(r['fours']),
                "sixes": int(r['sixes']),
                "strike_rate": sr
            })
        return results
    finally:
        if close:
            conn.close()


def calculate_most_wickets(conn=None) -> List[Dict[str, Any]]:
    """Calculate career Most Wickets across completed matches only."""
    close = False
    if conn is None:
        conn = get_db_connection()
        close = True
    try:
        cursor = conn.cursor()
        # Aggregate bowling figures
        cursor.execute("""
            SELECT 
                p.id as player_id,
                p.name as player_name,
                p.avatar_url,
                COALESCE(SUM(CASE WHEN d.is_bowler_wicket = 1 THEN 1 ELSE 0 END), 0) as wickets,
                COALESCE(COUNT(CASE WHEN d.is_legal = 1 THEN 1 END), 0) as legal_balls,
                COALESCE(SUM(d.runs_batter + (CASE WHEN d.extra_type IN ('wide', 'noball') THEN d.runs_extras ELSE 0 END)), 0) as runs_conceded,
                COUNT(DISTINCT m.id) as matches
            FROM players p
            JOIN deliveries d ON d.bowler_id = p.id
            JOIN innings i ON d.innings_id = i.id
            JOIN matches m ON i.match_id = m.id
            WHERE m.status = 'completed'
            GROUP BY p.id, p.name, p.avatar_url
            HAVING SUM(CASE WHEN d.is_bowler_wicket = 1 THEN 1 ELSE 0 END) > 0 OR COUNT(CASE WHEN d.is_legal = 1 THEN 1 END) > 0
            ORDER BY wickets DESC, runs_conceded ASC
        """)
        bowler_rows = cursor.fetchall()

        # Calculate Best Bowling Innings (BBI) per bowler
        cursor.execute("""
            SELECT 
                d.bowler_id,
                i.id as innings_id,
                COALESCE(SUM(CASE WHEN d.is_bowler_wicket = 1 THEN 1 ELSE 0 END), 0) as wkts,
                COALESCE(SUM(d.runs_batter + (CASE WHEN d.extra_type IN ('wide', 'noball') THEN d.runs_extras ELSE 0 END)), 0) as rc
            FROM deliveries d
            JOIN innings i ON d.innings_id = i.id
            JOIN matches m ON i.match_id = m.id
            WHERE m.status = 'completed'
            GROUP BY d.bowler_id, i.id
            ORDER BY wkts DESC, rc ASC
        """)
        bbi_rows = cursor.fetchall()
        bbi_map = {}
        for b in bbi_rows:
            bid = b['bowler_id']
            if bid not in bbi_map:
                bbi_map[bid] = f"{b['wkts']}/{b['rc']}"

        results = []
        for idx, r in enumerate(bowler_rows):
            wkts = int(r['wickets'])
            balls = int(r['legal_balls'])
            rc = int(r['runs_conceded'])
            overs_str = f"{balls // 6}.{balls % 6}"
            econ = round((rc * 6.0) / balls, 2) if balls > 0 else 0.0
            bbi = bbi_map.get(r['player_id'], "-")

            results.append({
                "rank": idx + 1,
                "player_id": r['player_id'],
                "player_name": r['player_name'],
                "avatar_url": r['avatar_url'] or f"https://api.dicebear.com/7.x/bottts/svg?seed={r['player_name'].replace(' ', '')}",
                "wickets": wkts,
                "matches": int(r['matches']),
                "overs": overs_str,
                "runs_conceded": rc,
                "economy": econ,
                "bbi": bbi
            })
        return results
    finally:
        if close:
            conn.close()


def calculate_best_strike_rate(min_balls: int = 20, conn=None) -> List[Dict[str, Any]]:
    """Calculate Best Batting Strike Rate with configurable minimum balls threshold."""
    close = False
    if conn is None:
        conn = get_db_connection()
        close = True
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                p.id as player_id,
                p.name as player_name,
                p.avatar_url,
                COALESCE(SUM(d.runs_batter), 0) as runs,
                COALESCE(COUNT(CASE WHEN d.extra_type != 'wide' OR d.extra_type IS NULL THEN 1 END), 0) as balls,
                COALESCE(SUM(CASE WHEN d.runs_batter = 4 THEN 1 ELSE 0 END), 0) as fours,
                COALESCE(SUM(CASE WHEN d.runs_batter = 6 THEN 1 ELSE 0 END), 0) as sixes
            FROM players p
            JOIN deliveries d ON d.striker_id = p.id
            JOIN innings i ON d.innings_id = i.id
            JOIN matches m ON i.match_id = m.id
            WHERE m.status = 'completed'
            GROUP BY p.id, p.name, p.avatar_url
            HAVING COUNT(CASE WHEN d.extra_type != 'wide' OR d.extra_type IS NULL THEN 1 END) >= ?
        """, (int(min_balls),))
        rows = cursor.fetchall()
        
        parsed = []
        for r in rows:
            runs = int(r['runs'])
            balls = int(r['balls'])
            sr = round((runs * 100.0) / balls, 2) if balls > 0 else 0.0
            parsed.append({
                "player_id": r['player_id'],
                "player_name": r['player_name'],
                "avatar_url": r['avatar_url'] or f"https://api.dicebear.com/7.x/bottts/svg?seed={r['player_name'].replace(' ', '')}",
                "runs": runs,
                "balls": balls,
                "fours": int(r['fours']),
                "sixes": int(r['sixes']),
                "strike_rate": sr
            })
        
        parsed.sort(key=lambda x: (x["strike_rate"], x["runs"]), reverse=True)
        for idx, item in enumerate(parsed):
            item["rank"] = idx + 1
        return parsed
    finally:
        if close:
            conn.close()


def calculate_best_average(min_matches: int = 2, conn=None) -> List[Dict[str, Any]]:
    """Calculate Best Batting Average (Runs / Dismissals) with configurable minimum matches."""
    close = False
    if conn is None:
        conn = get_db_connection()
        close = True
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                p.id as player_id,
                p.name as player_name,
                p.avatar_url,
                COALESCE(SUM(d.runs_batter), 0) as runs,
                COUNT(DISTINCT i.id) as innings,
                COUNT(DISTINCT m.id) as matches,
                COALESCE(COUNT(CASE WHEN d.is_wicket = 1 AND d.player_dismissed_id = p.id THEN 1 END), 0) as dismissals
            FROM players p
            JOIN deliveries d ON d.striker_id = p.id
            JOIN innings i ON d.innings_id = i.id
            JOIN matches m ON i.match_id = m.id
            WHERE m.status = 'completed'
            GROUP BY p.id, p.name, p.avatar_url
            HAVING COUNT(DISTINCT m.id) >= ?
        """, (int(min_matches),))
        rows = cursor.fetchall()

        parsed = []
        for r in rows:
            runs = int(r['runs'])
            dismissals = int(r['dismissals'])
            innings = int(r['innings'])
            not_outs = max(0, innings - dismissals)
            
            # Standard cricket average calculation
            if dismissals > 0:
                avg = round(runs / dismissals, 2)
            else:
                avg = float(runs)  # undefeated average

            parsed.append({
                "player_id": r['player_id'],
                "player_name": r['player_name'],
                "avatar_url": r['avatar_url'] or f"https://api.dicebear.com/7.x/bottts/svg?seed={r['player_name'].replace(' ', '')}",
                "average": avg,
                "runs": runs,
                "innings": innings,
                "dismissals": dismissals,
                "not_outs": not_outs,
                "matches": int(r['matches'])
            })

        parsed.sort(key=lambda x: (x["average"], x["runs"]), reverse=True)
        for idx, item in enumerate(parsed):
            item["rank"] = idx + 1
        return parsed
    finally:
        if close:
            conn.close()


def calculate_best_economy(min_overs: float = 5.0, conn=None) -> List[Dict[str, Any]]:
    """Calculate Best Bowling Economy Rate with configurable minimum overs threshold."""
    close = False
    if conn is None:
        conn = get_db_connection()
        close = True
    try:
        min_balls = int(float(min_overs) * 6)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                p.id as player_id,
                p.name as player_name,
                p.avatar_url,
                COALESCE(COUNT(CASE WHEN d.is_legal = 1 THEN 1 END), 0) as legal_balls,
                COALESCE(SUM(d.runs_batter + (CASE WHEN d.extra_type IN ('wide', 'noball') THEN d.runs_extras ELSE 0 END)), 0) as runs_conceded,
                COALESCE(SUM(CASE WHEN d.is_bowler_wicket = 1 THEN 1 ELSE 0 END), 0) as wickets,
                COUNT(DISTINCT m.id) as matches
            FROM players p
            JOIN deliveries d ON d.bowler_id = p.id
            JOIN innings i ON d.innings_id = i.id
            JOIN matches m ON i.match_id = m.id
            WHERE m.status = 'completed'
            GROUP BY p.id, p.name, p.avatar_url
            HAVING COUNT(CASE WHEN d.is_legal = 1 THEN 1 END) >= ?
        """, (min_balls,))
        rows = cursor.fetchall()

        parsed = []
        for r in rows:
            balls = int(r['legal_balls'])
            rc = int(r['runs_conceded'])
            wkts = int(r['wickets'])
            econ = round((rc * 6.0) / balls, 2) if balls > 0 else 0.0
            overs_str = f"{balls // 6}.{balls % 6}"

            parsed.append({
                "player_id": r['player_id'],
                "player_name": r['player_name'],
                "avatar_url": r['avatar_url'] or f"https://api.dicebear.com/7.x/bottts/svg?seed={r['player_name'].replace(' ', '')}",
                "economy": econ,
                "overs": overs_str,
                "runs_conceded": rc,
                "wickets": wkts,
                "legal_balls": balls,
                "matches": int(r['matches'])
            })

        parsed.sort(key=lambda x: (x["economy"], -x["wickets"], x["runs_conceded"]))
        for idx, item in enumerate(parsed):
            item["rank"] = idx + 1
        return parsed
    finally:
        if close:
            conn.close()


def calculate_most_catches(conn=None) -> List[Dict[str, Any]]:
    """Calculate Most Catches across completed matches."""
    close = False
    if conn is None:
        conn = get_db_connection()
        close = True
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                p.id as player_id,
                p.name as player_name,
                p.avatar_url,
                COALESCE(SUM(CASE WHEN d.is_wicket = 1 AND d.wicket_type = 'caught' AND d.fielder_id = p.id THEN 1 ELSE 0 END), 0) as catches,
                COALESCE(SUM(CASE WHEN d.is_wicket = 1 AND d.wicket_type = 'stumped' AND d.fielder_id = p.id THEN 1 ELSE 0 END), 0) as stumpings,
                COALESCE(SUM(CASE WHEN d.is_wicket = 1 AND d.wicket_type = 'run_out' AND d.fielder_id = p.id THEN 1 ELSE 0 END), 0) as run_outs,
                COUNT(DISTINCT m.id) as matches
            FROM players p
            JOIN deliveries d ON d.fielder_id = p.id
            JOIN innings i ON d.innings_id = i.id
            JOIN matches m ON i.match_id = m.id
            WHERE m.status = 'completed' AND d.is_wicket = 1
            GROUP BY p.id, p.name, p.avatar_url
            HAVING SUM(CASE WHEN d.is_wicket = 1 AND d.wicket_type = 'caught' AND d.fielder_id = p.id THEN 1 ELSE 0 END) > 0
               OR SUM(CASE WHEN d.is_wicket = 1 AND d.wicket_type = 'stumped' AND d.fielder_id = p.id THEN 1 ELSE 0 END) > 0
               OR SUM(CASE WHEN d.is_wicket = 1 AND d.wicket_type = 'run_out' AND d.fielder_id = p.id THEN 1 ELSE 0 END) > 0
            ORDER BY catches DESC, stumpings DESC, run_outs DESC
        """)
        rows = cursor.fetchall()
        results = []
        for idx, r in enumerate(rows):
            catches = int(r['catches'])
            stumpings = int(r['stumpings'])
            run_outs = int(r['run_outs'])
            results.append({
                "rank": idx + 1,
                "player_id": r['player_id'],
                "player_name": r['player_name'],
                "avatar_url": r['avatar_url'] or f"https://api.dicebear.com/7.x/bottts/svg?seed={r['player_name'].replace(' ', '')}",
                "catches": catches,
                "stumpings": stumpings,
                "run_outs": run_outs,
                "total_dismissals": catches + stumpings + run_outs,
                "matches": int(r['matches'])
            })
        return results
    finally:
        if close:
            conn.close()


def calculate_most_runouts(conn=None) -> List[Dict[str, Any]]:
    """Calculate Most Run-Outs credited to fielders across completed matches."""
    close = False
    if conn is None:
        conn = get_db_connection()
        close = True
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                p.id as player_id,
                p.name as player_name,
                p.avatar_url,
                COALESCE(COUNT(d.id), 0) as run_outs,
                COUNT(DISTINCT m.id) as matches
            FROM players p
            JOIN deliveries d ON d.fielder_id = p.id
            JOIN innings i ON d.innings_id = i.id
            JOIN matches m ON i.match_id = m.id
            WHERE m.status = 'completed' AND d.is_wicket = 1 AND d.wicket_type = 'run_out'
            GROUP BY p.id, p.name, p.avatar_url
            HAVING COUNT(d.id) > 0
            ORDER BY run_outs DESC, matches ASC
        """)
        rows = cursor.fetchall()
        results = []
        for idx, r in enumerate(rows):
            results.append({
                "rank": idx + 1,
                "player_id": r['player_id'],
                "player_name": r['player_name'],
                "avatar_url": r['avatar_url'] or f"https://api.dicebear.com/7.x/bottts/svg?seed={r['player_name'].replace(' ', '')}",
                "run_outs": int(r['run_outs']),
                "matches": int(r['matches'])
            })
        return results
    finally:
        if close:
            conn.close()


def calculate_most_boundaries(conn=None) -> List[Dict[str, Any]]:
    """Calculate Most Boundaries (4s + 6s) across completed matches."""
    close = False
    if conn is None:
        conn = get_db_connection()
        close = True
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                p.id as player_id,
                p.name as player_name,
                p.avatar_url,
                COALESCE(SUM(CASE WHEN d.runs_batter = 4 THEN 1 ELSE 0 END), 0) as fours,
                COALESCE(SUM(CASE WHEN d.runs_batter = 6 THEN 1 ELSE 0 END), 0) as sixes,
                COALESCE(SUM(d.runs_batter), 0) as runs
            FROM players p
            JOIN deliveries d ON d.striker_id = p.id
            JOIN innings i ON d.innings_id = i.id
            JOIN matches m ON i.match_id = m.id
            WHERE m.status = 'completed'
            GROUP BY p.id, p.name, p.avatar_url
            HAVING SUM(CASE WHEN d.runs_batter IN (4, 6) THEN 1 ELSE 0 END) > 0
            ORDER BY (SUM(CASE WHEN d.runs_batter = 4 THEN 1 ELSE 0 END) + SUM(CASE WHEN d.runs_batter = 6 THEN 1 ELSE 0 END)) DESC, fours DESC, runs DESC
        """)
        rows = cursor.fetchall()
        results = []
        for idx, r in enumerate(rows):
            fours = int(r['fours'])
            sixes = int(r['sixes'])
            results.append({
                "rank": idx + 1,
                "player_id": r['player_id'],
                "player_name": r['player_name'],
                "avatar_url": r['avatar_url'] or f"https://api.dicebear.com/7.x/bottts/svg?seed={r['player_name'].replace(' ', '')}",
                "total_boundaries": fours + sixes,
                "fours": fours,
                "sixes": sixes,
                "runs": int(r['runs'])
            })
        return results
    finally:
        if close:
            conn.close()


def calculate_most_sixes(conn=None) -> List[Dict[str, Any]]:
    """Calculate Most Sixes across completed matches."""
    close = False
    if conn is None:
        conn = get_db_connection()
        close = True
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                p.id as player_id,
                p.name as player_name,
                p.avatar_url,
                COALESCE(SUM(CASE WHEN d.runs_batter = 6 THEN 1 ELSE 0 END), 0) as sixes,
                COALESCE(SUM(d.runs_batter), 0) as runs,
                COUNT(DISTINCT m.id) as matches,
                COUNT(DISTINCT i.id) as innings
            FROM players p
            JOIN deliveries d ON d.striker_id = p.id
            JOIN innings i ON d.innings_id = i.id
            JOIN matches m ON i.match_id = m.id
            WHERE m.status = 'completed'
            GROUP BY p.id, p.name, p.avatar_url
            HAVING SUM(CASE WHEN d.runs_batter = 6 THEN 1 ELSE 0 END) > 0
            ORDER BY sixes DESC, runs DESC
        """)
        rows = cursor.fetchall()
        results = []
        for idx, r in enumerate(rows):
            results.append({
                "rank": idx + 1,
                "player_id": r['player_id'],
                "player_name": r['player_name'],
                "avatar_url": r['avatar_url'] or f"https://api.dicebear.com/7.x/bottts/svg?seed={r['player_name'].replace(' ', '')}",
                "sixes": int(r['sixes']),
                "runs": int(r['runs']),
                "matches": int(r['matches']),
                "innings": int(r['innings'])
            })
        return results
    finally:
        if close:
            conn.close()


def calculate_most_fours(conn=None) -> List[Dict[str, Any]]:
    """Calculate Most Fours across completed matches."""
    close = False
    if conn is None:
        conn = get_db_connection()
        close = True
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                p.id as player_id,
                p.name as player_name,
                p.avatar_url,
                COALESCE(SUM(CASE WHEN d.runs_batter = 4 THEN 1 ELSE 0 END), 0) as fours,
                COALESCE(SUM(d.runs_batter), 0) as runs,
                COUNT(DISTINCT m.id) as matches,
                COUNT(DISTINCT i.id) as innings
            FROM players p
            JOIN deliveries d ON d.striker_id = p.id
            JOIN innings i ON d.innings_id = i.id
            JOIN matches m ON i.match_id = m.id
            WHERE m.status = 'completed'
            GROUP BY p.id, p.name, p.avatar_url
            HAVING SUM(CASE WHEN d.runs_batter = 4 THEN 1 ELSE 0 END) > 0
            ORDER BY fours DESC, runs DESC
        """)
        rows = cursor.fetchall()
        results = []
        for idx, r in enumerate(rows):
            results.append({
                "rank": idx + 1,
                "player_id": r['player_id'],
                "player_name": r['player_name'],
                "avatar_url": r['avatar_url'] or f"https://api.dicebear.com/7.x/bottts/svg?seed={r['player_name'].replace(' ', '')}",
                "fours": int(r['fours']),
                "runs": int(r['runs']),
                "matches": int(r['matches']),
                "innings": int(r['innings'])
            })
        return results
    finally:
        if close:
            conn.close()


def calculate_best_spell(conn=None) -> List[Dict[str, Any]]:
    """Calculate Best Bowling Spell in a single innings across completed matches."""
    close = False
    if conn is None:
        conn = get_db_connection()
        close = True
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                p.id as player_id,
                p.name as player_name,
                p.avatar_url,
                m.id as match_id,
                m.match_date,
                m.ground,
                t_opp.name as opponent_name,
                COALESCE(SUM(CASE WHEN d.is_bowler_wicket = 1 THEN 1 ELSE 0 END), 0) as wickets,
                COALESCE(COUNT(CASE WHEN d.is_legal = 1 THEN 1 END), 0) as legal_balls,
                COALESCE(SUM(d.runs_batter + (CASE WHEN d.extra_type IN ('wide', 'noball') THEN d.runs_extras ELSE 0 END)), 0) as runs_conceded
            FROM deliveries d
            JOIN players p ON d.bowler_id = p.id
            JOIN innings i ON d.innings_id = i.id
            JOIN matches m ON i.match_id = m.id
            JOIN teams t_opp ON i.batting_team_id = t_opp.id
            WHERE m.status = 'completed'
            GROUP BY p.id, p.name, p.avatar_url, m.id, m.match_date, m.ground, t_opp.name, i.id
            HAVING SUM(CASE WHEN d.is_bowler_wicket = 1 THEN 1 ELSE 0 END) > 0 OR COUNT(CASE WHEN d.is_legal = 1 THEN 1 END) >= 6
            ORDER BY wickets DESC, runs_conceded ASC, legal_balls DESC
            LIMIT 50
        """)
        rows = cursor.fetchall()
        results = []
        for idx, r in enumerate(rows):
            wkts = int(r['wickets'])
            rc = int(r['runs_conceded'])
            balls = int(r['legal_balls'])
            econ = round((rc * 6.0) / balls, 2) if balls > 0 else 0.0
            overs_str = f"{balls // 6}.{balls % 6}"

            results.append({
                "rank": idx + 1,
                "player_id": r['player_id'],
                "player_name": r['player_name'],
                "avatar_url": r['avatar_url'] or f"https://api.dicebear.com/7.x/bottts/svg?seed={r['player_name'].replace(' ', '')}",
                "figures": f"{wkts}/{rc}",
                "overs": overs_str,
                "runs": rc,
                "wickets": wkts,
                "economy": econ,
                "match_id": r['match_id'],
                "match_date": r['match_date'] or "-",
                "ground": r['ground'] or "-",
                "opponent": r['opponent_name'] or "-"
            })
        return results
    finally:
        if close:
            conn.close()


def calculate_best_innings(conn=None) -> List[Dict[str, Any]]:
    """Calculate Highest Individual Batting Innings score across completed matches."""
    close = False
    if conn is None:
        conn = get_db_connection()
        close = True
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                p.id as player_id,
                p.name as player_name,
                p.avatar_url,
                m.id as match_id,
                m.match_date,
                m.ground,
                t_opp.name as opponent_name,
                i.id as innings_id,
                COALESCE(SUM(d.runs_batter), 0) as runs,
                COALESCE(COUNT(CASE WHEN d.extra_type != 'wide' OR d.extra_type IS NULL THEN 1 END), 0) as balls,
                COALESCE(SUM(CASE WHEN d.runs_batter = 4 THEN 1 ELSE 0 END), 0) as fours,
                COALESCE(SUM(CASE WHEN d.runs_batter = 6 THEN 1 ELSE 0 END), 0) as sixes,
                COALESCE(COUNT(CASE WHEN d.is_wicket = 1 AND d.player_dismissed_id = p.id THEN 1 END), 0) as dismissed
            FROM deliveries d
            JOIN players p ON d.striker_id = p.id
            JOIN innings i ON d.innings_id = i.id
            JOIN matches m ON i.match_id = m.id
            JOIN teams t_opp ON i.bowling_team_id = t_opp.id
            WHERE m.status = 'completed'
            GROUP BY p.id, p.name, p.avatar_url, m.id, m.match_date, m.ground, t_opp.name, i.id
            HAVING SUM(d.runs_batter) > 0 OR COUNT(d.id) > 0
            ORDER BY runs DESC, balls ASC, sixes DESC, fours DESC
            LIMIT 50
        """)
        rows = cursor.fetchall()
        results = []
        for idx, r in enumerate(rows):
            runs = int(r['runs'])
            balls = int(r['balls'])
            sr = round((runs * 100.0) / balls, 2) if balls > 0 else 0.0
            is_out = int(r['dismissed']) > 0

            results.append({
                "rank": idx + 1,
                "player_id": r['player_id'],
                "player_name": r['player_name'],
                "avatar_url": r['avatar_url'] or f"https://api.dicebear.com/7.x/bottts/svg?seed={r['player_name'].replace(' ', '')}",
                "runs": runs,
                "balls": balls,
                "fours": int(r['fours']),
                "sixes": int(r['sixes']),
                "strike_rate": sr,
                "status": "out" if is_out else "not out",
                "match_id": r['match_id'],
                "match_date": r['match_date'] or "-",
                "ground": r['ground'] or "-",
                "opponent": r['opponent_name'] or "-"
            })
        return results
    finally:
        if close:
            conn.close()


# --- MASTER DISPATCHER ---

STATISTIC_CALCULATORS = {
    "most_runs": lambda params, conn: calculate_most_runs(conn),
    "most_wickets": lambda params, conn: calculate_most_wickets(conn),
    "best_strike_rate": lambda params, conn: calculate_best_strike_rate(
        min_balls=int(params.get("min_balls", 20)), conn=conn
    ),
    "best_average": lambda params, conn: calculate_best_average(
        min_matches=int(params.get("min_matches", 2)), conn=conn
    ),
    "best_economy": lambda params, conn: calculate_best_economy(
        min_overs=float(params.get("min_overs", 5.0)), conn=conn
    ),
    "most_catches": lambda params, conn: calculate_most_catches(conn),
    "most_runouts": lambda params, conn: calculate_most_runouts(conn),
    "most_boundaries": lambda params, conn: calculate_most_boundaries(conn),
    "most_sixes": lambda params, conn: calculate_most_sixes(conn),
    "most_fours": lambda params, conn: calculate_most_fours(conn),
    "best_spell": lambda params, conn: calculate_best_spell(conn),
    "best_innings": lambda params, conn: calculate_best_innings(conn),
}


def calculate_statistic_by_key(stat_key: str, params: Optional[dict] = None, conn=None) -> Dict[str, Any]:
    """
    Executes an on-demand calculation for the requested statistic only.
    Saves the result to cache with current completed matches count.
    """
    if stat_key not in STATISTIC_CALCULATORS:
        raise ValueError(f"Unknown statistic key '{stat_key}'")

    close = False
    if conn is None:
        conn = get_db_connection()
        close = True

    try:
        meta = STATISTICS_REGISTRY.get(stat_key, {})
        effective_params = dict(meta.get("default_params", {}))
        if params:
            effective_params.update(params)

        calc_fn = STATISTIC_CALCULATORS[stat_key]
        result_data = calc_fn(effective_params, conn)

        completed_count = get_completed_matches_count(conn)
        save_cached_statistic(stat_key, effective_params, result_data, completed_count, conn)

        now_str = datetime.now().strftime('%d %b %Y %H:%M')
        return {
            "stat_key": stat_key,
            "title": meta.get("title", stat_key),
            "params": effective_params,
            "result": result_data,
            "completed_matches_count": completed_count,
            "calculated_at": now_str,
            "status": "fresh",
            "status_label": "UP TO DATE"
        }
    finally:
        if close:
            conn.close()
