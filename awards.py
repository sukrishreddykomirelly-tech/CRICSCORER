from database import get_db_connection

def calculate_awards(match_state):
    """
    Calculates the Cricket Impact Rating and Automatic Match Awards for a completed match.
    Returns a dictionary containing the awards and the performance table breakdown.
    """
    match_id = match_state.match_id
    players = match_state.player_names
    winner_id = match_state.winner_id
    
    # 1. Fetch player team mappings
    player_teams = {}
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT player_id, team_id FROM match_players WHERE match_id = ?", (match_id,))
        player_teams = {row['player_id']: row['team_id'] for row in cursor.fetchall()}
        conn.close()
    except Exception:
        player_teams = {}

    # If no players are registered in match_players, use player_names mapping to current innings teams
    if not player_teams and match_state.innings:
        # Fallback map
        for p_id in players:
            player_teams[p_id] = match_state.innings[0].batting_team_id

    # 2. Initialize rating stats for all players
    impact_stats = {}
    for p_id, p_name in players.items():
        impact_stats[p_id] = {
            "id": p_id,
            "name": p_name,
            "team_id": player_teams.get(p_id),
            "batting_runs": 0,
            "batting_balls": 0,
            "batting_fours": 0,
            "batting_sixes": 0,
            "batting_out": False,
            "bowling_balls": 0,
            "bowling_runs": 0,
            "bowling_wickets": 0,
            "bowling_maidens": 0,
            "fielding_catches": 0,
            "fielding_stumpings": 0,
            "fielding_run_outs": 0,
            "batting_impact": 0,
            "bowling_impact": 0,
            "fielding_impact": 0,
            "situation_impact": 0,
            "total_impact": 0,
            "important_wickets": 0,
            "winning_contribution": 0
        }

    # Helper variables for match context
    innings_list = match_state.innings
    chase_innings = None
    target_runs = None
    
    if len(innings_list) >= 2:
        # Innings 2 is the chase
        chase_innings = innings_list[1]
        target_runs = innings_list[0].total_runs + 1

    # 3. Populate raw statistics from innings scorecards
    for inn_idx, inn in enumerate(innings_list):
        is_chase_inn = (inn_idx == 1)
        
        # Batting Stats
        for p_id, b_data in inn.batting_scores.items():
            p_id = int(p_id)
            if p_id not in impact_stats:
                continue
            p_stat = impact_stats[p_id]
            p_stat["batting_runs"] = b_data.get("runs", 0)
            p_stat["batting_balls"] = b_data.get("balls", 0)
            p_stat["batting_fours"] = b_data.get("fours", 0)
            p_stat["batting_sixes"] = b_data.get("sixes", 0)
            p_stat["batting_out"] = (b_data.get("status") == "out")

        # Bowling Stats
        for p_id, bowl_data in inn.bowling_scores.items():
            p_id = int(p_id)
            if p_id not in impact_stats:
                continue
            p_stat = impact_stats[p_id]
            p_stat["bowling_balls"] = bowl_data.get("balls", 0)
            p_stat["bowling_runs"] = bowl_data.get("runs_conceded", 0)
            p_stat["bowling_wickets"] = bowl_data.get("wickets", 0)
            p_stat["bowling_maidens"] = bowl_data.get("maidens", 0)

        # Fielding Stats (catches, stumpings, run-outs)
        for p_id, field_data in inn.fielding_scores.items():
            p_id = int(p_id)
            if p_id not in impact_stats:
                continue
            p_stat = impact_stats[p_id]
            p_stat["fielding_catches"] = field_data.get("catches", 0)
            p_stat["fielding_stumpings"] = field_data.get("stumpings", 0)
            p_stat["fielding_run_outs"] = field_data.get("run_outs", 0)

    # 4. Calculate Batting Impact
    for p_id, p_stat in impact_stats.items():
        runs = p_stat["batting_runs"]
        balls = p_stat["batting_balls"]
        fours = p_stat["batting_fours"]
        sixes = p_stat["batting_sixes"]
        
        if balls == 0 and runs == 0:
            continue
            
        bat_imp = runs
        # Boundaries bonus
        bat_imp += fours * 1 + sixes * 2
        
        # Milestones (non-stackable)
        if runs >= 100:
            bat_imp += 25
        elif runs >= 75:
            bat_imp += 15
        elif runs >= 50:
            bat_imp += 10
        elif runs >= 30:
            bat_imp += 5
            
        # Strike Rate Bonus (min 10 balls)
        if balls >= 10:
            sr = (runs * 100.0) / balls
            if sr >= 150:
                bat_imp += 8
            elif sr >= 125:
                bat_imp += 4
            elif sr >= 100:
                bat_imp += 2
                
        # Successful Chase proportion contribution
        if chase_innings and p_stat["team_id"] == winner_id and p_stat["team_id"] == chase_innings.batting_team_id:
            if target_runs and target_runs > 0:
                prop = (runs * 1.0) / target_runs
                if prop >= 0.40:
                    bat_imp += 10
                elif prop >= 0.25:
                    bat_imp += 5
                    
        # Winning Contribution (conservative check)
        if p_stat["team_id"] == winner_id and winner_id is not None:
            team_runs = 0
            for inner_inn in innings_list:
                if inner_inn.batting_team_id == winner_id:
                    team_runs = inner_inn.total_runs
                    break
            
            if team_runs > 0:
                # Scored >= 35% of winning team total OR not out at the end of a successful chase with >= 20 runs
                is_chase_winner = (chase_innings and chase_innings.batting_team_id == winner_id)
                scored_35_percent = (runs >= team_runs * 0.35)
                not_out_in_chase = (is_chase_winner and not p_stat["batting_out"] and runs >= 20)
                
                if scored_35_percent or not_out_in_chase:
                    bat_imp += 5
                    p_stat["winning_contribution"] = 5
                    
        p_stat["batting_impact"] = bat_imp

    # 5. Calculate Bowling Impact & Important Wickets
    for p_id, p_stat in impact_stats.items():
        wickets = p_stat["bowling_wickets"]
        runs_con = p_stat["bowling_runs"]
        balls_bowled = p_stat["bowling_balls"]
        maidens = p_stat["bowling_maidens"]
        
        if balls_bowled == 0:
            continue
            
        bowl_imp = wickets * 20
        # Economy rate bonus (min 12 legal balls)
        if balls_bowled >= 12:
            econ = (runs_con * 6.0) / balls_bowled
            if econ < 5.00:
                bowl_imp += 10
            elif econ < 7.00:
                bowl_imp += 6
            elif econ < 9.00:
                bowl_imp += 2
                
        # Wicket haul bonus
        if wickets >= 5:
            bowl_imp += 25
        elif wickets >= 4:
            bowl_imp += 15
        elif wickets >= 3:
            bowl_imp += 10
            
        # Maidens bonus
        bowl_imp += maidens * 5
        
        # Important wickets: dismissals of batters who scored >= 30 runs
        imp_wkts = 0
        for inn in innings_list:
            for d in inn.deliveries:
                if d.get("bowler_id") == p_id and d.get("is_wicket") == 1:
                    dismissed_id = d.get("player_dismissed_id")
                    if dismissed_id:
                        # Find dismissed batter's score
                        bat_score = inn.batting_scores.get(dismissed_id, {}).get("runs", 0)
                        if bat_score >= 30:
                            imp_wkts += 1
        
        bowl_imp += imp_wkts * 3
        p_stat["important_wickets"] = imp_wkts
        p_stat["bowling_impact"] = bowl_imp

    # 6. Calculate Fielding Impact
    for p_id, p_stat in impact_stats.items():
        catches = p_stat["fielding_catches"]
        stumpings = p_stat["fielding_stumpings"]
        run_outs = p_stat["fielding_run_outs"]
        
        if catches == 0 and stumpings == 0 and run_outs == 0:
            continue
            
        # Catches (distinguish difficult: catch of a batsman with >= 30 runs)
        catches_imp = 0
        for inn in innings_list:
            for d in inn.deliveries:
                if d.get("fielder_id") == p_id and d.get("is_wicket") == 1:
                    dismissed_id = d.get("player_dismissed_id")
                    if dismissed_id and d.get("wicket_type") == "caught":
                        bat_score = inn.batting_scores.get(dismissed_id, {}).get("runs", 0)
                        if bat_score >= 30:
                            catches_imp += 15 # Difficult/important
                        else:
                            catches_imp += 10 # Normal
                            
        field_imp = catches_imp + stumpings * 12 + run_outs * 15
        
        # Match changing fielding (dismissal of a batsman who scored >= 50 runs)
        match_changing = False
        for inn in innings_list:
            for d in inn.deliveries:
                if d.get("fielder_id") == p_id and d.get("is_wicket") == 1:
                    dismissed_id = d.get("player_dismissed_id")
                    if dismissed_id:
                        bat_score = inn.batting_scores.get(dismissed_id, {}).get("runs", 0)
                        if bat_score >= 50:
                            match_changing = True
                            
        if match_changing:
            field_imp += 5
            
        p_stat["fielding_impact"] = field_imp

    # 7. Calculate Match Situation Impact (cap at 15)
    for p_id, p_stat in impact_stats.items():
        sit_imp = 0
        team_id = p_stat["team_id"]
        
        if team_id == winner_id and winner_id is not None:
            # 1. Successful chase contribution
            if chase_innings and team_id == chase_innings.batting_team_id:
                runs = p_stat["batting_runs"]
                if target_runs and target_runs > 0:
                    prop = (runs * 1.0) / target_runs
                    if prop >= 0.40:
                        sit_imp += 15
                    elif prop >= 0.25:
                        sit_imp += 10
                    # Winning runs scorer
                    elif chase_innings.deliveries and chase_innings.deliveries[-1].get("striker_id") == p_id:
                        sit_imp += 5
            
            # 2. Defending a total contribution
            else:
                wickets = p_stat["bowling_wickets"]
                balls = p_stat["bowling_balls"]
                runs_con = p_stat["bowling_runs"]
                catches = p_stat["fielding_catches"]
                run_outs = p_stat["fielding_run_outs"]
                
                # Bowling defense
                if wickets >= 3 or (balls >= 12 and (runs_con * 6.0 / balls) < 5.0):
                    sit_imp += 10
                # Taken final wicket to seal win
                for inn in innings_list:
                    if inn.batting_team_id != winner_id and inn.total_wickets >= inn.players_per_team - 1:
                        if inn.deliveries and inn.deliveries[-1].get("bowler_id") == p_id and inn.deliveries[-1].get("is_wicket") == 1:
                            sit_imp += 5
                
                # Fielding defense
                if catches >= 2 or run_outs >= 1:
                    sit_imp += 5
                    
            # 3. High pressure moments (Partnership & Death Over Wickets)
            # 50+ runs partnership contribution
            for inn in innings_list:
                for part in inn.partnerships:
                    if part.get("batter1_id") == p_id or part.get("batter2_id") == p_id:
                        if part.get("runs", 0) >= 50:
                            sit_imp += 5
                            
            # Death over wickets (last 3 overs of defending innings, under pressure)
            for inn in innings_list:
                if inn.batting_team_id != winner_id and inn.overs_limit > 3:
                    death_start_over = inn.overs_limit - 3
                    for d in inn.deliveries:
                        if d.get("bowler_id") == p_id and d.get("is_wicket") == 1 and d.get("over_number", 0) > death_start_over:
                            # Verify if chase was close
                            rem_runs = (target_runs or 0) - inn.total_runs
                            if rem_runs < 20:
                                sit_imp += 5
                                
        p_stat["situation_impact"] = min(15, sit_imp)

    # 8. Sum Total Impact
    for p_id, p_stat in impact_stats.items():
        p_stat["total_impact"] = (
            p_stat["batting_impact"] +
            p_stat["bowling_impact"] +
            p_stat["fielding_impact"] +
            p_stat["situation_impact"]
        )

    # 9. Perform Sorting & Rank Players
    all_players = list(impact_stats.values())
    all_players.sort(key=lambda x: x["total_impact"], reverse=True)

    # Compute Awards
    man_of_the_match = []
    best_batter = None
    best_bowler = None
    best_fielder = None

    # Filter players who actually contributed
    valid_batters = [p for p in all_players if p["batting_balls"] > 0]
    valid_bowlers = [p for p in all_players if p["bowling_balls"] > 0]
    valid_fielders = [p for p in all_players if (p["fielding_catches"] > 0 or p["fielding_stumpings"] > 0 or p["fielding_run_outs"] > 0)]

    # Best Batter Selection
    if valid_batters:
        valid_batters.sort(key=lambda x: (x["batting_impact"], x["batting_runs"], (x["batting_runs"] * 100.0 / x["batting_balls"] if x["batting_balls"] > 0 else 0)), reverse=True)
        best_batter = valid_batters[0]

    # Best Bowler Selection
    if valid_bowlers:
        valid_bowlers.sort(key=lambda x: (x["bowling_impact"], x["bowling_wickets"], -x["bowling_runs"]), reverse=True)
        best_bowler = valid_bowlers[0]

    # Best Fielder Selection
    if valid_fielders:
        valid_fielders.sort(key=lambda x: (x["fielding_impact"], x["fielding_catches"] + x["fielding_stumpings"] + x["fielding_run_outs"]), reverse=True)
        best_fielder = valid_fielders[0]

    # recommended MOTM
    if all_players and all_players[0]["total_impact"] > 0:
        top_player = all_players[0]
        tied_players = [top_player]
        
        # Find tied/near-tied players (within 1 point of top)
        for other in all_players[1:]:
            if top_player["total_impact"] - other["total_impact"] <= 1.0:
                tied_players.append(other)
            else:
                break
                
        # Resolve tie-breaker if multiple
        if len(tied_players) > 1:
            def tie_breaker_key(p):
                winning_weight = 10 if p["team_id"] == winner_id else 0
                max_contribution = max(p["batting_impact"], p["bowling_impact"])
                obj_stats = p["batting_runs"] + (p["bowling_wickets"] * 20)
                return (p["total_impact"], max_contribution, p["situation_impact"], winning_weight, obj_stats)
                
            tied_players.sort(key=tie_breaker_key, reverse=True)
            
            primary_winner = tied_players[0]
            man_of_the_match = [primary_winner]
            
            for runner_up in tied_players[1:]:
                if tie_breaker_key(primary_winner) == tie_breaker_key(runner_up):
                    man_of_the_match.append(runner_up)
                else:
                    break
        else:
            man_of_the_match = [top_player]

    # Generate explanations
    for motm in man_of_the_match:
        reasons = []
        if motm["batting_runs"] > 0:
            reasons.append(f"{motm['batting_runs']} runs")
        if motm["bowling_wickets"] > 0:
            reasons.append(f"{motm['bowling_wickets']} wickets")
        if motm["bowling_balls"] >= 6:
            econ = round(motm["bowling_runs"] * 6.0 / motm["bowling_balls"], 2)
            reasons.append(f"Economy {econ}")
        if motm["important_wickets"] > 0:
            reasons.append(f"Dismissed {motm['important_wickets']} key batter(s)")
        if motm["situation_impact"] > 5:
            if chase_innings and motm["team_id"] == chase_innings.batting_team_id:
                reasons.append("Strong chase performance")
            else:
                reasons.append("Defended total under pressure")
                
        motm["why"] = ", ".join(reasons) if reasons else "Consistent performance across all departments"

    return {
        "man_of_the_match": man_of_the_match,
        "best_batter": best_batter,
        "best_bowler": best_bowler,
        "best_fielder": best_fielder,
        "performance_table": all_players
    }
