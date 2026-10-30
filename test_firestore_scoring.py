"""Tests for Firestore live scoring reading and writing."""

from unittest.mock import MagicMock, patch
import pytest

from scoring import MatchState
import firestore_scoring


class MockDocSnapshot:
    def __init__(self, doc_id, data, exists=True):
        self.id = str(doc_id)
        self._data = data
        self.exists = exists
        self.reference = MagicMock()

    def to_dict(self):
        return self._data


def test_is_firestore_enabled_with_valid_config(monkeypatch):
    monkeypatch.setattr(firestore_scoring.firestore_db, "is_firestore_configured", lambda: True)
    assert firestore_scoring.is_firestore_enabled() is True


def test_is_firestore_enabled_without_config(monkeypatch):
    monkeypatch.setattr(firestore_scoring.firestore_db, "is_firestore_configured", lambda: False)
    assert firestore_scoring.is_firestore_enabled() is False


def test_firestore_load_match_state_hydrates_correctly():
    fake_match = {
        "id": 10,
        "team1_id": 1,
        "team2_id": 2,
        "match_format": "T20",
        "overs_limit": 20,
        "status": "live",
        "toss_winner_id": 1,
        "toss_decision": "bat"
    }
    fake_innings = [{
        "id": 100,
        "match_id": 10,
        "innings_number": 1,
        "batting_team_id": 1,
        "bowling_team_id": 2,
        "status": "ongoing",
        "current_striker_id": 101,
        "current_non_striker_id": 102,
        "current_bowler_id": 201,
        "total_runs": 4,
        "total_wickets": 0,
        "balls_bowled": 1
    }]
    fake_deliveries = [{
        "id": 1,
        "innings_id": 100,
        "over_number": 1,
        "ball_of_over": 1,
        "delivery_count": 1,
        "striker_id": 101,
        "non_striker_id": 102,
        "bowler_id": 201,
        "runs_batter": 4,
        "runs_extras": 0,
        "extra_type": None,
        "is_legal": 1,
        "is_wicket": 0,
        "commentary": "Boundary four!"
    }]

    mock_db = MagicMock()
    mock_db.collection("matches").document("10").get.return_value = MockDocSnapshot("10", fake_match)
    mock_db.collection("match_players").where().stream.return_value = []
    mock_db.collection("substitutions").where().stream.return_value = []
    mock_db.collection("innings").where().stream.return_value = [MockDocSnapshot("100", fake_innings[0])]
    mock_db.collection("deliveries").where().stream.return_value = [MockDocSnapshot("1", fake_deliveries[0])]

    with patch.object(firestore_scoring, "_get_db", return_value=mock_db), \
         patch.object(firestore_scoring, "get_all_players", return_value={101: {"name": "Batter 1"}, 102: {"name": "Batter 2"}, 201: {"name": "Bowler 1"}}):
        
        state = firestore_scoring.firestore_load_match_state(10)
        assert state is not None
        assert state.match_id == 10
        assert state.team1_id == 1
        assert state.team2_id == 2
        assert state.status == "live"
        assert len(state.innings) == 1
        assert state.innings[0].total_runs == 4
        assert state.innings[0].balls_bowled == 1


def test_firestore_save_delivery_writes_and_rebuilds():
    mock_db = MagicMock()
    mock_db.collection("innings").document("100").get.return_value = MockDocSnapshot("100", {"match_id": 10})
    
    with patch.object(firestore_scoring, "_get_db", return_value=mock_db), \
         patch.object(firestore_scoring, "get_next_sequence_id", return_value=999), \
         patch.object(firestore_scoring, "firestore_rebuild_and_cache_match_state") as mock_rebuild, \
         patch.object(firestore_scoring, "_mirror_sql_save_delivery"):

        delivery_input = {
            "over_number": 1,
            "ball_of_over": 2,
            "delivery_count": 2,
            "striker_id": 101,
            "non_striker_id": 102,
            "bowler_id": 201,
            "runs_batter": 1,
            "runs_extras": 0,
            "extra_type": None,
            "is_legal": 1,
            "is_wicket": 0,
            "commentary": "Single taken"
        }
        
        match_id = firestore_scoring.firestore_save_delivery(100, delivery_input)
        assert match_id == 10
        mock_db.collection("deliveries").document("999").set.assert_called_once()
        saved_doc = mock_db.collection("deliveries").document("999").set.call_args[0][0]
        assert saved_doc["id"] == 999
        assert saved_doc["innings_id"] == 100
        assert saved_doc["runs_batter"] == 1
        mock_rebuild.assert_called_once_with(10)


def test_firestore_delete_last_delivery_removes_from_firestore():
    mock_db = MagicMock()
    del_doc = MockDocSnapshot("55", {"id": 55, "over_number": 1, "ball_of_over": 1, "delivery_count": 1})
    del_ref = MagicMock()
    del_doc.reference = del_ref
    
    mock_db.collection("deliveries").where().stream.return_value = [del_doc]
    mock_db.collection("innings").document("100").get.return_value = MockDocSnapshot("100", {"match_id": 10})

    with patch.object(firestore_scoring, "_get_db", return_value=mock_db), \
         patch.object(firestore_scoring, "firestore_rebuild_and_cache_match_state") as mock_rebuild, \
         patch.object(firestore_scoring, "_mirror_sql_delete_delivery"):

        match_id = firestore_scoring.firestore_delete_last_delivery(100)
        assert match_id == 10
        del_ref.delete.assert_called_once()
        mock_rebuild.assert_called_once_with(10)


def test_firestore_change_bowler_updates_innings():
    mock_db = MagicMock()
    inn_ref = MagicMock()
    mock_db.collection("innings").document.return_value = inn_ref

    with patch.object(firestore_scoring, "_get_db", return_value=mock_db), \
         patch.object(firestore_scoring, "_mirror_sql_update_innings"):
        
        firestore_scoring.firestore_change_bowler(10, 100, 202)
        inn_ref.update.assert_called_once_with({"current_bowler_id": 202})


def test_firestore_change_batsman_updates_innings():
    mock_db = MagicMock()
    inn_ref = MagicMock()
    mock_db.collection("innings").document.return_value = inn_ref

    with patch.object(firestore_scoring, "_get_db", return_value=mock_db), \
         patch.object(firestore_scoring, "_mirror_sql_update_innings"):
        
        firestore_scoring.firestore_change_batsman(10, 100, striker_id=105, non_striker_id=106)
        inn_ref.update.assert_called_once_with({
            "current_striker_id": 105,
            "current_non_striker_id": 106
        })
