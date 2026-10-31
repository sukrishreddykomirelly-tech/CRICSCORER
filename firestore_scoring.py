"""Firestore live scoring data access layer.

Provides real-time read and write operations for live cricket scoring directly
against Cloud Firestore, with optional mirror syncing to SQL.
"""

from __future__ import annotations

import datetime
import time
from typing import Any, Dict, List, Optional, Tuple

from scoring import MatchState
import firestore_db

# In-memory short-lived cache for static/semi-static references (players, teams)
_CACHE_TTL = 30  # seconds
_players_cache: Dict[str, Any] = {"data": {}, "expires": 0}
_teams_cache: Dict[str, Any] = {"data": {}, "expires": 0}


def is_firestore_enabled() -> bool:
    """Return True if Firestore credentials are configured and client is usable."""
    return firestore_db.is_firestore_configured()


def _get_db():
    return firestore_db.get_firestore_client()


try:
    from google.cloud.firestore_v1.base_query import FieldFilter
    def _where_eq(query_or_coll, field, val):
        try:
            return query_or_coll.where(filter=FieldFilter(field, "==", val))
        except (TypeError, ValueError):
            return query_or_coll.where(field, "==", val)
    def _where_in(query_or_coll, field, vals):
        try:
            return query_or_coll.where(filter=FieldFilter(field, "in", vals))
        except (TypeError, ValueError):
            return query_or_coll.where(field, "in", vals)
except Exception:
    def _where_eq(query_or_coll, field, val):
        return query_or_coll.where(field, "==", val)
    def _where_in(query_or_coll, field, vals):
        return query_or_coll.where(field, "in", vals)


# --- ATOMIC ID GENERATION ---

def get_next_sequence_id(collection_name: str) -> int:
    """Return the next monotonic integer ID for a collection using Firestore transaction."""
    db = _get_db()
    counter_ref = db.collection("counters").document(collection_name)
    
    # We do a transactional get-and-increment
    from google.cloud import firestore as g_firestore
    
    transaction = db.transaction()
    
    @g_firestore.transactional
    def _in_transaction(txn):
        snapshot = counter_ref.get(transaction=txn)
        if snapshot.exists:
            current_id = snapshot.to_dict().get("last_id", 0)
            next_id = int(current_id) + 1
            txn.update(counter_ref, {"last_id": next_id})
            return next_id
        else:
            # Query the collection for existing highest integer ID
            max_id = 0
            for doc in db.collection(collection_name).stream():
                if doc.id.isdigit():
                    max_id = max(max_id, int(doc.id))
                doc_data = doc.to_dict() or {}
                if isinstance(doc_data.get("id"), (int, float)):
                    max_id = max(max_id, int(doc_data["id"]))
            next_id = max_id + 1
            txn.set(counter_ref, {"last_id": next_id})
            return next_id

    return _in_transaction(transaction)


# --- CACHED LOOKUPS ---

def get_all_players() -> Dict[int, Dict[str, Any]]:
    """Return dictionary of player_id -> player_dict with caching."""
    now = time.time()
    if _players_cache["data"] and now < _players_cache["expires"]:
        return _players_cache["data"]
        
    db = _get_db()
    players: Dict[int, Dict[str, Any]] = {}
    for doc in db.collection("players").stream():
        data = doc.to_dict() or {}
        p_id = int(data.get("id") or doc.id)
        data["id"] = p_id
        players[p_id] = data
        
    _players_cache["data"] = players
    _players_cache["expires"] = now + _CACHE_TTL
    return players


def get_all_teams() -> Dict[int, Dict[str, Any]]:
    """Return dictionary of team_id -> team_dict with caching."""
    now = time.time()
    if _teams_cache["data"] and now < _teams_cache["expires"]:
        return _teams_cache["data"]
        
    db = _get_db()
    teams: Dict[int, Dict[str, Any]] = {}
    for doc in db.collection("teams").stream():
        data = doc.to_dict() or {}
        t_id = int(data.get("id") or doc.id)
        data["id"] = t_id
        teams[t_id] = data
        
    _teams_cache["data"] = teams
    _teams_cache["expires"] = now + _CACHE_TTL
    return teams


# --- LIVE MATCH STATE LOADER ---

def firestore_load_match_state(match_id: int, is_rebuilding: bool = False) -> Optional[MatchState]:
    """Hydrate a MatchState instance by reading data directly from Cloud Firestore."""
    db = _get_db()
    match_ref = db.collection("matches").document(str(match_id))
    match_doc = match_ref.get()
    if not match_doc.exists:
        return None
        
    match_row = match_doc.to_dict() or {}
    team1_id = int(match_row.get("team1_id", 0))
    team2_id = int(match_row.get("team2_id", 0))
    
    # Count dynamic squad size to determine wickets limit
    mp_query = _where_eq(db.collection("match_players"), "match_id", int(match_id)).stream()
    mp_list = [d.to_dict() for d in mp_query]
    
    t1_count = sum(1 for r in mp_list if int(r.get("team_id", 0)) == team1_id) or 11
    t2_count = sum(1 for r in mp_list if int(r.get("team_id", 0)) == team2_id) or 11
    players_per_team = max(t1_count, t2_count)
    
    single_batting = bool(match_row.get("single_batting", False))
    
    match_state = MatchState(
        match_id=int(match_id),
        team1_id=team1_id,
        team2_id=team2_id,
        match_format=match_row.get("match_format", "T20"),
        overs_limit=int(match_row.get("overs_limit", 20)),
        players_per_team=players_per_team,
        single_batting=single_batting
    )
    
    match_state.status = match_row.get("status", "scheduled")
    match_state.toss_winner_id = match_row.get("toss_winner_id")
    match_state.toss_decision = match_row.get("toss_decision")
    match_state.winner_id = match_row.get("winner_id")
    match_state.result_margin = match_row.get("result_margin")
    match_state.is_super_over = match_row.get("is_super_over", 0)
    
    # Load substitutions
    sub_docs = _where_eq(db.collection("substitutions"), "match_id", int(match_id)).stream()
    match_state.substitutions = [
        {
            "innings_id": int(r.get("innings_id", 0)),
            "outgoing_id": int(r.get("outgoing_id", 0)),
            "incoming_id": int(r.get("incoming_id", 0))
        }
        for doc in sub_docs
        for r in [doc.to_dict()]
    ]
    
    # Hydrate Player Names
    players = get_all_players()
    for p_id, p_info in players.items():
        match_state.add_player_name(p_id, p_info.get("name", f"Player {p_id}"))
        
    # Fetch Innings for this match
    inn_docs = _where_eq(db.collection("innings"), "match_id", int(match_id)).stream()
    innings_list = [d.to_dict() for d in inn_docs]
    innings_list.sort(key=lambda x: int(x.get("innings_number", 1)))
    
    for inn_row in innings_list:
        inn_id = int(inn_row.get("id", 0))
        match_state.start_innings(
            innings_id=inn_id,
            batting_team_id=int(inn_row.get("batting_team_id", 0)),
            bowling_team_id=int(inn_row.get("bowling_team_id", 0)),
            innings_number=int(inn_row.get("innings_number", 1))
        )
        
        inn_state = match_state.get_current_innings()
        if inn_state:
            inn_state.striker_id = inn_row.get("current_striker_id")
            inn_state.non_striker_id = inn_row.get("current_non_striker_id")
            inn_state.bowler_id = inn_row.get("current_bowler_id")
            
        # Load all deliveries for this innings
        del_docs = _where_eq(db.collection("deliveries"), "innings_id", inn_id).stream()
        del_list = [d.to_dict() for d in del_docs]
        # Chronological sort without requiring Firestore composite index
        del_list.sort(key=lambda x: (
            int(x.get("over_number", 0)),
            int(x.get("ball_of_over", 0)),
            int(x.get("delivery_count", 0)),
            int(x.get("id", 0))
        ))
        
        for d_row in del_list:
            if inn_state:
                inn_state.striker_id = d_row.get("striker_id")
                inn_state.non_striker_id = d_row.get("non_striker_id")
                inn_state.bowler_id = d_row.get("bowler_id")
                
            d_dict = {
                "runs_batter": int(d_row.get("runs_batter", 0)),
                "runs_extras": int(d_row.get("runs_extras", 0)),
                "extra_type": d_row.get("extra_type"),
                "is_legal": int(d_row.get("is_legal", 1)),
                "is_wicket": int(d_row.get("is_wicket", 0)),
                "wicket_type": d_row.get("wicket_type"),
                "player_dismissed_id": d_row.get("player_dismissed_id"),
                "fielder_id": d_row.get("fielder_id"),
                "over_number": int(d_row.get("over_number", 1)),
                "ball_of_over": int(d_row.get("ball_of_over", 1)),
                "delivery_count": int(d_row.get("delivery_count", 1)),
                "commentary": d_row.get("commentary", ""),
                "is_bowler_wicket": int(d_row.get("is_bowler_wicket", 0)),
                "striker_id": d_row.get("striker_id"),
                "non_striker_id": d_row.get("non_striker_id"),
                "bowler_id": d_row.get("bowler_id"),
                "new_batter_id": d_row.get("new_batter_id"),
                "next_striker_id": d_row.get("next_striker_id")
            }
            match_state.apply_delivery(d_dict)
            
        # Apply substitutions
        for sub in match_state.substitutions:
            if sub.get("innings_id") in (inn_id, 0):
                if inn_state:
                    if inn_state.striker_id == sub["outgoing_id"]:
                        inn_state.striker_id = sub["incoming_id"]
                    if inn_state.non_striker_id == sub["outgoing_id"]:
                        inn_state.non_striker_id = sub["incoming_id"]
                    if inn_state.bowler_id == sub["outgoing_id"]:
                        inn_state.bowler_id = sub["incoming_id"]
                        
        # Crease hydration if not rebuilding (preserves manual swaps / wicket choices)
        if not is_rebuilding and inn_state:
            if inn_row.get("current_striker_id") is not None:
                inn_state.striker_id = inn_row["current_striker_id"]
            if inn_row.get("current_non_striker_id") is not None:
                inn_state.non_striker_id = inn_row["current_non_striker_id"]
            if inn_row.get("current_bowler_id") is not None:
                try:
                    inn_state.bowler_id = int(inn_row["current_bowler_id"])
                except (ValueError, TypeError):
                    inn_state.bowler_id = inn_row["current_bowler_id"]

    if match_row.get("status") in ("completed", "abandoned"):
        match_state.status = match_row["status"]
        if match_row.get("winner_id"):
            match_state.winner_id = match_row["winner_id"]
        if match_row.get("result_margin"):
            match_state.result_margin = match_row["result_margin"]
            
    return match_state


def firestore_get_match_metadata(match_id: int) -> Optional[Dict[str, Any]]:
    """Fetch teams, squad rosters, and ground/date details from Cloud Firestore."""
    db = _get_db()
    match_doc = db.collection("matches").document(str(match_id)).get()
    if not match_doc.exists:
        return None
        
    m_details = match_doc.to_dict() or {}
    team1_id = int(m_details.get("team1_id", 0))
    team2_id = int(m_details.get("team2_id", 0))
    
    teams = get_all_teams()
    players = get_all_players()
    
    t1 = teams.get(team1_id, {})
    t2 = teams.get(team2_id, {})
    
    team1_name = t1.get("name", "Team 1")
    team1_logo = t1.get("logo_url", "")
    team2_name = t2.get("name", "Team 2")
    team2_logo = t2.get("logo_url", "")
    
    mp_query = _where_eq(db.collection("match_players"), "match_id", int(match_id)).stream()
    team1_squad = []
    team2_squad = []
    for doc in mp_query:
        row = doc.to_dict()
        p_id = int(row.get("player_id", 0))
        t_id = int(row.get("team_id", 0))
        p_name = players.get(p_id, {}).get("name", f"Player {p_id}")
        p_dict = {"id": p_id, "name": p_name}
        if t_id == team1_id:
            team1_squad.append(p_dict)
        else:
            team2_squad.append(p_dict)
            
    return {
        "team1_name": team1_name,
        "team1_logo": team1_logo,
        "team2_name": team2_name,
        "team2_logo": team2_logo,
        "m_details": m_details,
        "team1_squad": team1_squad,
        "team2_squad": team2_squad
    }


# --- LIVE SCORING WRITE OPERATIONS ---

def firestore_save_delivery(innings_id: int, d: Dict[str, Any]) -> int:
    """Save a delivery to Cloud Firestore and update match state."""
    db = _get_db()
    
    # Generate monotonic ID
    del_id = get_next_sequence_id("deliveries")
    
    delivery_data = {
        "id": del_id,
        "innings_id": int(innings_id),
        "over_number": int(d.get("over_number", 1)),
        "ball_of_over": int(d.get("ball_of_over", 1)),
        "delivery_count": int(d.get("delivery_count", 1)),
        "striker_id": d.get("striker_id"),
        "non_striker_id": d.get("non_striker_id"),
        "bowler_id": d.get("bowler_id"),
        "runs_batter": int(d.get("runs_batter", 0)),
        "runs_extras": int(d.get("runs_extras", 0)),
        "extra_type": d.get("extra_type"),
        "is_legal": int(d.get("is_legal", 1)),
        "is_wicket": int(d.get("is_wicket", 0)),
        "wicket_type": d.get("wicket_type"),
        "player_dismissed_id": d.get("player_dismissed_id"),
        "fielder_id": d.get("fielder_id"),
        "is_bowler_wicket": int(d.get("is_bowler_wicket", 0)),
        "commentary": d.get("commentary", ""),
        "new_batter_id": d.get("new_batter_id"),
        "next_striker_id": d.get("next_striker_id"),
        "created_at": datetime.datetime.now().isoformat()
    }
    
    # 1. Write to Firestore
    db.collection("deliveries").document(str(del_id)).set(delivery_data)
    
    # 2. Get match_id for this innings
    inn_doc = db.collection("innings").document(str(innings_id)).get()
    if inn_doc.exists:
        match_id = int(inn_doc.to_dict().get("match_id", 0))
    else:
        match_id = 0
        
    # 3. Mirror write to SQL if connection is available
    _mirror_sql_save_delivery(del_id, innings_id, d)
    
    # 4. Rebuild & cache match state summaries
    if match_id:
        firestore_rebuild_and_cache_match_state(match_id)
        
    return match_id


def firestore_delete_last_delivery(innings_id: int) -> int:
    """Delete the latest delivery in an innings from Cloud Firestore (Undo)."""
    db = _get_db()
    
    # Find all deliveries for this innings
    del_docs = list(_where_eq(db.collection("deliveries"), "innings_id", int(innings_id)).stream())

    if del_docs:
        del_docs.sort(key=lambda doc: (
            int(doc.to_dict().get("over_number", 0)),
            int(doc.to_dict().get("ball_of_over", 0)),
            int(doc.to_dict().get("delivery_count", 0)),
            int(doc.to_dict().get("id", 0))
        ))
        last_doc = del_docs[-1]
        del_id = int(last_doc.to_dict().get("id") or last_doc.id)
        last_doc.reference.delete()
        
        # Mirror delete to SQL
        _mirror_sql_delete_delivery(del_id)
        
    # Get match ID
    inn_doc = db.collection("innings").document(str(innings_id)).get()
    match_id = int(inn_doc.to_dict().get("match_id", 0)) if inn_doc.exists else 0
    
    if match_id:
        firestore_rebuild_and_cache_match_state(match_id)
        
    return match_id


def firestore_rebuild_and_cache_match_state(match_id: int) -> None:
    """Replay deliveries from Cloud Firestore and persist precomputed totals."""
    match_state = firestore_load_match_state(match_id, is_rebuilding=True)
    if not match_state:
        return
        
    db = _get_db()
    batch = db.batch()
    
    # 1. Update Match record
    match_ref = db.collection("matches").document(str(match_id))
    batch.update(match_ref, {
        "status": match_state.status,
        "winner_id": match_state.winner_id,
        "result_margin": match_state.result_margin
    })
    
    # 2. Update each Innings summary
    for inn in match_state.innings:
        inn_ref = db.collection("innings").document(str(inn.innings_id))
        batch.update(inn_ref, {
            "total_runs": inn.total_runs,
            "total_wickets": inn.total_wickets,
            "balls_bowled": inn.balls_bowled,
            "wides": inn.wides,
            "noballs": inn.noballs,
            "byes": inn.byes,
            "legbyes": inn.legbyes,
            "status": inn.status,
            "current_striker_id": inn.striker_id,
            "current_non_striker_id": inn.non_striker_id,
            "current_bowler_id": inn.bowler_id
        })
        
    batch.commit()
    
    # Mirror rebuild to SQL
    _mirror_sql_rebuild_cache(match_state)


def firestore_change_bowler(match_id: int, innings_id: int, bowler_id: int) -> None:
    """Update active bowler in Cloud Firestore."""
    db = _get_db()
    inn_ref = db.collection("innings").document(str(innings_id))
    inn_ref.update({"current_bowler_id": int(bowler_id)})
    _mirror_sql_update_innings(innings_id, {"current_bowler_id": int(bowler_id)})


def firestore_change_batsman(
    match_id: int,
    innings_id: int,
    striker_id: Optional[int] = None,
    non_striker_id: Optional[int] = None
) -> None:
    """Update active striker and/or non-striker in Cloud Firestore."""
    db = _get_db()
    updates: Dict[str, Any] = {}
    if striker_id is not None:
        updates["current_striker_id"] = int(striker_id)
    if non_striker_id is not None:
        updates["current_non_striker_id"] = int(non_striker_id)
    if updates:
        db.collection("innings").document(str(innings_id)).update(updates)
        _mirror_sql_update_innings(innings_id, updates)


def firestore_start_second_innings(
    match_id: int,
    striker_id: int,
    non_striker_id: int,
    bowler_id: int
) -> int:
    """Initialize second innings in Cloud Firestore."""
    db = _get_db()
    
    # Innings 1 details
    inn1_query = _where_eq(_where_eq(db.collection("innings"), "match_id", int(match_id)), "innings_number", 1).stream()
    inn1_docs = list(inn1_query)
    if not inn1_docs:
        raise ValueError(f"Innings 1 not found for match {match_id}")
        
    inn1 = inn1_docs[0].to_dict()
    bat_team = int(inn1["bowling_team_id"])
    bowl_team = int(inn1["batting_team_id"])
    
    new_inn_id = get_next_sequence_id("innings")
    inn2_data = {
        "id": new_inn_id,
        "match_id": int(match_id),
        "innings_number": 2,
        "batting_team_id": bat_team,
        "bowling_team_id": bowl_team,
        "status": "ongoing",
        "total_runs": 0,
        "total_wickets": 0,
        "balls_bowled": 0,
        "wides": 0,
        "noballs": 0,
        "byes": 0,
        "legbyes": 0,
        "current_striker_id": int(striker_id),
        "current_non_striker_id": int(non_striker_id),
        "current_bowler_id": int(bowler_id)
    }
    
    db.collection("innings").document(str(new_inn_id)).set(inn2_data)
    db.collection("matches").document(str(match_id)).update({"current_innings_id": new_inn_id})
    
    _mirror_sql_create_second_innings(match_id, new_inn_id, bat_team, bowl_team, striker_id, non_striker_id, bowler_id)
    
    firestore_rebuild_and_cache_match_state(match_id)
    return new_inn_id


def firestore_substitute_player(
    match_id: int,
    innings_id: int,
    outgoing_id: int,
    incoming_id: int,
    team_id: int
) -> None:
    """Record player substitution and update crease cache in Cloud Firestore."""
    db = _get_db()
    
    # 1. Update match_players
    mp_key = f"{match_id}_{team_id}_{outgoing_id}"
    mp_doc = db.collection("match_players").document(mp_key).get()
    batting_order = 11
    if mp_doc.exists:
        batting_order = mp_doc.to_dict().get("batting_order", 11)
        mp_doc.reference.delete()
        
    new_mp_key = f"{match_id}_{team_id}_{incoming_id}"
    db.collection("match_players").document(new_mp_key).set({
        "match_id": int(match_id),
        "team_id": int(team_id),
        "player_id": int(incoming_id),
        "batting_order": batting_order
    })
    
    # 2. Insert into substitutions
    sub_id = get_next_sequence_id("substitutions")
    db.collection("substitutions").document(str(sub_id)).set({
        "id": sub_id,
        "match_id": int(match_id),
        "innings_id": int(innings_id),
        "outgoing_id": int(outgoing_id),
        "incoming_id": int(incoming_id),
        "created_at": datetime.datetime.now().isoformat()
    })
    
    # 3. Update crease player on innings if outgoing player was active
    if innings_id:
        inn_ref = db.collection("innings").document(str(innings_id))
        inn_doc = inn_ref.get()
        if inn_doc.exists:
            inn_data = inn_doc.to_dict()
            updates = {}
            if inn_data.get("current_striker_id") == outgoing_id:
                updates["current_striker_id"] = int(incoming_id)
            if inn_data.get("current_non_striker_id") == outgoing_id:
                updates["current_non_striker_id"] = int(incoming_id)
            if inn_data.get("current_bowler_id") == outgoing_id:
                updates["current_bowler_id"] = int(incoming_id)
            if updates:
                inn_ref.update(updates)
                
    _mirror_sql_substitute(match_id, innings_id, outgoing_id, incoming_id, team_id, sub_id)
    firestore_rebuild_and_cache_match_state(match_id)


def firestore_end_match(
    match_id: int,
    outcome_type: str = "completed",
    custom_winner_id: Optional[int] = None,
    custom_margin: str = ""
) -> Dict[str, Any]:
    """Finalize a match in Cloud Firestore."""
    db = _get_db()
    match_ref = db.collection("matches").document(str(match_id))
    match_doc = match_ref.get()
    if not match_doc.exists:
        raise ValueError(f"Match {match_id} not found")
        
    match_state = firestore_load_match_state(match_id)
    winner_id = match_state.winner_id if match_state else None
    result_margin = match_state.result_margin if match_state else "Match completed"
    status = "completed"
    
    if outcome_type == "abandoned":
        status = "abandoned"
        winner_id = None
        result_margin = custom_margin or "Match abandoned (No result)"
    elif outcome_type == "tied":
        status = "completed"
        winner_id = None
        result_margin = custom_margin or "Match tied"
    elif outcome_type == "custom":
        status = "completed"
        winner_id = int(custom_winner_id) if custom_winner_id and str(custom_winner_id).lower() != "none" else winner_id
        result_margin = custom_margin or result_margin
    else:
        # Default auto calculation from innings
        inn_docs = list(_where_eq(db.collection("innings"), "match_id", int(match_id)).stream())
        inn_docs.sort(key=lambda d: int(d.to_dict().get("innings_number", 1)))
        if len(inn_docs) >= 2:
            i1 = inn_docs[0].to_dict()
            i2 = inn_docs[1].to_dict()
            t1_runs = int(i1.get("total_runs", 0))
            t2_runs = int(i2.get("total_runs", 0))
            if t1_runs > t2_runs:
                winner_id = i1.get("batting_team_id")
                result_margin = f"Won by {t1_runs - t2_runs} runs"
            elif t2_runs > t1_runs:
                winner_id = i2.get("batting_team_id")
                result_margin = "Won by wickets"
            else:
                winner_id = None
                result_margin = "Match tied"
        elif len(inn_docs) == 1:
            i1 = inn_docs[0].to_dict()
            winner_id = i1.get("batting_team_id")
            result_margin = f"Completed (1st Inn: {i1.get('total_runs', 0)})"

    match_ref.update({
        "status": status,
        "winner_id": winner_id,
        "result_margin": result_margin
    })
    
    # Mark ongoing innings completed
    for inn_doc in _where_eq(db.collection("innings"), "match_id", int(match_id)).stream():
        if inn_doc.to_dict().get("status") == "ongoing":
            inn_doc.reference.update({"status": "completed"})

            
    _mirror_sql_end_match(match_id, status, winner_id, result_margin)
    firestore_rebuild_and_cache_match_state(match_id)
    
    return {
        "success": True,
        "match_id": match_id,
        "status": status,
        "winner_id": winner_id,
        "result_margin": result_margin
    }


def firestore_set_toss(match_id: int, toss_winner_id: int, toss_decision: str) -> None:
    """Record toss in Cloud Firestore."""
    db = _get_db()
    db.collection("matches").document(str(match_id)).update({
        "toss_winner_id": int(toss_winner_id),
        "toss_decision": toss_decision,
        "status": "toss_done"
    })
    _mirror_sql_set_toss(match_id, toss_winner_id, toss_decision)


def firestore_setup_crease(
    match_id: int,
    bat_team_id: int,
    bowl_team_id: int,
    striker_id: int,
    non_striker_id: int,
    bowler_id: int
) -> int:
    """Setup opening crease and start match in Cloud Firestore."""
    db = _get_db()
    innings_id = get_next_sequence_id("innings")
    
    inn_data = {
        "id": innings_id,
        "match_id": int(match_id),
        "innings_number": 1,
        "batting_team_id": int(bat_team_id),
        "bowling_team_id": int(bowl_team_id),
        "status": "ongoing",
        "total_runs": 0,
        "total_wickets": 0,
        "balls_bowled": 0,
        "wides": 0,
        "noballs": 0,
        "byes": 0,
        "legbyes": 0,
        "current_striker_id": int(striker_id),
        "current_non_striker_id": int(non_striker_id),
        "current_bowler_id": int(bowler_id)
    }
    db.collection("innings").document(str(innings_id)).set(inn_data)
    
    db.collection("matches").document(str(match_id)).update({
        "status": "live",
        "current_innings_id": innings_id
    })
    
    _mirror_sql_setup_crease(match_id, innings_id, bat_team_id, bowl_team_id, striker_id, non_striker_id, bowler_id)
    return innings_id


def firestore_create_match(match_data: Dict[str, Any], team1_xi: List[int], team2_xi: List[int]) -> int:
    """Create a new match and player rosters in Cloud Firestore."""
    db = _get_db()
    match_id = get_next_sequence_id("matches")
    
    doc = {
        "id": match_id,
        "tournament_id": match_data.get("tournament_id"),
        "team1_id": int(match_data["team1_id"]),
        "team2_id": int(match_data["team2_id"]),
        "match_format": match_data.get("match_format", "T20"),
        "overs_limit": int(match_data.get("overs_limit", 20)),
        "ground": match_data.get("ground", ""),
        "match_date": match_data.get("match_date", ""),
        "match_time": match_data.get("match_time", ""),
        "status": "scheduled",
        "single_batting": int(match_data.get("single_batting", 0)),
        "toss_winner_id": None,
        "toss_decision": None,
        "winner_id": None,
        "result_margin": None,
        "current_innings_id": None,
        "is_super_over": 0
    }
    db.collection("matches").document(str(match_id)).set(doc)
    
    for order, p_id in enumerate(team1_xi, start=1):
        key = f"{match_id}_{match_data['team1_id']}_{p_id}"
        db.collection("match_players").document(key).set({
            "match_id": match_id,
            "team_id": int(match_data["team1_id"]),
            "player_id": int(p_id),
            "batting_order": order
        })
        
    for order, p_id in enumerate(team2_xi, start=1):
        key = f"{match_id}_{match_data['team2_id']}_{p_id}"
        db.collection("match_players").document(key).set({
            "match_id": match_id,
            "team_id": int(match_data["team2_id"]),
            "player_id": int(p_id),
            "batting_order": order
        })
        
    _mirror_sql_create_match(match_id, match_data, team1_xi, team2_xi)
    return match_id


# --- LIVE MATCHES FOR DASHBOARD ---

def firestore_get_live_matches() -> List[Dict[str, Any]]:
    """Query live and in-progress matches from Cloud Firestore."""
    db = _get_db()
    live_docs = list(_where_in(db.collection("matches"), "status", ["live", "toss_done"]).stream())
    
    teams = get_all_teams()
    results = []
    
    from database import _map_match_team_scores
    
    for doc in live_docs:
        m = doc.to_dict()
        m_id = int(m.get("id") or doc.id)
        t1_id = int(m.get("team1_id", 0))
        t2_id = int(m.get("team2_id", 0))
        
        t1 = teams.get(t1_id, {})
        t2 = teams.get(t2_id, {})
        
        m["team1_name"] = t1.get("name", f"Team {t1_id}")
        m["team2_name"] = t2.get("name", f"Team {t2_id}")
        m["team1_logo"] = t1.get("logo_url", "")
        m["team2_logo"] = t2.get("logo_url", "")
        
        # Load innings 1 and 2
        inn_docs = list(_where_eq(db.collection("innings"), "match_id", m_id).stream())

        for inn in inn_docs:
            i_data = inn.to_dict()
            num = int(i_data.get("innings_number", 1))
            prefix = f"i{num}_"
            m[f"{prefix}id"] = i_data.get("id")
            m[f"{prefix}batting_team_id"] = i_data.get("batting_team_id")
            m[f"{prefix}runs"] = i_data.get("total_runs", 0)
            m[f"{prefix}wkts"] = i_data.get("total_wickets", 0)
            m[f"{prefix}balls"] = i_data.get("balls_bowled", 0)
            
        results.append(_map_match_team_scores(m))
        
    return results


# --- SQL MIRRORING (FAIL-SAFE HELPERS) ---

def _get_sql_cursor():
    try:
        from database import get_db_connection
        conn = get_db_connection()
        return conn, conn.cursor()
    except Exception:
        return None, None


def _mirror_sql_save_delivery(del_id: int, innings_id: int, d: Dict[str, Any]):
    conn, cursor = _get_sql_cursor()
    if not conn:
        return
    try:
        cursor.execute("""
            INSERT INTO deliveries (
                id, innings_id, over_number, ball_of_over, delivery_count,
                striker_id, non_striker_id, bowler_id,
                runs_batter, runs_extras, extra_type, is_legal,
                is_wicket, wicket_type, player_dismissed_id, fielder_id,
                is_bowler_wicket, commentary, new_batter_id, next_striker_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (id) DO NOTHING
        """, (
            del_id, innings_id, d.get("over_number", 1), d.get("ball_of_over", 1), d.get("delivery_count", 1),
            d.get("striker_id"), d.get("non_striker_id"), d.get("bowler_id"),
            d.get("runs_batter", 0), d.get("runs_extras", 0), d.get("extra_type"), d.get("is_legal", 1),
            d.get("is_wicket", 0), d.get("wicket_type"), d.get("player_dismissed_id"), d.get("fielder_id"),
            d.get("is_bowler_wicket", 0), d.get("commentary", ""), d.get("new_batter_id"), d.get("next_striker_id")
        ))
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()


def _mirror_sql_delete_delivery(del_id: int):
    conn, cursor = _get_sql_cursor()
    if not conn:
        return
    try:
        cursor.execute("DELETE FROM deliveries WHERE id = ?", (del_id,))
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()


def _mirror_sql_update_innings(innings_id: int, updates: Dict[str, Any]):
    conn, cursor = _get_sql_cursor()
    if not conn:
        return
    try:
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [innings_id]
        cursor.execute(f"UPDATE innings SET {set_clause} WHERE id = ?", tuple(values))
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()


def _mirror_sql_rebuild_cache(match_state: MatchState):
    conn, cursor = _get_sql_cursor()
    if not conn:
        return
    try:
        cursor.execute("""
            UPDATE matches 
            SET status = ?, winner_id = ?, result_margin = ?
            WHERE id = ?
        """, (match_state.status, match_state.winner_id, match_state.result_margin, match_state.match_id))
        
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
    except Exception:
        pass
    finally:
        conn.close()


def _mirror_sql_create_second_innings(match_id, inn_id, bat_team, bowl_team, striker_id, non_striker_id, bowler_id):
    conn, cursor = _get_sql_cursor()
    if not conn:
        return
    try:
        cursor.execute("""
            INSERT INTO innings (id, match_id, innings_number, batting_team_id, bowling_team_id, status, current_striker_id, current_non_striker_id, current_bowler_id)
            VALUES (?, ?, 2, ?, ?, 'ongoing', ?, ?, ?)
            ON CONFLICT (id) DO NOTHING
        """, (inn_id, match_id, bat_team, bowl_team, striker_id, non_striker_id, bowler_id))
        cursor.execute("UPDATE matches SET current_innings_id = ? WHERE id = ?", (inn_id, match_id))
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()


def _mirror_sql_substitute(match_id, innings_id, outgoing_id, incoming_id, team_id, sub_id):
    conn, cursor = _get_sql_cursor()
    if not conn:
        return
    try:
        cursor.execute("""
            UPDATE match_players
            SET player_id = ?
            WHERE match_id = ? AND team_id = ? AND player_id = ?
        """, (incoming_id, match_id, team_id, outgoing_id))
        cursor.execute("""
            INSERT INTO substitutions (id, match_id, innings_id, outgoing_id, incoming_id)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (id) DO NOTHING
        """, (sub_id, match_id, innings_id, outgoing_id, incoming_id))
        if innings_id:
            cursor.execute("UPDATE innings SET current_striker_id = ? WHERE id = ? AND current_striker_id = ?", (incoming_id, innings_id, outgoing_id))
            cursor.execute("UPDATE innings SET current_non_striker_id = ? WHERE id = ? AND current_non_striker_id = ?", (incoming_id, innings_id, outgoing_id))
            cursor.execute("UPDATE innings SET current_bowler_id = ? WHERE id = ? AND current_bowler_id = ?", (incoming_id, innings_id, outgoing_id))
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()


def _mirror_sql_end_match(match_id, status, winner_id, result_margin):
    conn, cursor = _get_sql_cursor()
    if not conn:
        return
    try:
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
    except Exception:
        pass
    finally:
        conn.close()


def _mirror_sql_set_toss(match_id, toss_winner_id, toss_decision):
    conn, cursor = _get_sql_cursor()
    if not conn:
        return
    try:
        cursor.execute("""
            UPDATE matches 
            SET toss_winner_id = ?, toss_decision = ?, status = 'toss_done'
            WHERE id = ?
        """, (toss_winner_id, toss_decision, match_id))
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()


def _mirror_sql_setup_crease(match_id, innings_id, bat_team, bowl_team, striker_id, non_striker_id, bowler_id):
    conn, cursor = _get_sql_cursor()
    if not conn:
        return
    try:
        cursor.execute("""
            INSERT INTO innings (id, match_id, innings_number, batting_team_id, bowling_team_id, status, current_striker_id, current_non_striker_id, current_bowler_id)
            VALUES (?, ?, 1, ?, ?, 'ongoing', ?, ?, ?)
            ON CONFLICT (id) DO NOTHING
        """, (innings_id, match_id, bat_team, bowl_team, striker_id, non_striker_id, bowler_id))
        cursor.execute("UPDATE matches SET status = 'live', current_innings_id = ? WHERE id = ?", (innings_id, match_id))
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()


def _mirror_sql_create_match(match_id, match_data, team1_xi, team2_xi):
    conn, cursor = _get_sql_cursor()
    if not conn:
        return
    try:
        cursor.execute("""
            INSERT INTO matches (id, tournament_id, team1_id, team2_id, match_format, overs_limit, ground, match_date, match_time, status, single_batting)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'scheduled', ?)
            ON CONFLICT (id) DO NOTHING
        """, (
            match_id, match_data.get("tournament_id"), int(match_data["team1_id"]), int(match_data["team2_id"]),
            match_data.get("match_format", "T20"), int(match_data.get("overs_limit", 20)),
            match_data.get("ground", ""), match_data.get("match_date", ""), match_data.get("match_time", ""),
            int(match_data.get("single_batting", 0))
        ))
        for order, p_id in enumerate(team1_xi, start=1):
            cursor.execute("""
                INSERT INTO match_players (match_id, team_id, player_id, batting_order)
                VALUES (?, ?, ?, ?)
                ON CONFLICT DO NOTHING
            """, (match_id, int(match_data["team1_id"]), int(p_id), order))
        for order, p_id in enumerate(team2_xi, start=1):
            cursor.execute("""
                INSERT INTO match_players (match_id, team_id, player_id, batting_order)
                VALUES (?, ?, ?, ?)
                ON CONFLICT DO NOTHING
            """, (match_id, int(match_data["team2_id"]), int(p_id), order))
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()
