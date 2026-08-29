# test_scoring.py
import unittest
from scoring import MatchState, parse_overs

class TestScoringEngine(unittest.TestCase):
    def setUp(self):
        # Setup a dummy match: Team 1 (batting first) vs Team 2
        # Overs limit: 5 overs, 5 players per team (for testing compact ends)
        self.match = MatchState(match_id=1, team1_id=101, team2_id=102, match_format="T20", overs_limit=5, players_per_team=5)
        self.match.add_player_name(1, "Virat Kohli")
        self.match.add_player_name(2, "Rohit Sharma")
        self.match.add_player_name(3, "MS Dhoni")
        self.match.add_player_name(4, "Yuvraj Singh")
        self.match.add_player_name(5, "Hardik Pandya")
        
        self.match.add_player_name(11, "Jasprit Bumrah")
        self.match.add_player_name(12, "Rashid Khan")
        
        # Start Innings 1: Team 1 batting, Team 2 bowling
        self.match.start_innings(innings_id=1, batting_team_id=101, bowling_team_id=102, innings_number=1)
        self.innings = self.match.get_current_innings()
        
        # Set up crease
        self.innings.striker_id = 1
        self.innings.non_striker_id = 2
        self.innings.bowler_id = 11

    def test_basic_scoring_and_rotation(self):
        # Ball 1: Dot ball
        self.innings.apply_delivery({"runs_batter": 0, "is_legal": 1})
        self.assertEqual(self.innings.total_runs, 0)
        self.assertEqual(self.innings.balls_bowled, 1)
        self.assertEqual(self.innings.striker_id, 1) # Strike does not rotate
        self.assertEqual(self.innings.batting_scores[1]["runs"], 0)
        self.assertEqual(self.innings.batting_scores[1]["balls"], 1)
        
        # Ball 2: Single run (strike rotates)
        self.innings.apply_delivery({"runs_batter": 1, "is_legal": 1})
        self.assertEqual(self.innings.total_runs, 1)
        self.assertEqual(self.innings.balls_bowled, 2)
        self.assertEqual(self.innings.striker_id, 2) # Strike rotated!
        self.assertEqual(self.innings.non_striker_id, 1)
        self.assertEqual(self.innings.batting_scores[1]["runs"], 1)
        self.assertEqual(self.innings.batting_scores[1]["balls"], 2)
        self.assertEqual(self.innings.batting_scores[2]["runs"], 0)
        self.assertEqual(self.innings.batting_scores[2]["balls"], 0)

        # Ball 3: Boundary 4 by Rohit (no rotation)
        self.innings.apply_delivery({"runs_batter": 4, "is_legal": 1})
        self.assertEqual(self.innings.total_runs, 5)
        self.assertEqual(self.innings.striker_id, 2) # No rotation
        self.assertEqual(self.innings.batting_scores[2]["runs"], 4)
        self.assertEqual(self.innings.batting_scores[2]["fours"], 1)

    def test_over_completion_strike_rotation(self):
        # 6 legal balls
        self.innings.apply_delivery({"runs_batter": 0, "is_legal": 1}) # Ball 1 (striker: 1)
        self.innings.apply_delivery({"runs_batter": 0, "is_legal": 1}) # Ball 2
        self.innings.apply_delivery({"runs_batter": 0, "is_legal": 1}) # Ball 3
        self.innings.apply_delivery({"runs_batter": 0, "is_legal": 1}) # Ball 4
        self.innings.apply_delivery({"runs_batter": 0, "is_legal": 1}) # Ball 5
        self.assertEqual(self.innings.striker_id, 1)
        
        self.innings.apply_delivery({"runs_batter": 0, "is_legal": 1}) # Ball 6
        # End of over: Bowler is cleared, strike rotates
        self.assertEqual(self.innings.balls_bowled, 6)
        self.assertEqual(self.innings.striker_id, 2) # Rotated due to over end!
        self.assertEqual(self.innings.non_striker_id, 1)
        self.assertIsNone(self.innings.bowler_id) # Bowler cleared

    def test_wides(self):
        # Wide ball: 1 extra run, ball not counted in over
        self.innings.apply_delivery({"extra_type": "wide", "runs_extras": 0, "is_legal": 0})
        self.assertEqual(self.innings.total_runs, 1)
        self.assertEqual(self.innings.wides, 1)
        self.assertEqual(self.innings.balls_bowled, 0) # Over not progressed
        self.assertEqual(self.innings.striker_id, 1) # Striker did not change
        self.assertEqual(self.innings.batting_scores[1]["balls"], 0) # Batter faced 0 balls
        self.assertEqual(self.innings.bowling_scores[11]["runs_conceded"], 1)
        self.assertEqual(self.innings.bowling_scores[11]["wides"], 1)

        # Wide + 2 runs completed off the wide (total 3 wides on ball, so 4 total. No rotation since 2 runs completed is even)
        self.innings.apply_delivery({"extra_type": "wide", "runs_extras": 2, "is_legal": 0})
        self.assertEqual(self.innings.total_runs, 4)
        self.assertEqual(self.innings.wides, 4)
        self.assertEqual(self.innings.striker_id, 1) # Strike remains 1 since 2 runs run is even
        
        # Wide + 1 run completed (total 2 wides on ball, so 6 total. Strike rotates since 1 run completed is odd)
        self.innings.apply_delivery({"extra_type": "wide", "runs_extras": 1, "is_legal": 0})
        self.assertEqual(self.innings.total_runs, 6)
        self.assertEqual(self.innings.wides, 6)
        self.assertEqual(self.innings.striker_id, 2) # Rotates to 2 since 1 completed run is odd

    def test_noballs_t20_mode(self):
        # T20 Match No Ball: 1 extra run, striker faces, ball not progress over.
        # Next ball becomes Free Hit
        self.innings.apply_delivery({"extra_type": "noball", "runs_batter": 0, "is_legal": 0})
        self.assertEqual(self.innings.total_runs, 1)
        self.assertEqual(self.innings.noballs, 1)
        self.assertEqual(self.innings.balls_bowled, 0)
        self.assertEqual(self.innings.batting_scores[1]["balls"], 1) # Batter faced a ball!
        self.assertTrue(self.innings.free_hit) # Free hit activated
        self.assertEqual(self.innings.bowling_scores[11]["runs_conceded"], 1)
        
        # Free Hit ball: hits boundary 6. Free hit deactivated.
        self.innings.apply_delivery({"runs_batter": 6, "is_legal": 1})
        self.assertEqual(self.innings.total_runs, 7)
        self.assertFalse(self.innings.free_hit)
        self.assertEqual(self.innings.batting_scores[1]["runs"], 6)
        self.assertEqual(self.innings.batting_scores[1]["balls"], 2)
        self.assertEqual(self.innings.bowling_scores[11]["runs_conceded"], 7)

    def test_byes_and_legbyes(self):
        # 3 Byes: legal ball, not charged to bowler, batter faces but scores 0. Strike rotates (3 is odd).
        self.innings.apply_delivery({"extra_type": "bye", "runs_extras": 3, "is_legal": 1})
        self.assertEqual(self.innings.total_runs, 3)
        self.assertEqual(self.innings.byes, 3)
        self.assertEqual(self.innings.balls_bowled, 1)
        self.assertEqual(self.innings.batting_scores[1]["runs"], 0)
        self.assertEqual(self.innings.batting_scores[1]["balls"], 1)
        self.assertEqual(self.innings.bowling_scores[11]["runs_conceded"], 0) # Not charged to bowler!
        self.assertEqual(self.innings.striker_id, 2) # Strike rotated

        # 2 Leg Byes (striker is now player 2): legal ball, not charged, no strike rotation (2 is even)
        self.innings.apply_delivery({"extra_type": "legbye", "runs_extras": 2, "is_legal": 1})
        self.assertEqual(self.innings.total_runs, 5)
        self.assertEqual(self.innings.legbyes, 2)
        self.assertEqual(self.innings.balls_bowled, 2)
        self.assertEqual(self.innings.batting_scores[2]["runs"], 0)
        self.assertEqual(self.innings.batting_scores[2]["balls"], 1)
        self.assertEqual(self.innings.bowling_scores[11]["runs_conceded"], 0)
        self.assertEqual(self.innings.striker_id, 2)

    def test_dismissal_caught(self):
        # Bowler bowls. Striker (1) is caught by player 12 (Rashid Khan).
        # New batter (3: MS Dhoni) enters.
        self.innings.apply_delivery({
            "is_wicket": 1,
            "wicket_type": "caught",
            "player_dismissed_id": 1,
            "fielder_id": 12,
            "new_batter_id": 3,
            "is_legal": 1
        })
        self.assertEqual(self.innings.total_wickets, 1)
        self.assertEqual(self.innings.batting_scores[1]["status"], "out")
        self.assertEqual(self.innings.batting_scores[1]["dismissal_type"], "caught")
        self.assertEqual(self.innings.batting_scores[1]["fielder_id"], 12)
        self.assertEqual(self.innings.batting_scores[1]["dismissed_by"], 11)
        self.assertEqual(self.innings.bowling_scores[11]["wickets"], 1)
        self.assertEqual(self.innings.fielding_scores[12]["catches"], 1)
        
        # Verify strike placement under MCC 2022Caught rule (new batter comes to striker's end)
        self.assertEqual(self.innings.striker_id, 3) # MS Dhoni is striker
        self.assertEqual(self.innings.non_striker_id, 2) # Rohit remains at non-striker's end

    def test_dismissal_run_out(self):
        # Ball 1: Rohit (2) hits, completes 1 run, they cross for 2nd run, but Virat (1) is run out.
        # 1 run is completed.
        # Fielder involved: 12 (Rashid Khan)
        # New batter: 3 (MS Dhoni)
        self.innings.apply_delivery({
            "runs_batter": 1, # 1 completed run off the bat
            "is_wicket": 1,
            "wicket_type": "run_out",
            "player_dismissed_id": 1, # Virat is run out
            "fielder_id": 12,
            "new_batter_id": 3,
            "next_striker_id": 3, # Explicit strike selection
            "is_legal": 1
        })
        
        self.assertEqual(self.innings.total_runs, 1) # Completed run counted
        self.assertEqual(self.innings.total_wickets, 1)
        self.assertEqual(self.innings.batting_scores[1]["status"], "out")
        self.assertEqual(self.innings.batting_scores[1]["runs"], 1) # Virat got the 1 run before run out
        self.assertEqual(self.innings.bowling_scores[11]["wickets"], 0) # Bowler gets NO credit for run out
        self.assertEqual(self.innings.fielding_scores[12]["run_outs"], 1) # Fielder credited
        
        # Crease check
        self.assertEqual(self.innings.striker_id, 3) # MS Dhoni is striker
        self.assertEqual(self.innings.non_striker_id, 2) # Rohit is non-striker

    def test_maiden_over(self):
        # Bowler Jasprit Bumrah bowls a complete maiden over (6 dots)
        for _ in range(6):
            self.innings.apply_delivery({"runs_batter": 0, "is_legal": 1})
            
        self.assertEqual(self.innings.balls_bowled, 6)
        self.assertEqual(self.innings.bowling_scores[11]["runs_conceded"], 0)
        self.assertEqual(self.innings.bowling_scores[11]["maidens"], 1) # Maiden over!

        # Next over: Bowler Rashid Khan (12). Bowls 5 dots, but concedes a single. Not a maiden.
        self.innings.bowler_id = 12
        for _ in range(5):
            self.innings.apply_delivery({"runs_batter": 0, "is_legal": 1})
        self.innings.apply_delivery({"runs_batter": 1, "is_legal": 1})
        self.assertEqual(self.innings.bowling_scores[12]["maidens"], 0)

        # Third over: Bumrah bowls again. Bowls 5 dots, and 1 bye. 
        # Byes are not charged to bowler, so it should still count as a maiden!
        self.innings.bowler_id = 11
        for _ in range(5):
            self.innings.apply_delivery({"runs_batter": 0, "is_legal": 1})
        self.innings.apply_delivery({"extra_type": "bye", "runs_extras": 4, "is_legal": 1}) # 4 byes boundary
        self.assertEqual(self.innings.bowling_scores[11]["maidens"], 2) # Bumrah has 2 maidens!

    def test_innings_and_match_completion(self):
        # In a 5-player-per-team match, innings ends at 4 wickets down
        # Start Innings 1. Let's bowl out the team.
        self.innings.apply_delivery({"is_wicket": 1, "wicket_type": "bowled", "new_batter_id": 3, "is_legal": 1}) # 1 wicket
        self.innings.apply_delivery({"is_wicket": 1, "wicket_type": "bowled", "new_batter_id": 4, "is_legal": 1}) # 2 wickets
        self.innings.apply_delivery({"is_wicket": 1, "wicket_type": "bowled", "new_batter_id": 5, "is_legal": 1}) # 3 wickets
        
        # Current status should be live
        self.assertEqual(self.match.status, "live")
        
        # 4th Wicket (last wicket since players_per_team is 5)
        self.match.apply_delivery({"is_wicket": 1, "wicket_type": "bowled", "is_legal": 1})
        self.assertEqual(self.innings.status, "completed")
        self.assertEqual(self.innings.total_wickets, 4)
        
        # Total runs scored: 0. Target for Innings 2 is 1 run.
        # Now start Innings 2
        self.match.start_innings(innings_id=2, batting_team_id=102, bowling_team_id=101, innings_number=2)
        innings2 = self.match.get_current_innings()
        innings2.striker_id = 11
        innings2.non_striker_id = 12
        innings2.bowler_id = 1
        
        # Strike single run: target reached, match completed, Team 102 wins by 4 wickets
        self.match.apply_delivery({"runs_batter": 1, "is_legal": 1})
        self.assertEqual(self.match.status, "completed")
        self.assertEqual(self.match.winner_id, 102)
        self.assertEqual(self.match.result_margin, "won by 4 wickets")

    def test_single_batting_mode(self):
        # Setup a match with single batting enabled
        single_match = MatchState(match_id=2, team1_id=101, team2_id=102, match_format="T20", overs_limit=5, players_per_team=3, single_batting=True)
        single_match.add_player_name(1, "Player 1")
        single_match.add_player_name(2, "Player 2")
        single_match.add_player_name(3, "Player 3")
        
        single_match.start_innings(innings_id=10, batting_team_id=101, bowling_team_id=102, innings_number=1)
        inn = single_match.get_current_innings()
        inn.striker_id = 1
        inn.non_striker_id = 2
        inn.bowler_id = 11
        
        # 1. 1st Wicket falls -> Player 3 comes in
        inn.apply_delivery({"is_wicket": 1, "wicket_type": "bowled", "player_dismissed_id": 1, "new_batter_id": 3, "is_legal": 1})
        self.assertEqual(inn.total_wickets, 1)
        self.assertEqual(inn.striker_id, 3)
        self.assertEqual(inn.non_striker_id, 2)
        
        # 2. 2nd Wicket falls (Player 2 is out). Since single batting is enabled and players_per_team is 3, 
        # this is the 2nd wicket, meaning only 1 batter remains.
        # So Player 2 gets dismissed, and Player 3 is the sole batter.
        # Player 3 goes to striker end, non-striker becomes None, and innings does NOT end!
        inn.apply_delivery({"is_wicket": 1, "wicket_type": "bowled", "player_dismissed_id": 2, "is_legal": 1})
        self.assertEqual(inn.total_wickets, 2)
        self.assertEqual(inn.status, "ongoing") # Innings is still ongoing!
        self.assertEqual(inn.striker_id, 3) # Player 3 remains striker
        self.assertIsNone(inn.non_striker_id) # Non-striker is now None
        
        # 3. Strike rotation should be bypassed when batting alone
        # Score 1 run off a legal ball. Strike should NOT rotate (non-striker is None)
        inn.apply_delivery({"runs_batter": 1, "is_legal": 1})
        self.assertEqual(inn.total_runs, 1)
        self.assertEqual(inn.striker_id, 3)
        self.assertIsNone(inn.non_striker_id)
        
        # End of over. Strike should NOT rotate (non-striker is None)
        # Since 3 balls have been bowled (step 1, step 2, and the 1 run above),
        # we need 2 more balls, then the 6th over-completing ball.
        for _ in range(2):
            inn.apply_delivery({"runs_batter": 0, "is_legal": 1})
        # The 6th ball:
        inn.apply_delivery({"runs_batter": 0, "is_legal": 1})
        self.assertEqual(inn.balls_bowled, 6)
        self.assertEqual(inn.striker_id, 3) # Player 3 still striker!
        self.assertIsNone(inn.non_striker_id)
        
        # 4. 3rd Wicket falls (Player 3 is out). Now the team is completely out of batters.
        # The innings should end!
        single_match.apply_delivery({"is_wicket": 1, "wicket_type": "bowled", "player_dismissed_id": 3, "is_legal": 1})
        self.assertEqual(inn.total_wickets, 3)
        self.assertEqual(inn.status, "completed") # Innings completed!

    def test_substitutions(self):
        # Setup: Match has substitution where Player 4 replaces Player 1
        self.match.substitutions = [{"outgoing_id": 1, "incoming_id": 4}]
        self.innings.substitutions = self.match.substitutions
        
        # Player 1 gets out, and we try to bring in Player 4 as the incoming batsman.
        # Since Player 1 already batted and got out, Player 4 should be rejected by the engine.
        self.innings.apply_delivery({
            "is_wicket": 1,
            "wicket_type": "caught",
            "player_dismissed_id": 1,
            "new_batter_id": 4,
            "is_legal": 1
        })
        
        self.assertEqual(self.innings.total_wickets, 1)
        # Verify that striker is NOT Player 4 (he was rejected)
        self.assertNotEqual(self.innings.striker_id, 4)

if __name__ == "__main__":
    unittest.main()
