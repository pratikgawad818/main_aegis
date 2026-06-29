"""Audit log helper: write one JSON line per verification (compliance trail)."""

import json
import logging
from datetime import datetime, timezone

from app.config import AUDIT_LOG_FILE

logger = logging.getLogger(__name__)


def utcnow_iso() -> str:
    """Return the current UTC time as an ISO-8601 string ending in 'Z'."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def write_audit_log(record: dict) -> None:
    """Append one JSON line to audit.log. Never crashes the request."""
    try:
        with open(AUDIT_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except Exception as e:
        logger.error(f"Audit log write failed: {e}")
