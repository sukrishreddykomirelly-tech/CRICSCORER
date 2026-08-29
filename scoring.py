# scoring.py
"""
CricScorer Cricket Scoring Engine
Compliant with MCC Laws of Cricket (including 2022 Updates) and ICC Playing Conditions.
"""

class MatchState:
    def __init__(self, match_id, team1_id, team2_id, match_format="T20", overs_limit=20, players_per_team=11, single_batting=False):
        self.match_id = match_id
        self.team1_id = team1_id
        self.team2_id = team2_id
        self.match_format = match_format
        self.overs_limit = overs_limit
        self.players_per_team = players_per_team
        self.single_batting = single_batting
        self.substitutions = []
        
        # Match overall state
        self.status = "scheduled"  # scheduled, toss_done, live, completed, abandoned
        self.toss_winner_id = None
        self.toss_decision = None  # bat, bowl
        self.winner_id = None
        self.result_margin = None
        self.is_super_over = 0
        
        # Team mappings (player rosters)
        # player_id -> name
        self.player_names = {}
        
        # Active Innings (max 2 for limited overs)
        self.innings = []
        self.current_innings_idx = -1  # 0 or 1
        
    def add_player_name(self, player_id, name):
        self.player_names[player_id] = name

    def start_innings(self, innings_id, batting_team_id, bowling_team_id, innings_number):
        innings = InningsState(innings_id, batting_team_id, bowling_team_id, innings_number, self.overs_limit, self.players_per_team, self.match_format, self.single_batting)
        innings.substitutions = self.substitutions
        self.innings.append(innings)
        self.current_innings_idx = len(self.innings) - 1
        self.status = "live"
        
    def get_current_innings(self):
        if 0 <= self.current_innings_idx < len(self.innings):
            return self.innings[self.current_innings_idx]
        return None

    def apply_delivery(self, d):
        """
        Applies a delivery dictionary to the current innings.
        d contains:
          - runs_batter (int)
          - runs_extras (int)
          - extra_type (str: 'wide', 'noball', 'bye', 'legbye' or None)
          - is_legal (int: 1 or 0)
          - is_wicket (int: 1 or 0)
          - wicket_type (str: 'bowled', 'caught', 'lbw', 'run_out', 'stumped', 'hit_wicket', 'retired_out', 'retired_hurt', 'obstructing_field' or None)
          - player_dismissed_id (int or None)
          - fielder_id (int or None)
          - new_batter_id (int or None)
          - next_striker_id (int or None) - explicitly override striker for next ball if run-out or similar
        """
        innings = self.get_current_innings()
        if not innings:
            return
        
        # If match is already completed, do not apply
        if self.status == "completed":
            return
            
        # Determine target if 2nd innings
        target = None
        if len(self.innings) == 2 and self.current_innings_idx == 1:
            target = self.innings[0].total_runs + 1
            innings.target = target
            
        innings.apply_delivery(d)
        
        # Check Innings / Match transitions
        # Innings ends if:
        # 1. Wickets down == players_per_team (or players_per_team - 1 if single_batting disabled)
        # 2. Overs limit reached (balls_bowled == overs_limit * 6)
        # 3. Innings 2 passed target
        innings_ended = False
        
        all_out_wickets = self.players_per_team if self.single_batting else (self.players_per_team - 1)
        
        # Check target reached
        if target is not None and innings.total_runs >= target:
            innings_ended = True
            self.status = "completed"
            self.winner_id = innings.batting_team_id
            wickets_left = all_out_wickets - innings.total_wickets
            self.result_margin = f"won by {wickets_left} wickets"
            
        elif innings.total_wickets >= all_out_wickets:
            innings_ended = True
            
        elif innings.balls_bowled >= self.overs_limit * 6:
            innings_ended = True
            
        if innings_ended:
            innings.status = "completed"
            if self.current_innings_idx == 0:
                # Innings 1 ended, match remains live but waiting for 2nd innings
                pass
            elif self.current_innings_idx == 1:
                # Innings 2 ended, determine winner if not already set (e.g. because of overs/wickets)
                self.status = "completed"
                if innings.total_runs >= target: # Should be handled already
                    self.winner_id = innings.batting_team_id
                    wickets_left = all_out_wickets - innings.total_wickets
                    self.result_margin = f"won by {wickets_left} wickets"
                elif innings.total_runs < target - 1:
                    self.winner_id = innings.bowling_team_id
                    runs_margin = (target - 1) - innings.total_runs
                    self.result_margin = f"won by {runs_margin} runs"
                else:
                    # Score is exactly target - 1 (Tied)
                    self.winner_id = None
                    self.result_margin = "match tied"


class InningsState:
    def __init__(self, innings_id, batting_team_id, bowling_team_id, innings_number, overs_limit, players_per_team, match_format, single_batting=False):
        self.innings_id = innings_id
        self.batting_team_id = batting_team_id
        self.bowling_team_id = bowling_team_id
        self.innings_number = innings_number
        self.overs_limit = overs_limit
        self.players_per_team = players_per_team
        self.match_format = match_format
        self.single_batting = single_batting
        self.substitutions = []
        
        # Running Innings Score
        self.total_runs = 0
        self.total_wickets = 0
        self.balls_bowled = 0  # Legal deliveries
        self.wides = 0
        self.noballs = 0
        self.byes = 0
        self.legbyes = 0
        self.status = "ongoing"
        self.target = None
        
        # Batter & Bowler Crease State
        self.striker_id = None
        self.non_striker_id = None
        self.bowler_id = None
        
        # Free Hit State
        self.free_hit = False
        
        # Performance Tracking during Replay
        # player_id -> dict
        self.batting_scores = {}
        self.bowling_scores = {}
        self.fielding_scores = {}
        
        # Partnerships list
        self.partnerships = []
        self.current_partnership = None  # {batter1, batter2, runs, balls}
        
        # Fall of Wickets list
        # {wicket_num, score, overs, batsman_id, bowler_id}
        self.fall_of_wickets = []
        
        # Over histories for bowler maiden calculations
        # bowler_id -> { over_number -> { legal_balls, runs_charged, has_illegal_ball } }
        self.bowler_overs_data = {}
        
        # Delivery log
        self.deliveries = []
        
    def init_batter(self, player_id):
        if player_id not in self.batting_scores:
            self.batting_scores[player_id] = {
                "player_id": player_id,
                "runs": 0,
                "balls": 0,
                "fours": 0,
                "sixes": 0,
                "status": "yet_to_bat",  # yet_to_bat, batting, out, not_out, retired_hurt
                "dismissal_type": None,
                "fielder_id": None,
                "bowler_id": None,
                "dismissed_by": None
            }
            
    def init_bowler(self, player_id):
        if player_id not in self.bowling_scores:
            self.bowling_scores[player_id] = {
                "player_id": player_id,
                "balls": 0,
                "runs_conceded": 0,
                "wickets": 0,
                "maidens": 0,
                "wides": 0,
                "noballs": 0
            }
        if player_id not in self.bowler_overs_data:
            self.bowler_overs_data[player_id] = {}

    def init_fielder(self, player_id):
        if player_id not in self.fielding_scores:
            self.fielding_scores[player_id] = {
                "player_id": player_id,
                "catches": 0,
                "stumpings": 0,
                "run_outs": 0
            }

    def start_partnership(self, b1, b2):
        self.current_partnership = {
            "batter1_id": b1,
            "batter2_id": b2,
            "runs": 0,
            "balls": 0,
            "active": True
        }
        self.partnerships.append(self.current_partnership)

    def update_partnership(self, runs, is_legal_ball):
        if self.current_partnership:
            self.current_partnership["runs"] += runs
            if is_legal_ball:
                self.current_partnership["balls"] += 1

    def end_partnership(self):
        if self.current_partnership:
            self.current_partnership["active"] = False
            self.current_partnership = None

    def apply_delivery(self, d):
        # Read fields
        runs_batter = d.get("runs_batter", 0)
        runs_extras = d.get("runs_extras", 0)
        extra_type = d.get("extra_type")
        is_legal = d.get("is_legal", 1)
        is_wicket = d.get("is_wicket", 0)
        wicket_type = d.get("wicket_type")
        player_dismissed_id = d.get("player_dismissed_id")
        fielder_id = d.get("fielder_id")
        new_batter_id = d.get("new_batter_id")
        next_striker_id = d.get("next_striker_id")
        
        # Ensure crease players are registered in stats
        if self.striker_id:
            self.init_batter(self.striker_id)
            self.batting_scores[self.striker_id]["status"] = "batting"
        if self.non_striker_id:
            self.init_batter(self.non_striker_id)
            self.batting_scores[self.non_striker_id]["status"] = "batting"
        if self.bowler_id:
            self.init_bowler(self.bowler_id)
            
        # Set up partnership if not exists
        if not self.current_partnership and self.striker_id and self.non_striker_id:
            self.start_partnership(self.striker_id, self.non_striker_id)
            
        # Determine over number
        current_over_number = (self.balls_bowled // 6) + 1
        
        # Initialize bowler over data tracking for maiden check
        if self.bowler_id:
            if current_over_number not in self.bowler_overs_data[self.bowler_id]:
                self.bowler_overs_data[self.bowler_id][current_over_number] = {
                    "legal_balls": 0,
                    "runs_charged": 0,
                    "has_illegal_ball": False
                }
            over_tracker = self.bowler_overs_data[self.bowler_id][current_over_number]
        else:
            over_tracker = None

        # --- SCORING CALCULATION ---
        runs_scored_on_ball = 0
        bowler_runs_on_ball = 0
        
        if extra_type == "wide":
            # 1 wide penalty + additional runs run off wide
            wide_runs = 1 + runs_extras
            self.wides += wide_runs
            runs_scored_on_ball = wide_runs
            bowler_runs_on_ball = wide_runs
            
            # Wides are charged to bowler wide count
            if self.bowler_id:
                self.bowling_scores[self.bowler_id]["wides"] += wide_runs
                
            if over_tracker:
                over_tracker["has_illegal_ball"] = True
                
        elif extra_type == "noball":
            # 1 noball penalty
            self.noballs += 1
            runs_scored_on_ball = 1
            bowler_runs_on_ball = 1
            
            if self.bowler_id:
                self.bowling_scores[self.bowler_id]["noballs"] += 1
                
            # Batters can score runs off bat
            if runs_batter > 0:
                runs_scored_on_ball += runs_batter
                bowler_runs_on_ball += runs_batter
                if self.striker_id:
                    self.batting_scores[self.striker_id]["runs"] += runs_batter
                    self.batting_scores[self.striker_id]["balls"] += 1
                    if runs_batter == 4:
                        self.batting_scores[self.striker_id]["fours"] += 1
                    elif runs_batter == 6:
                        self.batting_scores[self.striker_id]["sixes"] += 1
                        
            # Or they can run byes/legbyes on No Ball
            elif runs_extras > 0:
                # ICC limited overs rules score these as No-ball extras
                # MCC Standard rules score these as Byes/Legbyes
                if self.match_format in ["T20", "T20I", "ODI"]:
                    self.noballs += runs_extras
                    runs_scored_on_ball += runs_extras
                    bowler_runs_on_ball += runs_extras  # Charged to bowler under ICC
                else:
                    # Score as byes/legbyes
                    self.byes += runs_extras  # Default to byes for recreational
                    runs_scored_on_ball += runs_extras
                    
                if self.striker_id:
                    self.batting_scores[self.striker_id]["balls"] += 1 # Faces ball on No Ball
                    
            else:
                # Just the penalty
                if self.striker_id:
                    self.batting_scores[self.striker_id]["balls"] += 1
                    
            if over_tracker:
                over_tracker["has_illegal_ball"] = True
                
        elif extra_type == "bye":
            # Legal ball, byes added to extras, not charged to bowler
            self.byes += runs_extras
            runs_scored_on_ball = runs_extras
            
            # Batter faces ball, but gets no runs
            if self.striker_id:
                self.batting_scores[self.striker_id]["balls"] += 1
                
            if self.bowler_id:
                self.bowling_scores[self.bowler_id]["balls"] += 1
                
            if over_tracker:
                over_tracker["legal_balls"] += 1
                
        elif extra_type == "legbye":
            # Legal ball, leg byes added to extras, not charged to bowler
            self.legbyes += runs_extras
            runs_scored_on_ball = runs_extras
            
            if self.striker_id:
                self.batting_scores[self.striker_id]["balls"] += 1
                
            if self.bowler_id:
                self.bowling_scores[self.bowler_id]["balls"] += 1
                
            if over_tracker:
                over_tracker["legal_balls"] += 1
                
        else:
            # Standard legal delivery with batter runs (or dots)
            runs_scored_on_ball = runs_batter
            bowler_runs_on_ball = runs_batter
            
            if self.striker_id:
                self.batting_scores[self.striker_id]["runs"] += runs_batter
                self.batting_scores[self.striker_id]["balls"] += 1
                if runs_batter == 4:
                    self.batting_scores[self.striker_id]["fours"] += 1
                elif runs_batter == 6:
                    self.batting_scores[self.striker_id]["sixes"] += 1
                    
            if self.bowler_id:
                self.bowling_scores[self.bowler_id]["balls"] += 1
                
            if over_tracker:
                over_tracker["legal_balls"] += 1
                over_tracker["runs_charged"] += runs_batter

        # Update running score & partnership
        self.total_runs += runs_scored_on_ball
        self.update_partnership(runs_scored_on_ball, is_legal)
        
        if self.bowler_id:
            self.bowling_scores[self.bowler_id]["runs_conceded"] += bowler_runs_on_ball
            if over_tracker:
                over_tracker["runs_charged"] += bowler_runs_on_ball

        # --- WICKET HANDLING ---
        wicket_occurred = False
        striker_dismissed = False
        non_striker_dismissed = False
        
        if is_wicket:
            self.total_wickets += 1
            wicket_occurred = True
            
            # Identify dismissed player
            # Default to striker for standard dismissals
            is_bowler_credited = False
            if wicket_type in ["bowled", "caught", "lbw", "stumped", "hit_wicket"]:
                is_bowler_credited = True
                
            # If player dismissed is not explicitly set, default to striker
            if not player_dismissed_id:
                player_dismissed_id = self.striker_id
                
            if player_dismissed_id == self.striker_id:
                striker_dismissed = True
            elif player_dismissed_id == self.non_striker_id:
                non_striker_dismissed = True
                
            # Apply batting stats for dismissed player
            self.init_batter(player_dismissed_id)
            self.batting_scores[player_dismissed_id]["status"] = "out"
            self.batting_scores[player_dismissed_id]["dismissal_type"] = wicket_type
            self.batting_scores[player_dismissed_id]["fielder_id"] = fielder_id
            self.batting_scores[player_dismissed_id]["bowler_id"] = self.bowler_id if is_bowler_credited else None
            self.batting_scores[player_dismissed_id]["dismissed_by"] = self.bowler_id
            
            # Apply bowling wickets credit
            if is_bowler_credited and self.bowler_id:
                self.bowling_scores[self.bowler_id]["wickets"] += 1
                
            # Apply fielding stats
            if fielder_id:
                self.init_fielder(fielder_id)
                if wicket_type == "caught":
                    self.fielding_scores[fielder_id]["catches"] += 1
                elif wicket_type == "stumped":
                    self.fielding_scores[fielder_id]["stumpings"] += 1
                elif wicket_type == "run_out":
                    self.fielding_scores[fielder_id]["run_outs"] += 1
                    
            # Fall of wickets tracking
            overs_str = f"{(self.balls_bowled // 6)}.{self.balls_bowled % 6}"
            self.fall_of_wickets.append({
                "wicket_num": self.total_wickets,
                "score": self.total_runs,
                "overs": overs_str,
                "batsman_id": player_dismissed_id,
                "bowler_id": self.bowler_id
            })
            
            # End partnership
            self.end_partnership()

        # --- STRIKE ROTATION & ENDS ---
        if is_legal:
            self.balls_bowled += 1
            
        # Determine strike rotation
        rotate_strike = False
        
        runs_for_rotation = 0
        if extra_type in ["bye", "legbye", "wide"]:
            runs_for_rotation = runs_extras
        else:
            runs_for_rotation = runs_batter
            
        if runs_for_rotation in [1, 3, 5]:
            rotate_strike = True
            
        if rotate_strike and self.non_striker_id is not None:
            self.striker_id, self.non_striker_id = self.non_striker_id, self.striker_id

        # Wicket replacement
        if wicket_occurred:
            # Determine which batter is non-dismissed
            if player_dismissed_id == self.striker_id:
                non_dismissed_batter = self.non_striker_id
                self.striker_id = None
                striker_was_dismissed = True
            else:
                non_dismissed_batter = self.striker_id
                self.non_striker_id = None
                striker_was_dismissed = False
                
            # Place new batter
            if new_batter_id:
                # Check if new_batter_id is a substitute for a player who already batted in this innings
                is_eligible = True
                for sub in getattr(self, 'substitutions', []):
                    if sub['incoming_id'] == new_batter_id:
                        out_id = sub['outgoing_id']
                        if out_id in self.batting_scores and self.batting_scores[out_id]['status'] in ['out', 'batting', 'retired_hurt']:
                            is_eligible = False
                            break
                
                if is_eligible:
                    self.init_batter(new_batter_id)
                    self.batting_scores[new_batter_id]["status"] = "batting"
                    
                    if next_striker_id:
                        if next_striker_id == new_batter_id:
                            self.striker_id = new_batter_id
                            self.non_striker_id = non_dismissed_batter
                        else:
                            self.striker_id = non_dismissed_batter
                            self.non_striker_id = new_batter_id
                    else:
                        if wicket_type == "run_out":
                            if striker_was_dismissed:
                                self.striker_id = new_batter_id
                                self.non_striker_id = non_dismissed_batter
                            else:
                                self.striker_id = non_dismissed_batter
                                self.non_striker_id = new_batter_id
                        else:
                            # Caught, Bowled, LBW, Stumped, etc. -> new batter takes strike
                            self.striker_id = new_batter_id
                            self.non_striker_id = non_dismissed_batter
                else:
                    new_batter_id = None
            else:
                # No new batter (e.g. because we are all-out, or because last batsman bats alone)
                if self.single_batting and self.total_wickets == self.players_per_team - 1:
                    self.striker_id = non_dismissed_batter
                    self.non_striker_id = None

        # Retired Hurt replacement
        if wicket_type == "retired_hurt" and player_dismissed_id:
            self.batting_scores[player_dismissed_id]["status"] = "retired_hurt"
            if striker_dismissed:
                self.striker_id = None
            elif non_striker_dismissed:
                self.non_striker_id = None
                
            if new_batter_id:
                self.init_batter(new_batter_id)
                self.batting_scores[new_batter_id]["status"] = "batting"
                if striker_dismissed:
                    self.striker_id = new_batter_id
                else:
                    self.non_striker_id = new_batter_id

        # Over completion
        if is_legal and self.balls_bowled % 6 == 0 and self.balls_bowled > 0:
            if self.bowler_id and over_tracker:
                if (over_tracker["legal_balls"] == 6 and 
                    over_tracker["runs_charged"] == 0 and 
                    not over_tracker["has_illegal_ball"]):
                    self.bowling_scores[self.bowler_id]["maidens"] += 1
            
            # Strike rotates at end of over (only if we have a non-striker!)
            if self.non_striker_id is not None:
                self.striker_id, self.non_striker_id = self.non_striker_id, self.striker_id
            self.bowler_id = None

        # Free Hit State
        if self.match_format in ["T20", "T20I", "ODI"]:
            if extra_type == "noball":
                self.free_hit = True
            elif is_legal:
                self.free_hit = False
        else:
            self.free_hit = False

        self.deliveries.append(d)


def parse_overs(balls):
    return f"{balls // 6}.{balls % 6}"

def parse_overs_float(balls):
    return balls / 6.0
