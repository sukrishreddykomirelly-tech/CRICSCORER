import unittest
from scoring import MatchState, InningsState
from awards import calculate_awards

class TestAwardsCalculation(unittest.TestCase):
    def setUp(self):
        # Create a mock match state
        self.match = MatchState(match_id=999, team1_id=1, team2_id=2, match_format="T20", overs_limit=20, players_per_team=11)
        self.match.add_player_name(101, "Batter Elite")
        self.match.add_player_name(102, "All Rounder")
        self.match.add_player_name(103, "Bowler Ace")
        self.match.add_player_name(104, "Fielder Star")
        self.match.add_player_name(201, "Opponent Star")
        
        # Start Innings 1 (Team 1 bat, Team 2 bowl)
        self.match.start_innings(innings_id=1, batting_team_id=1, bowling_team_id=2, innings_number=1)
        
    def test_batting_impact_milestones_and_sr(self):
        # Test batter scoring 72 runs from 45 balls with 8 fours and 2 sixes
        inn = self.match.innings[0]
        inn.batting_scores[101] = {
            "runs": 72,
            "balls": 45,
            "fours": 8,
            "sixes": 2,
            "status": "out",
            "dismissal_type": "caught",
            "fielder_id": 201,
            "bowler_id": 103
        }
        
        # Calculate awards
        awards = calculate_awards(self.match)
        perf = {p["id"]: p for p in awards["performance_table"]}
        
        # Batter Elite score verification:
        # Base runs = 72
        # Boundaries: 8*1 + 2*2 = 12
        # Milestone (50-74 runs) = 10
        # Strike Rate SR = (72*100)/45 = 160.0. Since SR >= 150 (and faced >= 10 balls), bonus = 8.
        # Total Batting Impact = 72 + 12 + 10 + 8 = 102.
        self.assertEqual(perf[101]["batting_impact"], 102)

    def test_bowling_impact_wickets_and_economy(self):
        inn = self.match.innings[0]
        inn.bowling_scores[103] = {
            "balls": 24,
            "runs_conceded": 22,
            "wickets": 4,
            "maidens": 0,
            "wides": 0,
            "noballs": 0
        }
        
        # Add 4 wicket deliveries to bowlers credit to verify haul and wickets points
        inn.deliveries = [
            {"bowler_id": 103, "is_wicket": 1, "player_dismissed_id": 201, "wicket_type": "bowled"},
            {"bowler_id": 103, "is_wicket": 1, "player_dismissed_id": 201, "wicket_type": "caught", "fielder_id": 104},
            {"bowler_id": 103, "is_wicket": 1, "player_dismissed_id": 201, "wicket_type": "lbw"},
            {"bowler_id": 103, "is_wicket": 1, "player_dismissed_id": 201, "wicket_type": "caught", "fielder_id": 104}
        ]
        
        awards = calculate_awards(self.match)
        perf = {p["id"]: p for p in awards["performance_table"]}
        
        # Bowler Ace score verification:
        # Wickets: 4 * 20 = 80
        # Economy: 22 runs from 24 balls = 5.50 economy. Econ 5.00-6.99 bonus = 6.
        # Wicket haul (4 wickets) = 15.
        # Total Bowling Impact = 80 + 6 + 15 = 101.
        self.assertEqual(perf[103]["bowling_impact"], 101)

    def test_fielding_impact_catches(self):
        inn = self.match.innings[0]
        inn.fielding_scores[104] = {
            "catches": 2,
            "stumpings": 0,
            "run_outs": 0
        }
        inn.deliveries = [
            {"bowler_id": 103, "is_wicket": 1, "player_dismissed_id": 201, "wicket_type": "caught", "fielder_id": 104},
            {"bowler_id": 103, "is_wicket": 1, "player_dismissed_id": 201, "wicket_type": "caught", "fielder_id": 104}
        ]
        
        awards = calculate_awards(self.match)
        perf = {p["id"]: p for p in awards["performance_table"]}
        
        # Catches: 2 normal catches = 20.
        self.assertEqual(perf[104]["fielding_impact"], 20)

if __name__ == "__main__":
    unittest.main()
