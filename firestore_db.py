"""Firebase Admin SDK setup for Cloud Firestore.

Credentials may be provided as complete JSON or as individual service-account
environment variables. Keep PostgreSQL active until app data access is migrated.
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
SERVICE_ACCOUNT_FIELDS = (
    "type",
    "project_id",
    "private_key",
    "private_key_id",
    "client_email",
    "client_id",
    "auth_uri",
    "token_uri",
    "auth_provider_x509_cert_url",
    "client_x509_cert_url",
    "universe_domain",
)
REQUIRED_SERVICE_ACCOUNT_FIELDS = (
    "type",
    "project_id",
    "private_key",
    "client_email",
    "token_uri",
)


def _load_service_account() -> Dict[str, Any]:
    raw_credentials = os.environ.get(SERVICE_ACCOUNT_ENV)

    def reject_constant(value: str) -> None:
        raise ValueError(f"Invalid JSON constant: {value}")

    def reject_duplicate_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    if raw_credentials:
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
        credential_source = SERVICE_ACCOUNT_ENV
    else:
        service_account = {
            field: os.environ[field]
            for field in SERVICE_ACCOUNT_FIELDS
            if os.environ.get(field)
        }
        if not service_account:
            raise RuntimeError(
                f"Missing Firebase credentials. Set {SERVICE_ACCOUNT_ENV} to the "
                "complete service-account JSON, or add its individual fields as secrets."
            )
        credential_source = "individual Firebase service-account secrets"

    if not isinstance(service_account, dict):
        raise RuntimeError(
            f"{credential_source} must contain a JSON object, not an array or scalar."
        )
    missing_fields = [
        field for field in REQUIRED_SERVICE_ACCOUNT_FIELDS
        if not isinstance(service_account.get(field), str)
        or not service_account[field].strip()
    ]
    if missing_fields:
        raise RuntimeError(
            f"{credential_source} is missing required non-empty fields: "
            f"{', '.join(missing_fields)}."
        )
    if service_account["type"] != "service_account":
        raise RuntimeError(
            f"{credential_source} must identify a Google service-account JSON file "
            '(type must be "service_account").'
        )

    private_key = service_account["private_key"]
    if "\\n" in private_key:
        service_account["private_key"] = private_key.replace("\\n", "\n")

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
