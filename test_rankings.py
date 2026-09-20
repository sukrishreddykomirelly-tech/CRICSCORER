import unittest
import math
from unittest.mock import patch, MagicMock
from scoring import MatchState
from rankings import calculate_player_rankings, get_player_career_ranking_summary


class MockCursor:
    def __init__(self, players=None, teams=None, completed_matches=None, match_players=None):
        self.players = players or []
        self.teams = teams or []
        self.completed_matches = completed_matches or []
        self.match_players = match_players or {}  # match_id -> list of player_ids
        self._current_result = []

    def execute(self, query, params=None):
        q = query.strip().upper()
        if "FROM PLAYERS" in q:
            self._current_result = [
                {"id": p["id"], "name": p["name"], "avatar_url": p.get("avatar_url", ""), 
                 "batting_style": p.get("batting_style", ""), "bowling_style": p.get("bowling_style", ""),
                 "is_keeper": p.get("is_keeper", 0)}
                for p in self.players
            ]
        elif "FROM TEAM_PLAYERS" in q:
            self._current_result = []
        elif "FROM MATCHES" in q and "STATUS = 'COMPLETED'" in q:
            self._current_result = [
                {"id": m["id"], "match_date": m.get("match_date", "2026-09-20"), 
                 "match_time": "10:00", "match_format": "T20", "overs_limit": 20}
                for m in self.completed_matches
            ]
        elif "FROM MATCH_PLAYERS" in q:
            m_id = params[0] if params else 1
            p_ids = self.match_players.get(m_id, [])
            self._current_result = [{"player_id": pid} for pid in p_ids]
        else:
            self._current_result = []
        return self

    def fetchall(self):
        return list(self._current_result)

    def fetchone(self):
        return self._current_result[0] if self._current_result else None


class MockConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def close(self):
        pass


class TestPlayerRankingSystem(unittest.TestCase):
    def setUp(self):
        self.players = [
            {"id": 1, "name": "Player A", "batting_style": "Right-hand", "bowling_style": "Right-arm fast", "is_keeper": 0},
            {"id": 2, "name": "Player B", "batting_style": "Left-hand", "bowling_style": "Right-arm legbreak", "is_keeper": 0},
            {"id": 3, "name": "Player C", "batting_style": "Right-hand", "bowling_style": "None", "is_keeper": 1},
            {"id": 4, "name": "Player D", "batting_style": "Right-hand", "bowling_style": "Right-arm offbreak", "is_keeper": 0}
        ]

    def _create_mock_match(self, match_id, playing_xi, batter_stats=None, bowler_stats=None, fielder_stats=None):
        m = MatchState(match_id=match_id, team1_id=10, team2_id=20, match_format="T20", overs_limit=20, players_per_team=11)
        m.status = "completed"
        for p in self.players:
            m.add_player_name(p["id"], p["name"])
        
        m.start_innings(innings_id=match_id * 10 + 1, batting_team_id=10, bowling_team_id=20, innings_number=1)
        inn = m.innings[0]
        
        if batter_stats:
            for pid, bdata in batter_stats.items():
                inn.batting_scores[pid] = bdata
        if bowler_stats:
            for pid, bwdata in bowler_stats.items():
                inn.bowling_scores[pid] = bwdata
        if fielder_stats:
            for pid, fdata in fielder_stats.items():
                inn.fielding_scores[pid] = fdata
                
        return m

    # 1. One completed match -> rankings work
    def test_01_one_completed_match(self):
        m1 = self._create_mock_match(
            match_id=1,
            playing_xi=[1, 2],
            batter_stats={1: {"runs": 50, "balls": 30, "fours": 5, "sixes": 2, "status": "not_out"}}, # 50 + 9 + 10 + 8 (SR 166.7) = 77
            bowler_stats={2: {"balls": 24, "runs_conceded": 20, "wickets": 2, "maidens": 0}}
        )
        mock_cursor = MockCursor(
            players=self.players,
            completed_matches=[{"id": 1}],
            match_players={1: [1, 2]}
        )
        with patch("database.load_match_state", return_value=m1):
            rankings = calculate_player_rankings(conn=MockConnection(mock_cursor))
            self.assertEqual(rankings["total_completed_matches"], 1)
            self.assertEqual(rankings["min_participation"], 1)
            self.assertEqual(len(rankings["batsmen"]), 1)
            self.assertEqual(rankings["batsmen"][0]["player_id"], 1)
            # Batting average = 77, rating = 770
            self.assertEqual(rankings["batsmen"][0]["rating"], 770.0)

    # 2. Two completed matches -> rankings work
    def test_02_two_completed_matches(self):
        m1 = self._create_mock_match(1, [1, 2], batter_stats={1: {"runs": 40, "balls": 25, "fours": 4, "sixes": 1, "status": "out"}})
        m2 = self._create_mock_match(2, [1, 2], batter_stats={1: {"runs": 60, "balls": 35, "fours": 6, "sixes": 2, "status": "out"}})
        matches = {1: m1, 2: m2}
        mock_cursor = MockCursor(
            players=self.players,
            completed_matches=[{"id": 1}, {"id": 2}],
            match_players={1: [1, 2], 2: [1, 2]}
        )
        with patch("database.load_match_state", side_effect=lambda mid: matches[mid]):
            rankings = calculate_player_rankings(conn=MockConnection(mock_cursor))
            self.assertEqual(rankings["total_completed_matches"], 2)
            self.assertEqual(rankings["min_participation"], 1)
            self.assertEqual(rankings["batsmen"][0]["matches_batted"], 2)

    # 3. Three completed matches -> no 50% restriction (min participation = 1)
    def test_03_three_completed_matches_no_50_percent_restriction(self):
        m1 = self._create_mock_match(1, [1])
        m2 = self._create_mock_match(2, [1])
        m3 = self._create_mock_match(3, [2], batter_stats={2: {"runs": 30, "balls": 20, "fours": 3, "sixes": 0, "status": "out"}})
        matches = {1: m1, 2: m2, 3: m3}
        mock_cursor = MockCursor(
            players=self.players,
            completed_matches=[{"id": 1}, {"id": 2}, {"id": 3}],
            match_players={1: [1], 2: [1], 3: [2]}
        )
        with patch("database.load_match_state", side_effect=lambda mid: matches[mid]):
            rankings = calculate_player_rankings(conn=MockConnection(mock_cursor))
            self.assertEqual(rankings["total_completed_matches"], 3)
            self.assertEqual(rankings["min_participation"], 1)
            # Player 2 played only 1 of 3 matches, but since T=3, min_participation is 1, so Player 2 is eligible
            batsman_ids = [b["player_id"] for b in rankings["batsmen"]]
            self.assertIn(2, batsman_ids)

    # 4. Four completed matches -> 50% eligibility activates (min 2 participations)
    def test_04_four_completed_matches_50_percent_activates(self):
        m1 = self._create_mock_match(1, [1])
        m2 = self._create_mock_match(2, [1])
        m3 = self._create_mock_match(3, [1])
        # Player 2 only participates in Match 4 (1/4 = 25% < 50%)
        m4 = self._create_mock_match(4, [2], batter_stats={2: {"runs": 80, "balls": 40, "fours": 8, "sixes": 3, "status": "out"}})
        matches = {1: m1, 2: m2, 3: m3, 4: m4}
        mock_cursor = MockCursor(
            players=self.players,
            completed_matches=[{"id": 1}, {"id": 2}, {"id": 3}, {"id": 4}],
            match_players={1: [1], 2: [1], 3: [1], 4: [2]}
        )
        with patch("database.load_match_state", side_effect=lambda mid: matches[mid]):
            rankings = calculate_player_rankings(conn=MockConnection(mock_cursor))
            self.assertEqual(rankings["total_completed_matches"], 4)
            self.assertEqual(rankings["min_participation"], 2) # ceil(4 * 0.5) = 2
            # Player 2 has only 1 participation < 2, so excluded from rankings
            batsman_ids = [b["player_id"] for b in rankings["batsmen"]]
            self.assertNotIn(2, batsman_ids)

    # 5. Five completed matches -> minimum participation is 3 (ceil(5 * 0.5) = 3)
    def test_05_five_completed_matches_min_participation_is_3(self):
        m1 = self._create_mock_match(1, [1, 2], batter_stats={2: {"runs": 40, "balls": 20, "fours": 4, "sixes": 1, "status": "out"}})
        m2 = self._create_mock_match(2, [1, 2], batter_stats={2: {"runs": 40, "balls": 20, "fours": 4, "sixes": 1, "status": "out"}})
        m3 = self._create_mock_match(3, [1])
        m4 = self._create_mock_match(4, [1])
        m5 = self._create_mock_match(5, [1])
        matches = {1: m1, 2: m2, 3: m3, 4: m4, 5: m5}
        mock_cursor = MockCursor(
            players=self.players,
            completed_matches=[{"id": i} for i in range(1, 6)],
            match_players={1: [1, 2], 2: [1, 2], 3: [1], 4: [1], 5: [1]}
        )
        with patch("database.load_match_state", side_effect=lambda mid: matches[mid]):
            rankings = calculate_player_rankings(conn=MockConnection(mock_cursor))
            self.assertEqual(rankings["total_completed_matches"], 5)
            self.assertEqual(rankings["min_participation"], 3) # ceil(5 * 0.5) = 3
            # Player 2 has 2 participations < 3, so ineligible
            batsman_ids = [b["player_id"] for b in rankings["batsmen"]]
            self.assertNotIn(2, batsman_ids)

    # 6. Player participates in Playing XI but does not bat/bowl -> counts as participation
    def test_06_playing_xi_without_batting_counts_as_participation(self):
        # Player 3 in Playing XI for 2 matches out of 4, never bats or bowls
        m1 = self._create_mock_match(1, [1, 3], batter_stats={1: {"runs": 30, "balls": 20, "fours": 2, "sixes": 0, "status": "out"}})
        m2 = self._create_mock_match(2, [1, 3])
        m3 = self._create_mock_match(3, [1])
        m4 = self._create_mock_match(4, [1])
        matches = {1: m1, 2: m2, 3: m3, 4: m4}
        mock_cursor = MockCursor(
            players=self.players,
            completed_matches=[{"id": 1}, {"id": 2}, {"id": 3}, {"id": 4}],
            match_players={1: [1, 3], 2: [1, 3], 3: [1], 4: [1]}
        )
        with patch("database.load_match_state", side_effect=lambda mid: matches[mid]):
            rankings = calculate_player_rankings(conn=MockConnection(mock_cursor))
            # Player 3 has 2 participations in fielding, eligible under 50% rule (min 2)
            fielder_ids = [f["player_id"] for f in rankings["fielders"]]
            self.assertIn(3, fielder_ids)
            f3 = next(f for f in rankings["fielders"] if f["player_id"] == 3)
            self.assertEqual(f3["total_participations"], 2)
            self.assertEqual(f3["matches_fielded"], 2)

    # 7 & 8. Global inactivity across CricScorer & 2 consecutive non-participations = 5% penalty
    def test_07_and_08_global_inactivity_2_consecutive_matches_5_percent_penalty(self):
        # Player 1 participates in Match 1 (scores 50 runs, MVP 77 => Base Rating 770)
        # Match 2: Player 1 does not participate (streak = 1)
        # Match 3: Player 1 does not participate (streak = 2 -> 5% penalty)
        m1 = self._create_mock_match(1, [1], batter_stats={1: {"runs": 50, "balls": 30, "fours": 5, "sixes": 2, "status": "not_out"}})
        m2 = self._create_mock_match(2, [2])
        m3 = self._create_mock_match(3, [2])
        matches = {1: m1, 2: m2, 3: m3}
        mock_cursor = MockCursor(
            players=self.players,
            completed_matches=[{"id": 1}, {"id": 2}, {"id": 3}],
            match_players={1: [1], 2: [2], 3: [2]}
        )
        with patch("database.load_match_state", side_effect=lambda mid: matches[mid]):
            rankings = calculate_player_rankings(conn=MockConnection(mock_cursor))
            p1 = next(b for b in rankings["batsmen"] if b["player_id"] == 1)
            self.assertEqual(p1["inactivity_streak"], 2)
            self.assertTrue(p1["has_penalty"])
            self.assertEqual(p1["base_rating"], 770.0)
            # 770 * 0.95 = 731.5
            self.assertEqual(p1["rating"], 731.5)

    # 9. Participation after inactivity -> streak resets to 0 and rating returns to base
    def test_09_participation_after_inactivity_resets_streak(self):
        # Match 1: Player 1 plays
        # Match 2: Misses (streak 1)
        # Match 3: Misses (streak 2)
        # Match 4: Player 1 plays again (streak resets to 0)
        m1 = self._create_mock_match(1, [1], batter_stats={1: {"runs": 50, "balls": 30, "fours": 5, "sixes": 2, "status": "not_out"}}) # 77 pts
        m2 = self._create_mock_match(2, [2])
        m3 = self._create_mock_match(3, [2])
        m4 = self._create_mock_match(4, [1], batter_stats={1: {"runs": 50, "balls": 30, "fours": 5, "sixes": 2, "status": "not_out"}}) # 77 pts
        matches = {1: m1, 2: m2, 3: m3, 4: m4}
        mock_cursor = MockCursor(
            players=self.players,
            completed_matches=[{"id": 1}, {"id": 2}, {"id": 3}, {"id": 4}],
            match_players={1: [1], 2: [2], 3: [2], 4: [1]}
        )
        with patch("database.load_match_state", side_effect=lambda mid: matches[mid]):
            rankings = calculate_player_rankings(conn=MockConnection(mock_cursor))
            p1 = next(b for b in rankings["batsmen"] if b["player_id"] == 1)
            self.assertEqual(p1["inactivity_streak"], 0)
            self.assertFalse(p1["has_penalty"])
            self.assertEqual(p1["rating"], p1["base_rating"])
            self.assertEqual(p1["rating"], 770.0)

    # 10. Poor performance while participating -> no inactivity penalty
    def test_10_poor_performance_resets_inactivity(self):
        # Match 1: Player 1 plays
        # Match 2: Misses (streak 1)
        # Match 3: Plays but gets a duck (0 runs, 1 ball) -> streak resets to 0!
        m1 = self._create_mock_match(1, [1], batter_stats={1: {"runs": 50, "balls": 30, "fours": 5, "sixes": 2, "status": "not_out"}})
        m2 = self._create_mock_match(2, [2])
        m3 = self._create_mock_match(3, [1], batter_stats={1: {"runs": 0, "balls": 1, "fours": 0, "sixes": 0, "status": "out"}})
        matches = {1: m1, 2: m2, 3: m3}
        mock_cursor = MockCursor(
            players=self.players,
            completed_matches=[{"id": 1}, {"id": 2}, {"id": 3}],
            match_players={1: [1], 2: [2], 3: [1]}
        )
        with patch("database.load_match_state", side_effect=lambda mid: matches[mid]):
            rankings = calculate_player_rankings(conn=MockConnection(mock_cursor))
            p1 = next(b for b in rankings["batsmen"] if b["player_id"] == 1)
            self.assertEqual(p1["inactivity_streak"], 0)
            self.assertFalse(p1["has_penalty"])

    # 11, 12, 13. Independent ratings (Batting, Bowling, Fielding do not bleed into each other)
    def test_11_12_13_independent_categories(self):
        # Player 1 is an all-rounder: scores runs, takes wickets, takes catches
        m1 = self._create_mock_match(
            1, [1],
            batter_stats={1: {"runs": 100, "balls": 50, "fours": 10, "sixes": 4, "status": "not_out"}}, # Batting impact ~ 151
            bowler_stats={1: {"balls": 24, "runs_conceded": 10, "wickets": 3, "maidens": 1}},          # Bowling impact ~ 85
            fielder_stats={1: {"catches": 2, "stumpings": 0, "run_outs": 0}}                            # Fielding impact ~ 20
        )
        mock_cursor = MockCursor(
            players=self.players,
            completed_matches=[{"id": 1}],
            match_players={1: [1]}
        )
        with patch("database.load_match_state", return_value=m1):
            rankings = calculate_player_rankings(conn=MockConnection(mock_cursor))
            bat_p1 = rankings["batsmen"][0]
            bowl_p1 = rankings["bowlers"][0]
            field_p1 = rankings["fielders"][0]

            self.assertNotEqual(bat_p1["rating"], bowl_p1["rating"])
            self.assertNotEqual(bat_p1["rating"], field_p1["rating"])
            self.assertEqual(bat_p1["matches_batted"], 1)
            self.assertEqual(bowl_p1["matches_bowled"], 1)
            self.assertEqual(field_p1["matches_fielded"], 1)

    # 14. Zero-denominator safety
    def test_14_zero_denominator_safety(self):
        # Player 3 has no batting or bowling stats
        m1 = self._create_mock_match(1, [1, 3], batter_stats={1: {"runs": 20, "balls": 10, "fours": 2, "sixes": 0, "status": "not_out"}})
        mock_cursor = MockCursor(
            players=self.players,
            completed_matches=[{"id": 1}],
            match_players={1: [1, 3]}
        )
        with patch("database.load_match_state", return_value=m1):
            rankings = calculate_player_rankings(conn=MockConnection(mock_cursor))
            # Player 3 should NOT be in batsmen or bowlers ranking
            bat_ids = [b["player_id"] for b in rankings["batsmen"]]
            bowl_ids = [bw["player_id"] for bw in rankings["bowlers"]]
            self.assertNotIn(3, bat_ids)
            self.assertNotIn(3, bowl_ids)

    # 15. In-progress matches do not affect rankings
    def test_15_in_progress_matches_ignored(self):
        # Only completed matches returned by SQL status = 'completed'
        mock_cursor = MockCursor(
            players=self.players,
            completed_matches=[], # 0 completed matches even if live matches exist
            match_players={}
        )
        rankings = calculate_player_rankings(conn=MockConnection(mock_cursor))
        self.assertEqual(rankings["total_completed_matches"], 0)
        self.assertEqual(len(rankings["batsmen"]), 0)
        self.assertEqual(len(rankings["bowlers"]), 0)
        self.assertEqual(len(rankings["fielders"]), 0)

    # 16. Repeated recalculation does not compound penalty (Idempotency)
    def test_16_repeated_recalculation_does_not_compound_penalty(self):
        m1 = self._create_mock_match(1, [1], batter_stats={1: {"runs": 50, "balls": 30, "fours": 5, "sixes": 2, "status": "not_out"}})
        m2 = self._create_mock_match(2, [2])
        m3 = self._create_mock_match(3, [2])
        matches = {1: m1, 2: m2, 3: m3}
        mock_cursor = MockCursor(
            players=self.players,
            completed_matches=[{"id": 1}, {"id": 2}, {"id": 3}],
            match_players={1: [1], 2: [2], 3: [2]}
        )
        with patch("database.load_match_state", side_effect=lambda mid: matches[mid]):
            conn = MockConnection(mock_cursor)
            rankings1 = calculate_player_rankings(conn=conn)
            p1_calc1 = next(b for b in rankings1["batsmen"] if b["player_id"] == 1)
            
            rankings2 = calculate_player_rankings(conn=conn)
            p1_calc2 = next(b for b in rankings2["batsmen"] if b["player_id"] == 1)

            # Rating in calculation 1 and calculation 2 must be identical
            self.assertEqual(p1_calc1["rating"], p1_calc2["rating"])
            self.assertEqual(p1_calc1["base_rating"], p1_calc2["base_rating"])
    # 17. Explicit User Scenario 10: Global Inactivity Lifecycle
    def test_exact_scenario_10_global_inactivity(self):
        # Player A plays Match 1. Matches 2 & 3: Player A's team does not play -> streak = 2 -> 5% penalty.
        # Match 4: Player A participates -> streak = 0 -> rating returns to base.
        # Batting 60 runs, 30 balls, 6 fours, 2 sixes, not out -> 60 + 10 (boundaries) + 10 (milestone) + 8 (SR 200) = 88 pts -> 880 base rating
        m1 = self._create_mock_match(1, [1], batter_stats={1: {"runs": 60, "balls": 30, "fours": 6, "sixes": 2, "status": "not_out"}})
        m2 = self._create_mock_match(2, [2])
        m3 = self._create_mock_match(3, [2])
        
        matches_after_m3 = {1: m1, 2: m2, 3: m3}
        cursor_m3 = MockCursor(
            players=self.players,
            completed_matches=[{"id": 1}, {"id": 2}, {"id": 3}],
            match_players={1: [1], 2: [2], 3: [2]}
        )
        with patch("database.load_match_state", side_effect=lambda mid: matches_after_m3[mid]):
            rankings_m3 = calculate_player_rankings(conn=MockConnection(cursor_m3))
            p1_m3 = next(b for b in rankings_m3["batsmen"] if b["player_id"] == 1)
            self.assertEqual(p1_m3["inactivity_streak"], 2)
            self.assertTrue(p1_m3["has_penalty"])
            self.assertEqual(p1_m3["base_rating"], 880.0)
            self.assertEqual(p1_m3["rating"], 836.0) # 880 * 0.95 = 836.0

        # Now Match 4 occurs and Player A participates
        m4 = self._create_mock_match(4, [1], batter_stats={1: {"runs": 60, "balls": 30, "fours": 6, "sixes": 2, "status": "not_out"}})
        matches_after_m4 = {1: m1, 2: m2, 3: m3, 4: m4}
        cursor_m4 = MockCursor(
            players=self.players,
            completed_matches=[{"id": 1}, {"id": 2}, {"id": 3}, {"id": 4}],
            match_players={1: [1], 2: [2], 3: [2], 4: [1]}
        )
        with patch("database.load_match_state", side_effect=lambda mid: matches_after_m4[mid]):
            rankings_m4 = calculate_player_rankings(conn=MockConnection(cursor_m4))
            p1_m4 = next(b for b in rankings_m4["batsmen"] if b["player_id"] == 1)
            self.assertEqual(p1_m4["inactivity_streak"], 0)
            self.assertFalse(p1_m4["has_penalty"])
            self.assertEqual(p1_m4["base_rating"], 880.0)
            self.assertEqual(p1_m4["rating"], 880.0) # Streak reset, back to unpenalized base rating!

    # 18. Explicit User Scenario 11: Penalty Does Not Compound on Recalculation
    def test_exact_scenario_11_penalty_no_compounding(self):
        # Streak = 2 -> First calculation: 836.0. Second calculation: STILL 836.0 (NOT 794.2)
        m1 = self._create_mock_match(1, [1], batter_stats={1: {"runs": 60, "balls": 30, "fours": 6, "sixes": 2, "status": "not_out"}})
        m2 = self._create_mock_match(2, [2])
        m3 = self._create_mock_match(3, [2])
        matches = {1: m1, 2: m2, 3: m3}
        cursor = MockCursor(
            players=self.players,
            completed_matches=[{"id": 1}, {"id": 2}, {"id": 3}],
            match_players={1: [1], 2: [2], 3: [2]}
        )
        with patch("database.load_match_state", side_effect=lambda mid: matches[mid]):
            conn = MockConnection(cursor)
            res1 = calculate_player_rankings(conn=conn)
            p1_1 = next(b for b in res1["batsmen"] if b["player_id"] == 1)
            self.assertEqual(p1_1["rating"], 836.0)

            res2 = calculate_player_rankings(conn=conn)
            p1_2 = next(b for b in res2["batsmen"] if b["player_id"] == 1)
            self.assertEqual(p1_2["rating"], 836.0)
            self.assertNotEqual(p1_2["rating"], 794.2)


class TestRankingRoutes(unittest.TestCase):
    def setUp(self):
        from app import app
        self.app = app
        self.client = app.test_client()

    def test_rankings_page_route(self):
        with patch("database.get_player_rankings", return_value={
            "total_completed_matches": 1,
            "min_participation": 1,
            "batsmen": [{"player_id": 1, "name": "Kohli", "avatar_url": "", "batting_style": "RHB", "team_name": "Titans", "team_logo": "", "matches_batted": 1, "total_participations": 1, "total_points": 80.0, "average_points": 80.0, "base_rating": 800.0, "rating": 800.0, "inactivity_streak": 0, "has_penalty": False, "rank": 1}],
            "bowlers": [],
            "fielders": []
        }):
            resp = self.client.get("/rankings")
            self.assertEqual(resp.status_code, 200)
            self.assertIn(b"BEST BATSMEN", resp.data)
            self.assertIn(b"Kohli", resp.data)

    def test_api_rankings_route(self):
        with patch("database.get_player_rankings", return_value={
            "total_completed_matches": 1,
            "min_participation": 1,
            "batsmen": [{"player_id": 1, "name": "Kohli", "rating": 800.0, "rank": 1}],
            "bowlers": [],
            "fielders": []
        }):
            resp = self.client.get("/api/rankings")
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertTrue(data["success"])
            self.assertEqual(data["data"]["batsmen"][0]["rating"], 800.0)


if __name__ == "__main__":
    unittest.main()
