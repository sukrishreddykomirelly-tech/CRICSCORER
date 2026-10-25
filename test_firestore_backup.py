import json

import pytest

from firestore_backup import (
    MAX_FIRESTORE_DOCUMENT_BYTES,
    import_backup_to_firestore,
    prepare_backup_documents,
)


class FakeDocument:
    def __init__(self, client, collection, document_id):
        self.client = client
        self.collection = collection
        self.document_id = document_id


class FakeCollection:
    def __init__(self, client, name):
        self.client = client
        self.name = name

    def document(self, document_id):
        return FakeDocument(self.client, self.name, document_id)


class FakeBatch:
    def __init__(self, client):
        self.client = client
        self.pending = []

    def set(self, reference, document):
        self.pending.append((reference, document))

    def commit(self):
        for reference, document in self.pending:
            self.client.documents[(reference.collection, reference.document_id)] = document
        self.client.commits += 1


class FakeFirestore:
    def __init__(self):
        self.documents = {}
        self.commits = 0

    def collection(self, name):
        return FakeCollection(self, name)

    def batch(self):
        return FakeBatch(self)


def backup_bytes(payload):
    return json.dumps(payload).encode("utf-8")


def test_backup_rows_are_prepared_with_stable_ids():
    prepared = prepare_backup_documents(backup_bytes({
        "application": "CricScorer",
        "players": [{"id": 12, "name": "Example"}],
        "team_players": [{"team_id": 3, "player_id": 12}],
    }))

    assert prepared["players"] == [("12", {"id": 12, "name": "Example"})]
    assert prepared["team_players"] == [
        ("3_12", {"team_id": 3, "player_id": 12})
    ]


def test_import_overwrites_matching_ids_but_does_not_delete_other_documents():
    client = FakeFirestore()
    client.documents[("players", "12")] = {"id": 12, "name": "Old"}
    client.documents[("players", "99")] = {"id": 99, "name": "Keep"}

    counts = import_backup_to_firestore(
        backup_bytes({"players": [{"id": 12, "name": "New"}]}),
        client,
    )

    assert counts == {"players": 1}
    assert client.documents[("players", "12")]["name"] == "New"
    assert client.documents[("players", "99")]["name"] == "Keep"
    assert client.commits == 1


@pytest.mark.parametrize("raw", [
    b"",
    b"{not-json}",
    b'{"players":[{"id":NaN}]}',
    b'{"players":[],"players":[]}',
])
def test_invalid_json_is_rejected_before_firestore_writes(raw):
    client = FakeFirestore()
    with pytest.raises(ValueError):
        import_backup_to_firestore(raw, client)
    assert client.documents == {}
    assert client.commits == 0


def test_unknown_backup_sections_are_rejected():
    with pytest.raises(ValueError, match="Unsupported backup section"):
        prepare_backup_documents(backup_bytes({
            "players": [],
            "service_account": {"private_key": "not allowed here"},
        }))


def test_duplicate_record_ids_are_rejected():
    with pytest.raises(ValueError, match="Duplicate record ID"):
        prepare_backup_documents(backup_bytes({
            "players": [{"id": 12}, {"id": 12}],
        }))


def test_firestore_document_size_limit_is_checked_before_writing():
    with pytest.raises(ValueError, match="too large"):
        prepare_backup_documents(backup_bytes({
            "players": [{"id": 1, "bio": "x" * MAX_FIRESTORE_DOCUMENT_BYTES}],
        }))
