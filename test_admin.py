# test_admin.py
import unittest
import json
from app import app
import database
from database import get_db_connection
from admin import ensure_admin_table_seeded

class TestAdminPanel(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.config['SECRET_KEY'] = 'test-secret-key-2026'
        self.client = app.test_client()
        database.init_db()
        database.seed_db()
        ensure_admin_table_seeded()

    def _login(self, username="admin", password="admin123"):
        return self.client.post('/admin/login', data={
            'username': username,
            'password': password
        }, follow_redirects=True)

    def test_admin_auth_flow(self):
        # 1. Unauthenticated access should redirect to login
        res = self.client.get('/admin', follow_redirects=False)
        self.assertEqual(res.status_code, 302)
        self.assertIn('/admin/login', res.headers['Location'])

        # 2. Invalid credentials
        res = self._login(username="admin", password="wrongpassword")
        self.assertIn(b"Invalid admin username or password", res.data)

        # 3. Successful login
        res = self._login()
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"System Overview", res.data)

        # 4. Logout
        res = self.client.get('/admin/logout', follow_redirects=True)
        self.assertIn(b"logged out safely", res.data)

        # 5. Accessing dashboard after logout redirects to login
        res = self.client.get('/admin', follow_redirects=False)
        self.assertEqual(res.status_code, 302)

    def test_dashboard_metrics(self):
        self._login()
        res = self.client.get('/admin/dashboard')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Matches", res.data)
        self.assertIn(b"Players", res.data)
        self.assertIn(b"Teams", res.data)

    def test_player_crud(self):
        self._login()
        # 1. List players
        res = self.client.get('/admin/players')
        self.assertEqual(res.status_code, 200)

        # 2. Create player
        res = self.client.post('/admin/players/new', data={
            'name': 'Test Admin Player',
            'batting_style': 'Right-hand bat',
            'bowling_style': 'Right-arm fast',
            'is_keeper': '0',
            'avatar_url': ''
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Test Admin Player", res.data)

        # Find created player ID
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM players WHERE name = 'Test Admin Player'")
        player_id = cursor.fetchone()['id']
        conn.close()

        # 3. Edit player
        res = self.client.post(f'/admin/players/{player_id}/edit', data={
            'name': 'Test Admin Player Updated',
            'batting_style': 'Left-hand bat',
            'bowling_style': 'None',
            'is_keeper': '1',
            'avatar_url': ''
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Test Admin Player Updated", res.data)

        # 4. Delete player (has no match records)
        res = self.client.post(f'/admin/players/{player_id}/delete', follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"removed successfully", res.data)

    def test_team_crud(self):
        self._login()
        # 1. List teams
        res = self.client.get('/admin/teams')
        self.assertEqual(res.status_code, 200)

        # 2. Create team
        res = self.client.post('/admin/teams/new', data={
            'name': 'Stallions CC',
            'logo_url': ''
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Stallions CC", res.data)

        # Find team ID
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM teams WHERE name = 'Stallions CC'")
        team_id = cursor.fetchone()['id']
        conn.close()

        # 3. Edit team & squad
        res = self.client.post(f'/admin/teams/{team_id}/edit', data={
            'name': 'Stallions CC Updated',
            'logo_url': ''
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Stallions CC Updated", res.data)

        # 4. Delete team
        res = self.client.post(f'/admin/teams/{team_id}/delete', follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"removed successfully", res.data)

    def test_tournament_crud(self):
        self._login()
        # 1. List tournaments
        res = self.client.get('/admin/tournaments')
        self.assertEqual(res.status_code, 200)

        # 2. Create tournament
        res = self.client.post('/admin/tournaments/new', data={
            'name': 'Admin Super League',
            'win_points': '3',
            'tie_points': '1',
            'nr_points': '1'
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Admin Super League", res.data)

        # Find tournament ID
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM tournaments WHERE name = 'Admin Super League'")
        tourney_id = cursor.fetchone()['id']
        conn.close()

        # 3. View standings
        res = self.client.get(f'/admin/tournaments/{tourney_id}/standings')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Admin Super League", res.data)

        # 4. Delete tournament
        res = self.client.post(f'/admin/tournaments/{tourney_id}/delete', follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"deleted", res.data)

    def test_match_and_delivery_management(self):
        self._login()
        # 1. Matches list
        res = self.client.get('/admin/matches')
        self.assertEqual(res.status_code, 200)

        # Create a test match with innings and delivery
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM teams LIMIT 2")
        t_rows = cursor.fetchall()
        t1_id, t2_id = t_rows[0]['id'], t_rows[1]['id']

        cursor.execute("""
            INSERT INTO matches (team1_id, team2_id, match_format, overs_limit, ground, status)
            VALUES (?, ?, 'T20', 20, 'Test Ground', 'live')
        """, (t1_id, t2_id))
        match_id = cursor.lastrowid

        cursor.execute("""
            INSERT INTO innings (match_id, innings_number, batting_team_id, bowling_team_id, status)
            VALUES (?, 1, ?, ?, 'ongoing')
        """, (match_id, t1_id, t2_id))
        innings_id = cursor.lastrowid

        cursor.execute("SELECT id FROM players LIMIT 3")
        p_rows = cursor.fetchall()
        p1_id, p2_id, p3_id = p_rows[0]['id'], p_rows[1]['id'], p_rows[2]['id']

        cursor.execute("""
            INSERT INTO deliveries (
                innings_id, over_number, ball_of_over, delivery_count,
                striker_id, non_striker_id, bowler_id, runs_batter, runs_extras, is_legal
            ) VALUES (?, 1, 1, 1, ?, ?, ?, 4, 0, 1)
        """, (innings_id, p1_id, p2_id, p3_id))
        del_id = cursor.lastrowid
        conn.commit()
        conn.close()

        database.rebuild_and_cache_match_state(match_id)

        # 2. Match detail
        res = self.client.get(f'/admin/matches/{match_id}')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Test Ground", res.data)

        # 3. Deliveries inspector
        res = self.client.get(f'/admin/matches/{match_id}/deliveries')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Del #1", res.data)

        # 4. Edit delivery (change 4 to 6)
        res = self.client.post(f'/admin/deliveries/{del_id}/edit', data={
            'striker_id': p1_id,
            'non_striker_id': p2_id,
            'bowler_id': p3_id,
            'runs_batter': '6',
            'runs_extras': '0',
            'extra_type': 'None',
            'is_legal': '1',
            'commentary': 'Monster six over midwicket'
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        # Verify state rebuilt with 6 runs
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT total_runs FROM innings WHERE id = ?", (innings_id,))
        total_runs = cursor.fetchone()['total_runs']
        self.assertEqual(total_runs, 6)
        conn.close()

        # 5. Scorecard inspector
        res = self.client.get(f'/admin/matches/{match_id}/scorecard')
        self.assertEqual(res.status_code, 200)

        # 6. Delete delivery
        res = self.client.post(f'/admin/deliveries/{del_id}/delete', follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        # Verify total runs reverted to 0
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT total_runs FROM innings WHERE id = ?", (innings_id,))
        total_runs = cursor.fetchone()['total_runs']
        self.assertEqual(total_runs, 0)
        conn.close()

        # 6. Test Admin End Match action
        res = self.client.post(f'/admin/matches/{match_id}/end', follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM matches WHERE id = ?", (match_id,))
        m_status = cursor.fetchone()['status']
        self.assertEqual(m_status, 'completed')
        conn.close()

        # 7. Test API End Match endpoint
        res = self.client.post(f'/api/match/{match_id}/end_match', json={
            'outcome_type': 'custom',
            'winner_id': t1_id,
            'result_margin': 'Titans won by 10 runs'
        })
        self.assertEqual(res.status_code, 200)
        json_data = res.get_json()
        self.assertTrue(json_data['success'])
        self.assertEqual(json_data['status'], 'completed')

        # 8. Delete match
        res = self.client.post(f'/admin/matches/{match_id}/delete', follow_redirects=True)
        self.assertEqual(res.status_code, 200)

    def test_rankings_and_inactivity_admin(self):
        self._login()
        res = self.client.get('/admin/rankings')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Career Player Rankings", res.data)

        res = self.client.post('/admin/rankings/recalculate', follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"successfully recalculated", res.data)

        res = self.client.get('/admin/inactivity')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Inactivity", res.data)

    def test_data_health_and_backups(self):
        self._login()
        # Data health check
        res = self.client.get('/admin/data-health')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Diagnostic Test Suite", res.data)

        # Auto-heal
        res = self.client.post('/admin/data-health/heal', follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Auto-Heal complete", res.data)

        # Backups dashboard
        res = self.client.get('/admin/backups')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Database Table Inventory", res.data)

        # Export JSON backup
        res = self.client.get('/admin/backups/export')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.mimetype, 'application/json')
        data = json.loads(res.data.decode('utf-8'))
        self.assertEqual(data['application'], 'CricScorer')
        self.assertIn('players', data)
        self.assertIn('matches', data)

    def test_audit_logs_and_search(self):
        self._login()
        # Audit log list
        res = self.client.get('/admin/audit-log')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Administrative Audit Log", res.data)

        # Search
        res = self.client.get('/admin/search?q=Kohli')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Search Results", res.data)

if __name__ == '__main__':
    unittest.main()
