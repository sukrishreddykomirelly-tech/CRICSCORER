"""Validated, non-destructive imports of CricScorer JSON backups to Firestore."""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, Tuple

from migrate_postgres_to_firestore import (
    FIRESTORE_BATCH_SIZE,
    TABLES,
    _document_id,
    _to_firestore_value,
)


MAX_BACKUP_BYTES = 20 * 1024 * 1024
MAX_FIRESTORE_DOCUMENT_BYTES = 1024 * 1024 - 1024
BACKUP_METADATA_KEYS = {"application", "timestamp", "version"}


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"Non-standard JSON value: {value}")


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def prepare_backup_documents(raw_data: bytes) -> Dict[str, list[Tuple[str, Dict[str, Any]]]]:
    """Parse and validate every row before any Firestore write is attempted."""
    if not isinstance(raw_data, bytes):
        raise ValueError("The uploaded backup must be a file.")
    if not raw_data:
        raise ValueError("The uploaded JSON file is empty.")
    if len(raw_data) > MAX_BACKUP_BYTES:
        raise ValueError(f"Backup file exceeds the {MAX_BACKUP_BYTES // (1024 * 1024)} MB limit.")

    try:
        text = raw_data.decode("utf-8-sig")
        payload = json.loads(
            text,
            parse_constant=_reject_json_constant,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("The uploaded file is not valid UTF-8 JSON.") from exc

    if not isinstance(payload, dict):
        raise ValueError("The backup root must be a JSON object containing table arrays.")

    if payload.get("application") not in (None, "CricScorer"):
        raise ValueError("This JSON file is not a CricScorer backup.")

    allowed_keys = set(TABLES) | BACKUP_METADATA_KEYS
    unexpected = sorted(set(payload) - allowed_keys)
    if unexpected:
        raise ValueError(f"Unsupported backup section(s): {', '.join(unexpected[:10])}.")

    present_tables = [table for table in TABLES if table in payload]
    if not present_tables:
        raise ValueError("No supported CricScorer data tables were found in the JSON file.")

    prepared: Dict[str, list[Tuple[str, Dict[str, Any]]]] = {}
    for table in present_tables:
        rows = payload[table]
        if not isinstance(rows, list):
            raise ValueError(f"The '{table}' section must be a JSON array.")

        table_docs: list[Tuple[str, Dict[str, Any]]] = []
        seen_ids = set()
        for index, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                raise ValueError(f"Row {index} in '{table}' must be a JSON object.")
            try:
                doc_id = _document_id(table, row)
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"Row {index} in '{table}' has no valid stable record ID.") from exc

            if not doc_id or "/" in doc_id or len(doc_id.encode("utf-8")) > 1500:
                raise ValueError(f"Row {index} in '{table}' has an invalid Firestore document ID.")
            if doc_id in seen_ids:
                raise ValueError(f"Duplicate record ID '{doc_id}' in the '{table}' section.")
            seen_ids.add(doc_id)

            document = _to_firestore_value(row)
            encoded_size = len(
                json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            )
            if encoded_size > MAX_FIRESTORE_DOCUMENT_BYTES:
                raise ValueError(
                    f"Row {index} in '{table}' is too large for a Firestore document."
                )
            table_docs.append((doc_id, document))
        prepared[table] = table_docs

    return prepared


def import_backup_to_firestore(raw_data: bytes, firestore_client) -> Dict[str, int]:
    """Merge validated backup rows into Firestore without deleting omitted records.

    Documents with the same stable ID are overwritten. The caller should tell the
    administrator this before invoking the function.
    """
    prepared = prepare_backup_documents(raw_data)
    writes: Iterable[Tuple[str, str, Dict[str, Any]]] = (
        (table, doc_id, document)
        for table, documents in prepared.items()
        for doc_id, document in documents
    )
    pending = list(writes)

    for start in range(0, len(pending), FIRESTORE_BATCH_SIZE):
        batch = firestore_client.batch()
        for table, doc_id, document in pending[start:start + FIRESTORE_BATCH_SIZE]:
            batch.set(firestore_client.collection(table).document(doc_id), document)
        batch.commit()

    return {table: len(documents) for table, documents in prepared.items()}
