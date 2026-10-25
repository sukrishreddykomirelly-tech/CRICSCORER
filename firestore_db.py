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

    try:
        service_account = json.loads(raw_credentials)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"{SERVICE_ACCOUNT_ENV} must contain valid service-account JSON."
        ) from exc

    if not isinstance(service_account, dict) or not service_account.get("project_id"):
        raise RuntimeError(
            f"{SERVICE_ACCOUNT_ENV} must be a Firebase service-account JSON object "
            "with a project_id."
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
