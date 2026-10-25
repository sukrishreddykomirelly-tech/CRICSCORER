"""Firebase Admin SDK setup for Cloud Firestore.

Credentials are read only from the FIREBASE_SERVICE_ACCOUNT_JSON environment
variable. Keep PostgreSQL as the active application database until all SQL
data access has been migrated and Firestore has been verified.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Any, Dict

import firebase_admin
from firebase_admin import credentials, firestore


FIREBASE_APP_NAME = "cricscorer"
SERVICE_ACCOUNT_ENV = "FIREBASE_SERVICE_ACCOUNT_JSON"


def _load_service_account() -> Dict[str, Any]:
    raw_credentials = os.environ.get(SERVICE_ACCOUNT_ENV)
    if not raw_credentials:
        raise RuntimeError(
            f"Missing {SERVICE_ACCOUNT_ENV}. Add the Firebase service-account "
            "JSON to Replit Secrets before connecting to Firestore."
        )

    def reject_constant(value: str) -> None:
        raise ValueError(f"Invalid JSON constant: {value}")

    def reject_duplicate_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        service_account = json.loads(
            raw_credentials,
            parse_constant=reject_constant,
            object_pairs_hook=reject_duplicate_keys,
        )
    except (json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError(
            f"{SERVICE_ACCOUNT_ENV} must contain valid, standard service-account JSON."
        ) from exc

    required_fields = ("type", "project_id", "private_key", "client_email", "token_uri")
    if not isinstance(service_account, dict):
        raise RuntimeError(
            f"{SERVICE_ACCOUNT_ENV} must contain a JSON object, not an array or scalar."
        )
    missing_fields = [
        field for field in required_fields
        if not isinstance(service_account.get(field), str)
        or not service_account[field].strip()
    ]
    if missing_fields:
        raise RuntimeError(
            f"{SERVICE_ACCOUNT_ENV} is missing required non-empty fields: "
            f"{', '.join(missing_fields)}."
        )
    if service_account["type"] != "service_account":
        raise RuntimeError(
            f"{SERVICE_ACCOUNT_ENV} must be a Google service-account JSON file "
            '(type must be "service_account").'
        )

    return service_account


@lru_cache(maxsize=1)
def get_firestore_client():
    """Return the Firestore client, initializing the named Admin app once."""
    service_account = _load_service_account()

    try:
        firebase_app = firebase_admin.get_app(FIREBASE_APP_NAME)
    except ValueError:
        firebase_app = firebase_admin.initialize_app(
            credentials.Certificate(service_account),
            name=FIREBASE_APP_NAME,
        )

    return firestore.client(app=firebase_app)
