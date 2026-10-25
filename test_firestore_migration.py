from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

import pytest

from firestore_db import SERVICE_ACCOUNT_ENV, _load_service_account
from migrate_postgres_to_firestore import _document_id, _to_firestore_value


def test_service_account_is_required_without_revealing_credentials(monkeypatch):
    monkeypatch.delenv(SERVICE_ACCOUNT_ENV, raising=False)
    with pytest.raises(RuntimeError, match=SERVICE_ACCOUNT_ENV):
        _load_service_account()


def test_service_account_json_must_be_valid(monkeypatch):
    monkeypatch.setenv(SERVICE_ACCOUNT_ENV, "not-json")
    with pytest.raises(RuntimeError, match="valid service-account JSON"):
        _load_service_account()


def test_document_id_uses_existing_id_as_string():
    assert _document_id("players", {"id": 12, "name": "Player"}) == "12"


def test_document_id_supports_join_tables():
    assert _document_id(
        "match_players",
        {"match_id": 7, "team_id": 3, "player_id": 12},
    ) == "7_3_12"
    assert _document_id("match_awards_override", {"match_id": 7}) == "7"


def test_document_id_rejects_unknown_keyless_table():
    with pytest.raises(ValueError, match="No stable Firestore document key"):
        _document_id("unknown_table", {"name": "x"})


def test_values_are_converted_to_firestore_compatible_types():
    timestamp = datetime(2026, 10, 25, tzinfo=timezone.utc)
    result = _to_firestore_value({
        "date": date(2026, 10, 25),
        "timestamp": timestamp,
        "whole": Decimal("4.0"),
        "fraction": Decimal("2.75"),
        "uuid": UUID("12345678-1234-5678-1234-567812345678"),
        "nested": (1, 2),
    })
    assert result == {
        "date": "2026-10-25",
        "timestamp": timestamp,
        "whole": 4,
        "fraction": 2.75,
        "uuid": "12345678-1234-5678-1234-567812345678",
        "nested": [1, 2],
    }
