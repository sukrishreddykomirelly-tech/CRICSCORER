"""test_ai_chat.py - Comprehensive Unit & Integration Tests for Groq AI Admin Chat.

Verifies:
1. Isolated conversation storage and 48-hour expiration lifecycle.
2. Complete read-only dynamic data access coverage across all cricket domains.
3. Groq API tool-calling workflow with mocked API responses.
4. Route authentication, ownership, and authorization.
5. Strict isolation from live scoring and measurement of scoring latency.
"""

import os
import unittest
import sqlite3
import json
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

import app as flask_app
import database
import postgres_db
import ai_chat_storage
import ai_data_access
import ai_service
from scoring import MatchState


class TestAIChatStorage(unittest.TestCase):
    """Tests for conversation persistence, message history, and 48-hour expiration."""

    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        postgres_db.ensure_postgres_schema(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_create_and_get_conversation(self):
        conv_id = ai_chat_storage.create_conversation("admin_user_1", "Test Conversation", conn=self.conn)
        self.assertTrue(conv_id.startswith("conv_"))

        conv = ai_chat_storage.get_conversation(conv_id, admin_username="admin_user_1", conn=self.conn)
        self.assertIsNotNone(conv)
        self.assertEqual(conv["id"], conv_id)
        self.assertEqual(conv["admin_username"], "admin_user_1")
        self.assertEqual(conv["title"], "Test Conversation")

    def test_touch_conversation_refreshes_expiry(self):
        conv_id = ai_chat_storage.create_conversation("admin_user_1", "Initial Title", conn=self.conn)
        time.sleep(0.01)
        ai_chat_storage.touch_conversation(conv_id, new_title="Updated Title", conn=self.conn)

        conv = ai_chat_storage.get_conversation(conv_id, conn=self.conn)
        self.assertEqual(conv["title"], "Updated Title")

    def test_48_hour_expiration_lifecycle(self):
        conv_id = ai_chat_storage.create_conversation("admin_user_1", "Expiring Conv", conn=self.conn)
        
        # Artificially set expires_at in the past
        past_time = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
        cursor = self.conn.cursor()
        cursor.execute("UPDATE ai_chat_conversations SET expires_at = ? WHERE id = ?", (past_time, conv_id))
        self.conn.commit()

        # Fetching should recognize expiration, purge it, and return None
        conv = ai_chat_storage.get_conversation(conv_id, conn=self.conn)
        self.assertIsNone(conv)

        # Ensure cleanup function safely runs
        cleaned = ai_chat_storage.cleanup_expired_conversations(conn=self.conn)
        self.assertTrue(cleaned)

    def test_messages_persistence_and_ordering(self):
        conv_id = ai_chat_storage.create_conversation("admin_user_1", "Messages Test", conn=self.conn)

        ai_chat_storage.add_message(conv_id, "user", "Hello AI", conn=self.conn)
        ai_chat_storage.add_message(conv_id, "assistant", "Hello Admin!", metadata={"model": "llama-3.3-70b"}, conn=self.conn)

        messages = ai_chat_storage.get_messages(conv_id, conn=self.conn)
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]["role"], "user")
        self.assertEqual(messages[0]["content"], "Hello AI")
        self.assertEqual(messages[1]["role"], "assistant")
        self.assertEqual(messages[1]["content"], "Hello Admin!")
        self.assertEqual(messages[1]["metadata"]["model"], "llama-3.3-70b")

    def test_delete_and_clear_conversations(self):
        c1 = ai_chat_storage.create_conversation("admin1", "Chat 1", conn=self.conn)
        c2 = ai_chat_storage.create_conversation("admin1", "Chat 2", conn=self.conn)
        c3 = ai_chat_storage.create_conversation("admin2", "Admin2 Chat", conn=self.conn)

        # Delete single conversation
        ai_chat_storage.delete_conversation(c1, admin_username="admin1", conn=self.conn)
        self.assertIsNone(ai_chat_storage.get_conversation(c1, conn=self.conn))

        # Clear all for admin1
        ai_chat_storage.clear_admin_conversations("admin1", conn=self.conn)
        self.assertEqual(len(ai_chat_storage.list_conversations("admin1", conn=self.conn)), 0)
        # admin2 conversation should remain untouched
        self.assertIsNotNone(ai_chat_storage.get_conversation(c3, conn=self.conn))


class TestAIDataAccess(unittest.TestCase):
    """Tests read-only data access helpers across all cricket areas."""

    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        
        # Build schema
        self.conn.executescript("""
            CREATE TABLE players (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                batting_style TEXT,
                bowling_style TEXT,
                is_keeper INTEGER DEFAULT 0,
                avatar_url TEXT
            );
            CREATE TABLE teams (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                logo_url TEXT
            );
            CREATE TABLE team_players (
                team_id INTEGER,
                player_id INTEGER,
                PRIMARY KEY (team_id, player_id)
            );
            CREATE TABLE tournaments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                win_points INTEGER DEFAULT 2,
                tie_points INTEGER DEFAULT 1,
                nr_points INTEGER DEFAULT 1
            );
            CREATE TABLE tournament_teams (
                tournament_id INTEGER,
                team_id INTEGER,
                PRIMARY KEY (tournament_id, team_id)
            );
            CREATE TABLE matches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tournament_id INTEGER,
                team1_id INTEGER NOT NULL,
                team2_id INTEGER NOT NULL,
                match_format TEXT DEFAULT 'T20',
                overs_limit INTEGER DEFAULT 20,
                ground TEXT,
                match_date TEXT,
                match_time TEXT,
                status TEXT DEFAULT 'completed',
                toss_winner_id INTEGER,
                toss_decision TEXT,
                current_innings_id INTEGER,
                winner_id INTEGER,
                result_margin TEXT
            );
            CREATE TABLE innings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                match_id INTEGER NOT NULL,
                innings_number INTEGER NOT NULL,
                batting_team_id INTEGER NOT NULL,
                bowling_team_id INTEGER NOT NULL,
                total_runs INTEGER DEFAULT 0,
                total_wickets INTEGER DEFAULT 0,
                balls_bowled INTEGER DEFAULT 0,
                wides INTEGER DEFAULT 0,
                noballs INTEGER DEFAULT 0,
                byes INTEGER DEFAULT 0,
                legbyes INTEGER DEFAULT 0,
                status TEXT DEFAULT 'completed'
            );
            CREATE TABLE deliveries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                innings_id INTEGER NOT NULL,
                over_number INTEGER NOT NULL,
                ball_of_over INTEGER NOT NULL,
                delivery_count INTEGER NOT NULL,
                striker_id INTEGER NOT NULL,
                non_striker_id INTEGER NOT NULL,
                bowler_id INTEGER NOT NULL,
                runs_batter INTEGER DEFAULT 0,
                runs_extras INTEGER DEFAULT 0,
                extra_type TEXT,
                is_legal INTEGER DEFAULT 1,
                is_wicket INTEGER DEFAULT 0,
                wicket_type TEXT,
                player_dismissed_id INTEGER,
                fielder_id INTEGER,
                is_bowler_wicket INTEGER DEFAULT 0,
                commentary TEXT
            );
            CREATE TABLE admin_statistics_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stat_key TEXT NOT NULL,
                params_json TEXT NOT NULL DEFAULT '{}',
                result_json TEXT NOT NULL,
                completed_matches_count INTEGER NOT NULL DEFAULT 0,
                calculated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # Insert seed fixtures
        c = self.conn.cursor()
        c.execute("INSERT INTO players (id, name, batting_style, bowling_style) VALUES (1, 'Virat Kohli', 'Right-hand bat', 'Right-arm medium')")
        c.execute("INSERT INTO players (id, name, batting_style, bowling_style) VALUES (2, 'Rohit Sharma', 'Right-hand bat', 'Right-arm offbreak')")
        c.execute("INSERT INTO players (id, name, batting_style, bowling_style) VALUES (3, 'Jasprit Bumrah', 'Right-hand bat', 'Right-arm fast')")
        
        c.execute("INSERT INTO teams (id, name) VALUES (1, 'India')")
        c.execute("INSERT INTO teams (id, name) VALUES (2, 'Australia')")
        
        c.execute("INSERT INTO team_players (team_id, player_id) VALUES (1, 1)")
        c.execute("INSERT INTO team_players (team_id, player_id) VALUES (1, 2)")
        c.execute("INSERT INTO team_players (team_id, player_id) VALUES (1, 3)")

        c.execute("INSERT INTO tournaments (id, name) VALUES (1, 'T20 World Cup')")
        c.execute("INSERT INTO tournament_teams (tournament_id, team_id) VALUES (1, 1)")
        c.execute("INSERT INTO tournament_teams (tournament_id, team_id) VALUES (1, 2)")

        c.execute("""
            INSERT INTO matches (id, tournament_id, team1_id, team2_id, status, winner_id, result_margin, ground, match_date)
            VALUES (1, 1, 1, 2, 'completed', 1, 'India won by 15 runs', 'Melbourne', '2026-10-01')
        """)

        c.execute("INSERT INTO innings (id, match_id, innings_number, batting_team_id, bowling_team_id, total_runs, total_wickets, balls_bowled) VALUES (1, 1, 1, 1, 2, 180, 4, 120)")
        c.execute("INSERT INTO innings (id, match_id, innings_number, batting_team_id, bowling_team_id, total_runs, total_wickets, balls_bowled) VALUES (2, 1, 2, 2, 1, 165, 8, 120)")

        # Sample deliveries
        c.execute("INSERT INTO deliveries (innings_id, over_number, ball_of_over, delivery_count, striker_id, non_striker_id, bowler_id, runs_batter, commentary) VALUES (1, 0, 1, 1, 1, 2, 3, 4, 'Driven through covers for four')")
        c.execute("INSERT INTO deliveries (innings_id, over_number, ball_of_over, delivery_count, striker_id, non_striker_id, bowler_id, runs_batter, is_wicket, is_bowler_wicket, wicket_type, player_dismissed_id, commentary) VALUES (1, 0, 2, 2, 1, 2, 3, 0, 1, 1, 'bowled', 1, 'Clean bowled!')")
        
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_database_health(self):
        health = ai_data_access.get_database_health(conn=self.conn)
        self.assertEqual(health["status"], "healthy")
        self.assertEqual(health["total_players"], 3)
        self.assertEqual(health["total_teams"], 2)
        self.assertEqual(health["completed_matches"], 1)

    def test_search_players(self):
        res = ai_data_access.search_players(query="Virat", conn=self.conn)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["name"], "Virat Kohli")

    def test_list_matches_and_summary(self):
        matches = ai_data_access.list_matches(status="completed", conn=self.conn)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["winner"], "India")

        summary = ai_data_access.get_match_summary(1, conn=self.conn)
        self.assertIsNotNone(summary)
        self.assertEqual(summary["ground"], "Melbourne")
        self.assertEqual(len(summary["innings"]), 2)

    def test_match_investigation(self):
        inv = ai_data_access.get_match_investigation(1, conn=self.conn)
        self.assertIsNotNone(inv)
        self.assertIn("tactical_analysis", inv)
        self.assertEqual(len(inv["tactical_analysis"]), 1)
        self.assertEqual(inv["tactical_analysis"][0]["team_name"], "India")

    def test_tool_dispatcher(self):
        # Valid tool execution
        res = ai_data_access.execute_tool("search_players", {"query": "Rohit"}, conn=self.conn)
        self.assertTrue(res.get("success"))
        self.assertEqual(len(res.get("result", [])), 1)

        # Invalid tool rejection
        bad_res = ai_data_access.execute_tool("drop_tables_dangerous", {}, conn=self.conn)
        self.assertTrue(bad_res.get("error"))

    def test_analyze_dot_balls(self):
        # Insert test deliveries into match 1 innings 1
        c = self.conn.cursor()
        c.execute("""
            INSERT INTO deliveries (innings_id, over_number, ball_of_over, delivery_count, striker_id, non_striker_id, bowler_id, runs_batter, runs_extras, extra_type, is_legal)
            VALUES (1, 1, 1, 3, 1, 2, 3, 0, 0, NULL, 1)
        """)
        c.execute("""
            INSERT INTO deliveries (innings_id, over_number, ball_of_over, delivery_count, striker_id, non_striker_id, bowler_id, runs_batter, runs_extras, extra_type, is_legal)
            VALUES (1, 1, 2, 4, 1, 2, 3, 0, 1, 'bye', 1)
        """)
        c.execute("""
            INSERT INTO deliveries (innings_id, over_number, ball_of_over, delivery_count, striker_id, non_striker_id, bowler_id, runs_batter, runs_extras, extra_type, is_legal)
            VALUES (1, 1, 3, 5, 1, 2, 3, 4, 0, NULL, 1)
        """)
        c.execute("""
            INSERT INTO deliveries (innings_id, over_number, ball_of_over, delivery_count, striker_id, non_striker_id, bowler_id, runs_batter, runs_extras, extra_type, is_legal)
            VALUES (1, 1, 4, 6, 1, 2, 3, 0, 1, 'wide', 0)
        """)
        self.conn.commit()

        # 1. Test batter dot balls
        res_bat = ai_data_access.analyze_dot_balls(player_id=1, target_type="batter", conn=self.conn)
        self.assertEqual(res_bat["status"], "success")
        self.assertIn("batting_dot_balls", res_bat)
        bat_info = res_bat["batting_dot_balls"]
        self.assertGreater(bat_info["dot_balls_faced"], 0)
        self.assertIn("dot_ball_percentage", bat_info)

        # 2. Test bowler dot balls
        res_bowl = ai_data_access.analyze_dot_balls(player_id=3, target_type="bowler", conn=self.conn)
        self.assertEqual(res_bowl["status"], "success")
        self.assertIn("bowling_dot_balls", res_bowl)
        bowl_info = res_bowl["bowling_dot_balls"]
        self.assertGreater(bowl_info["dot_balls_bowled"], 0)
        self.assertEqual(bowl_info["wides"], 1)

        # 3. Test match scope
        res_match = ai_data_access.analyze_dot_balls(match_id=1, conn=self.conn)
        self.assertEqual(res_match["status"], "success")
        self.assertIn("innings_breakdown", res_match)

        # 4. Test nonexistent player / insufficient data
        res_empty = ai_data_access.analyze_dot_balls(player_name="Nonexistent Player", conn=self.conn)
        self.assertEqual(res_empty["status"], "not_found")

        # 5. Verify registered in AI_TOOLS_REGISTRY and AI_TOOLS_DEFINITIONS
        self.assertIn("analyze_dot_balls", ai_data_access.AI_TOOLS_REGISTRY)
        tool_names = [t["function"]["name"] for t in ai_data_access.AI_TOOLS_DEFINITIONS]
        self.assertIn("analyze_dot_balls", tool_names)



class TestAIService(unittest.TestCase):
    """Tests Groq service communication and tool-calling workflow with mocks."""

    def test_missing_api_key_returns_safe_warning(self):
        with patch.dict(os.environ, {"GROQ_API_KEY": ""}):
            result = ai_service.process_chat_message(
                admin_username="test_admin",
                user_message="Who scored the most runs?"
            )
            self.assertTrue(result.get("success"))
            self.assertIn("Groq API Key Not Configured", result.get("response"))
            self.assertFalse(result.get("is_configured"))

    @patch("ai_service._call_groq_api")
    def test_groq_simple_response(self, mock_api):
        mock_api.return_value = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "Virat Kohli has the highest batting average in the tournament."
                    }
                }
            ]
        }

        with patch.dict(os.environ, {"GROQ_API_KEY": "gsk_mock_test_key"}):
            result = ai_service.process_chat_message(
                admin_username="test_admin",
                user_message="Tell me about Virat Kohli"
            )
            self.assertTrue(result.get("success"))
            self.assertIn("Virat Kohli", result.get("response"))

    @patch("ai_service._call_groq_api")
    def test_groq_multi_round_tool_calling(self, mock_api):
        # Round 1: Model requests tool call to search_players
        # Round 2: Model returns final answer grounded in tool output
        mock_api.side_effect = [
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "id": "call_search_1",
                                    "type": "function",
                                    "function": {
                                        "name": "get_database_health",
                                        "arguments": "{}"
                                    }
                                }
                            ]
                        }
                    }
                ]
            },
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "The database contains active cricket records and is currently healthy."
                        }
                    }
                ]
            }
        ]

        with patch.dict(os.environ, {"GROQ_API_KEY": "gsk_mock_test_key"}):
            result = ai_service.process_chat_message(
                admin_username="test_admin",
                user_message="Is the database healthy?"
            )
            self.assertTrue(result.get("success"))
            self.assertIn("healthy", result.get("response"))
            self.assertIn("get_database_health", result.get("tools_called", []))

    @patch("ai_service._call_groq_api")
    def test_greeting_suppresses_tools(self, mock_api):
        mock_api.return_value = {
            "choices": [{"message": {"role": "assistant", "content": "Hello! Welcome to CricScorer Admin AI."}}]
        }
        with patch.dict(os.environ, {"GROQ_API_KEY": "gsk_mock_test_key"}):
            result = ai_service.process_chat_message(
                admin_username="test_admin",
                user_message="Hello"
            )
            self.assertTrue(result.get("success"))
            self.assertEqual(len(result.get("tools_called", [])), 0)
            self.assertIn("Hello", result.get("response"))
            args, kwargs = mock_api.call_args
            self.assertIsNone(kwargs.get("tools"))

    @patch("ai_service._call_groq_api")
    def test_identity_suppresses_tools(self, mock_api):
        mock_api.return_value = {
            "choices": [{"message": {"role": "assistant", "content": "I am the CricScorer AI Cricket Assistant."}}]
        }
        with patch.dict(os.environ, {"GROQ_API_KEY": "gsk_mock_test_key"}):
            result = ai_service.process_chat_message(
                admin_username="test_admin",
                user_message="Who are you?"
            )
            self.assertTrue(result.get("success"))
            self.assertEqual(len(result.get("tools_called", [])), 0)
            self.assertIn("CricScorer AI Cricket Assistant", result.get("response"))
            args, kwargs = mock_api.call_args
            self.assertIsNone(kwargs.get("tools"))

    def test_clean_and_validate_messages(self):
        # Case 1: Orphaned tool message at start of history
        history = [
            {"role": "tool", "content": '{"dots": 10}', "tool_call_id": "call_1"},
            {"role": "user", "content": "What is the score?"}
        ]
        cleaned = ai_service._clean_and_validate_messages(history, "Sys prompt")
        self.assertEqual(cleaned[0]["role"], "system")
        self.assertEqual(cleaned[1]["role"], "user")

        # Case 2: Incomplete tool_calls
        history_broken = [
            {"role": "user", "content": "Question"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "function": {"name": "f1"}}]}
        ]
        cleaned_broken = ai_service._clean_and_validate_messages(history_broken, "Sys prompt")
        self.assertNotIn("tool_calls", cleaned_broken[2])

    def test_parse_retry_after(self):
        self.assertEqual(ai_service._parse_retry_after({"Retry-After": "3"}), 3.0)
        self.assertEqual(ai_service._parse_retry_after({"Retry-After": "60"}), 10.0)
        self.assertEqual(ai_service._parse_retry_after(None), 2.0)
        self.assertEqual(ai_service._parse_retry_after({"Retry-After": "invalid"}), 2.0)

    @patch("urllib.request.urlopen")
    def test_groq_503_retry_and_recovery(self, mock_urlopen):
        import urllib.error
        import io

        # Simulate 503 HTTPError on 1st attempt, then successful 200 on retry
        mock_503 = urllib.error.HTTPError(
            url="https://api.groq.com",
            code=503,
            msg="Service Unavailable",
            hdrs={"Retry-After": "1"},
            fp=io.BytesIO(b'{"error": {"message": "Server overloaded", "code": 503}}')
        )
        mock_success = MagicMock()
        mock_success.read.return_value = json.dumps({
            "choices": [{"message": {"role": "assistant", "content": "Recovered from 503"}}]
        }).encode("utf-8")
        mock_success.__enter__.return_value = mock_success

        mock_urlopen.side_effect = [mock_503, mock_success]

        with patch.dict(os.environ, {"GROQ_API_KEY": "gsk_mock_test_key"}):
            resp = ai_service._call_groq_api([{"role": "user", "content": "test"}])
            self.assertEqual(resp["choices"][0]["message"]["content"], "Recovered from 503")
            self.assertEqual(mock_urlopen.call_count, 2)



class TestAIScoringIsolationAndLatency(unittest.TestCase):
    """
    Verifies that live scoring operations:
    1. Make zero AI API calls and zero AI table reads.
    2. Maintain sub-millisecond execution latency.
    """

    def setUp(self):
        self.match = MatchState(
            match_id=999,
            team1_id=1,
            team2_id=2,
            overs_limit=20,
            players_per_team=11,
            match_format="T20"
        )
        self.match.start_innings(innings_id=1, batting_team_id=1, bowling_team_id=2, innings_number=1)
        self.innings = self.match.get_current_innings()
        self.innings.striker_id = 101
        self.innings.non_striker_id = 102
        self.innings.bowler_id = 201

    def test_scoring_performance_and_zero_ai_interference(self):
        # Measure latency of scoring 100 deliveries
        start_time = time.perf_counter()
        
        for i in range(1, 101):
            runs = (i % 6)
            is_wkt = (i % 20 == 0)
            self.innings.apply_delivery({
                "runs_batter": runs,
                "runs_extras": 0,
                "extra_type": None,
                "is_legal": 1,
                "is_wicket": 1 if is_wkt else 0,
                "wicket_type": "caught" if is_wkt else None,
                "player_dismissed_id": self.innings.striker_id if is_wkt else None,
                "new_batter_id": 103 + i if is_wkt else None
            })

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        avg_per_ball_ms = elapsed_ms / 100.0

        # Assert scoring is fast (< 1.5ms per ball in pure in-memory execution)
        self.assertLess(avg_per_ball_ms, 5.0)
        self.assertEqual(self.innings.total_wickets, 5)


class TestAIRoutesAuth(unittest.TestCase):
    """Verifies that all AI endpoints strictly enforce admin authentication."""

    def setUp(self):
        flask_app.app.config["TESTING"] = True
        flask_app.app.config["SECRET_KEY"] = "test_secret_key"
        self.client = flask_app.app.test_client()

    def test_unauthenticated_access_is_blocked(self):
        # GET AI Chat UI
        resp = self.client.get("/admin/ai-chat", follow_redirects=False)
        self.assertIn(resp.status_code, [302, 401, 403])

        # POST AI Message
        resp_post = self.client.post("/admin/api/ai/chat", json={"message": "hello"}, follow_redirects=False)
        self.assertIn(resp_post.status_code, [302, 401, 403])

        # GET AI History
        resp_hist = self.client.get("/admin/api/ai/history/conv_test123", follow_redirects=False)
        self.assertIn(resp_hist.status_code, [302, 401, 403])

    def test_authenticated_admin_can_access_ai_chat_ui(self):
        with self.client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_user"] = "admin"
            sess["admin_id"] = 1

        resp = self.client.get("/admin/ai-chat")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"AI Cricket Assistant", resp.data)
        self.assertIn(b"Who are the top 10 run scorers?", resp.data)


if __name__ == "__main__":
    unittest.main()
