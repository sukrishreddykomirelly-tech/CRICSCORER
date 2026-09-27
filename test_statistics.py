# test_statistics.py
import unittest
import json
from app import app
import database
from database import get_db_connection
from admin import ensure_admin_table_seeded
import statistics as stats_service


class TestAdvancedStatistics(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.config['SECRET_KEY'] = 'test-secret-key-2026'
        self.client = app.test_client()
        database.init_db()
        database.seed_db()
        ensure_admin_table_seeded()
        self._setup_test_data()

    def _login(self, username="admin", password="admin123"):
        return self.client.post('/admin/login', data={
            'username': username,
            'password': password
        }, follow_redirects=True)

    def _setup_test_data(self):
        """Create structured completed matches and deliveries to test all statistics."""
        conn = get_db_connection()
        cursor = conn.cursor()

        # Clean cache and test tables
        cursor.execute("DELETE FROM admin_statistics_cache")
        cursor.execute("DELETE FROM deliveries")
        cursor.execute("DELETE FROM innings")
        cursor.execute("DELETE FROM match_players")
        cursor.execute("DELETE FROM matches")
        cursor.execute("DELETE FROM team_players")
        cursor.execute("DELETE FROM teams")
        cursor.execute("DELETE FROM players")

        # Create Players:
        # P1: Master Batter (High runs, 4s, 6s)
        # P2: Fast Striker (High SR, lower balls)
        # P3: Ace Bowler (High wickets, low economy)
        # P4: Star Fielder (Catches, run outs)
        # P5: All-Rounder (Moderate across)
        cursor.execute("INSERT INTO players (id, name, batting_style, bowling_style) VALUES (1, 'Virat Star', 'Right-hand bat', 'Right-arm medium')")
        cursor.execute("INSERT INTO players (id, name, batting_style, bowling_style) VALUES (2, 'Surya Blitz', 'Right-hand bat', 'Right-arm offbreak')")
        cursor.execute("INSERT INTO players (id, name, batting_style, bowling_style) VALUES (3, 'Jasprit Fire', 'Right-hand bat', 'Right-arm fast')")
        cursor.execute("INSERT INTO players (id, name, batting_style, bowling_style) VALUES (4, 'Jaddu Hawk', 'Left-hand bat', 'Slow left-arm orthodox')")
        cursor.execute("INSERT INTO players (id, name, batting_style, bowling_style) VALUES (5, 'Hardik Power', 'Right-hand bat', 'Right-arm fast-medium')")

        # Create Teams
        cursor.execute("INSERT INTO teams (id, name) VALUES (1, 'Alpha Warriors')")
        cursor.execute("INSERT INTO teams (id, name) VALUES (2, 'Beta Titans')")

        # Create Completed Match #1
        cursor.execute("""
            INSERT INTO matches (id, team1_id, team2_id, match_format, overs_limit, ground, match_date, status, winner_id)
            VALUES (1, 1, 2, 'T20', 20, 'Eden Gardens', '2026-09-01', 'completed', 1)
        """)
        cursor.execute("INSERT INTO match_players (match_id, team_id, player_id) VALUES (1, 1, 1), (1, 1, 2), (1, 1, 3), (1, 2, 4), (1, 2, 5)")

        # Match 1 - Innings 1 (Alpha Warriors batting, Beta Titans bowling)
        cursor.execute("INSERT INTO innings (id, match_id, innings_number, batting_team_id, bowling_team_id, status) VALUES (1, 1, 1, 1, 2, 'completed')")
        # P1 bats: 10 balls: 4, 6, 4, 1, 0, 4, 6, 2, 4, 1 = 32 runs (4 fours, 2 sixes)
        # Bowler P4 bowled 6 balls, conceded 16
        # Bowler P5 bowled 4 balls, conceded 16
        deliveries_inn1 = [
            (1, 1, 1, 1, 1, 2, 4, 4, 0, None, 1, 0, None, None, None, 0),
            (1, 1, 2, 2, 1, 2, 4, 6, 0, None, 1, 0, None, None, None, 0),
            (1, 1, 3, 3, 1, 2, 4, 4, 0, None, 1, 0, None, None, None, 0),
            (1, 1, 4, 4, 1, 2, 4, 1, 0, None, 1, 0, None, None, None, 0),
            (1, 1, 5, 5, 2, 1, 4, 0, 0, None, 1, 0, None, None, None, 0),
            (1, 1, 6, 6, 2, 1, 4, 4, 0, None, 1, 0, None, None, None, 0),
            # Over 2 by P5:
            (1, 2, 1, 7, 1, 2, 5, 4, 0, None, 1, 0, None, None, None, 0),
            (1, 2, 2, 8, 1, 2, 5, 6, 0, None, 1, 0, None, None, None, 0),
            (1, 2, 3, 9, 1, 2, 5, 2, 0, None, 1, 0, None, None, None, 0),
            (1, 2, 4, 10, 1, 2, 5, 4, 0, None, 1, 0, None, None, None, 0),
            # Wicket: P1 caught by P4 off P5
            (1, 2, 5, 11, 1, 2, 5, 0, 0, None, 1, 1, 'caught', 1, 4, 1),
            # Wicket: P2 run out by P4
            (1, 2, 6, 12, 2, 1, 5, 0, 0, None, 1, 1, 'run_out', 2, 4, 0),
        ]
        for d in deliveries_inn1:
            cursor.execute("""
                INSERT INTO deliveries (
                    innings_id, over_number, ball_of_over, delivery_count, striker_id, non_striker_id, bowler_id,
                    runs_batter, runs_extras, extra_type, is_legal, is_wicket, wicket_type, player_dismissed_id, fielder_id, is_bowler_wicket
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, d)

        # Match 1 - Innings 2 (Beta Titans batting, Alpha Warriors bowling)
        cursor.execute("INSERT INTO innings (id, match_id, innings_number, batting_team_id, bowling_team_id, status) VALUES (2, 1, 2, 2, 1, 'completed')")
        # Bowler P3 (Jasprit Fire) takes 3 wickets in 6 balls for 2 runs!
        deliveries_inn2 = [
            (2, 1, 1, 1, 4, 5, 3, 0, 0, None, 1, 0, None, None, None, 0),
            (2, 1, 2, 2, 4, 5, 3, 0, 0, None, 1, 1, 'bowled', 4, None, 1),
            (2, 1, 3, 3, 5, 4, 3, 1, 0, None, 1, 0, None, None, None, 0),
            (2, 1, 4, 4, 5, 4, 3, 0, 0, None, 1, 1, 'caught', 5, 1, 1), # P1 takes catch!
            (2, 1, 5, 5, 4, 5, 3, 1, 0, None, 1, 0, None, None, None, 0),
            (2, 1, 6, 6, 4, 5, 3, 0, 0, None, 1, 1, 'bowled', 4, None, 1),
        ]
        for d in deliveries_inn2:
            cursor.execute("""
                INSERT INTO deliveries (
                    innings_id, over_number, ball_of_over, delivery_count, striker_id, non_striker_id, bowler_id,
                    runs_batter, runs_extras, extra_type, is_legal, is_wicket, wicket_type, player_dismissed_id, fielder_id, is_bowler_wicket
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, d)

        # Create Live (Unfinished) Match #2 - should be EXCLUDED from stats!
        cursor.execute("""
            INSERT INTO matches (id, team1_id, team2_id, match_format, overs_limit, ground, match_date, status)
            VALUES (2, 1, 2, 'T20', 20, 'Wankhede', '2026-09-02', 'live')
        """)
        cursor.execute("INSERT INTO innings (id, match_id, innings_number, batting_team_id, bowling_team_id, status) VALUES (3, 2, 1, 1, 2, 'ongoing')")
        # P1 scores 100 in live match -> MUST NOT be in completed stats!
        cursor.execute("""
            INSERT INTO deliveries (innings_id, over_number, ball_of_over, delivery_count, striker_id, non_striker_id, bowler_id, runs_batter, is_legal)
            VALUES (3, 1, 1, 1, 1, 2, 3, 100, 1)
        """)

        conn.commit()
        conn.close()

    def test_completed_matches_count(self):
        count = stats_service.get_completed_matches_count()
        self.assertEqual(count, 1)  # Only Match 1 is completed

    def test_most_runs(self):
        results = stats_service.calculate_most_runs()
        self.assertTrue(len(results) > 0)
        # P1 should have 31 runs (4+6+4+1+4+6+2+4 = 31), not 131 (excluding live match)
        top_scorer = results[0]
        self.assertEqual(top_scorer['player_id'], 1)
        self.assertEqual(top_scorer['runs'], 31)
        self.assertEqual(top_scorer['fours'], 4)
        self.assertEqual(top_scorer['sixes'], 2)
        self.assertEqual(top_scorer['rank'], 1)

    def test_most_wickets_and_bbi(self):
        results = stats_service.calculate_most_wickets()
        self.assertTrue(len(results) > 0)
        top_bowler = results[0]
        self.assertEqual(top_bowler['player_id'], 3)  # Jasprit Fire
        self.assertEqual(top_bowler['wickets'], 3)
        self.assertEqual(top_bowler['runs_conceded'], 2)
        self.assertEqual(top_bowler['bbi'], "3/2")

    def test_best_strike_rate_with_threshold(self):
        # Min balls = 5 -> P1 qualifies (9 balls faced)
        results = stats_service.calculate_best_strike_rate(min_balls=5)
        self.assertTrue(len(results) > 0)
        self.assertEqual(results[0]['player_id'], 1)

        # Min balls = 20 -> No one qualifies (P1 only faced 9 balls in completed match)
        results_high = stats_service.calculate_best_strike_rate(min_balls=20)
        self.assertEqual(len(results_high), 0)

    def test_best_average_with_threshold(self):
        # Min matches = 1 -> P1 has 31 runs, 1 dismissal -> Avg = 31.0
        results = stats_service.calculate_best_average(min_matches=1)
        self.assertTrue(len(results) > 0)
        top = results[0]
        self.assertEqual(top['player_id'], 1)
        self.assertEqual(top['average'], 31.0)

        # Min matches = 5 -> No one qualifies
        results_5 = stats_service.calculate_best_average(min_matches=5)
        self.assertEqual(len(results_5), 0)

    def test_best_economy_with_threshold(self):
        # Min overs = 1.0 (6 balls) -> P3 (Jasprit) bowled 1 over for 2 runs (Econ 2.0)
        results = stats_service.calculate_best_economy(min_overs=1.0)
        self.assertTrue(len(results) > 0)
        top_econ = results[0]
        self.assertEqual(top_econ['player_id'], 3)
        self.assertEqual(top_econ['economy'], 2.0)
        self.assertEqual(top_econ['overs'], "1.0")

        # Min overs = 5.0 -> No one qualifies
        results_high = stats_service.calculate_best_economy(min_overs=5.0)
        self.assertEqual(len(results_high), 0)

    def test_fielding_catches_and_runouts(self):
        # Catches: P4 took 1 catch (P1), P1 took 1 catch (P5)
        catches_res = stats_service.calculate_most_catches()
        self.assertTrue(len(catches_res) > 0)
        self.assertTrue(any(r['catches'] >= 1 for r in catches_res))

        # Run-outs: P4 credited with 1 run-out (P2)
        runouts_res = stats_service.calculate_most_runouts()
        self.assertTrue(len(runouts_res) > 0)
        self.assertEqual(runouts_res[0]['player_id'], 4)
        self.assertEqual(runouts_res[0]['run_outs'], 1)

    def test_boundaries_sixes_fours(self):
        # Boundaries: P1 has 4 fours + 2 sixes = 6 boundaries
        bounds = stats_service.calculate_most_boundaries()
        self.assertTrue(len(bounds) > 0)
        self.assertEqual(bounds[0]['player_id'], 1)
        self.assertEqual(bounds[0]['total_boundaries'], 6)
        self.assertEqual(bounds[0]['fours'], 4)
        self.assertEqual(bounds[0]['sixes'], 2)

        # Sixes
        sixes = stats_service.calculate_most_sixes()
        self.assertEqual(sixes[0]['player_id'], 1)
        self.assertEqual(sixes[0]['sixes'], 2)

        # Fours
        fours = stats_service.calculate_most_fours()
        self.assertEqual(fours[0]['player_id'], 1)
        self.assertEqual(fours[0]['fours'], 4)

    def test_best_spell_and_best_innings(self):
        # Best Spell: P3 in Innings 2 (3/2)
        spells = stats_service.calculate_best_spell()
        self.assertTrue(len(spells) > 0)
        top_spell = spells[0]
        self.assertEqual(top_spell['player_id'], 3)
        self.assertEqual(top_spell['wickets'], 3)
        self.assertEqual(top_spell['runs'], 2)
        self.assertEqual(top_spell['figures'], "3/2")
        self.assertEqual(top_spell['match_id'], 1)

        # Best Innings: P1 in Innings 1 (31 runs off 9 balls)
        innings_res = stats_service.calculate_best_innings()
        self.assertTrue(len(innings_res) > 0)
        top_inn = innings_res[0]
        self.assertEqual(top_inn['player_id'], 1)
        self.assertEqual(top_inn['runs'], 31)
        self.assertEqual(top_inn['match_id'], 1)

    def test_caching_and_independent_calculation(self):
        # Initially, cache should be empty
        self.assertIsNone(stats_service.get_cached_statistic("most_runs"))
        self.assertIsNone(stats_service.get_cached_statistic("most_wickets"))

        # Calculate ONLY most_runs
        res = stats_service.calculate_statistic_by_key("most_runs")
        self.assertEqual(res['stat_key'], "most_runs")
        self.assertEqual(res['status'], "fresh")

        # Verify most_runs IS cached
        cached_runs = stats_service.get_cached_statistic("most_runs")
        self.assertIsNotNone(cached_runs)
        self.assertEqual(cached_runs['completed_matches_count'], 1)

        # Verify other statistics were NOT calculated or cached
        self.assertIsNone(stats_service.get_cached_statistic("most_wickets"))
        self.assertIsNone(stats_service.get_cached_statistic("most_catches"))

    def test_outdated_invalidation_on_new_completed_match(self):
        # 1. Calculate and cache most_runs when 1 completed match exists
        stats_service.calculate_statistic_by_key("most_runs")
        cached = stats_service.get_cached_statistic("most_runs")
        self.assertEqual(cached['completed_matches_count'], 1)

        # Check overview status -> should be 'fresh'
        overview = stats_service.get_all_statistics_overview()
        runs_meta = next(item for item in overview if item['key'] == 'most_runs')
        self.assertEqual(runs_meta['status'], 'fresh')

        # 2. Add a second completed match
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO matches (id, team1_id, team2_id, match_format, overs_limit, ground, match_date, status, winner_id)
            VALUES (3, 1, 2, 'T20', 20, 'Chepauk', '2026-09-03', 'completed', 2)
        """)
        conn.commit()
        conn.close()

        # 3. Check overview status again -> should now be marked 'outdated'
        overview_after = stats_service.get_all_statistics_overview()
        runs_meta_after = next(item for item in overview_after if item['key'] == 'most_runs')
        self.assertEqual(runs_meta_after['status'], 'outdated')
        self.assertEqual(runs_meta_after['status_label'], 'OUTDATED')

    def test_admin_routes_and_export(self):
        self._login()

        # 1. Statistics dashboard overview page
        res = self.client.get('/admin/statistics')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Advanced Statistics", res.data)
        self.assertIn(b"Most Runs", res.data)
        self.assertIn(b"Most Wickets", res.data)

        # 2. Statistic detail page
        res = self.client.get('/admin/statistics/most_runs')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Most Runs", res.data)

        # 3. Post calculate action
        res = self.client.post('/admin/statistics/calculate/most_runs', follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Virat Star", res.data)

        # 4. JSON API calculate
        res_json = self.client.post('/admin/statistics/calculate/most_runs', headers={'Accept': 'application/json'})
        self.assertEqual(res_json.status_code, 200)
        data = res_json.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['data']['stat_key'], 'most_runs')

        # 5. Export CSV
        res_csv = self.client.get('/admin/statistics/export/most_runs')
        self.assertEqual(res_csv.status_code, 200)
        self.assertEqual(res_csv.content_type, 'text/csv; charset=utf-8')
        self.assertIn(b"Virat Star", res_csv.data)
        self.assertIn(b"CricScorer Advanced Statistics", res_csv.data)


if __name__ == '__main__':
    unittest.main()
