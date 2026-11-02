"""Error-response helpers.

Tools convert ``httpx`` failures into structured ``{"error": ...}`` dicts rather
than raising, so the model receives an interpretable result instead of a
transport-level exception. The client logs the underlying failure; these helpers
shape the response.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


def api_error(exc: httpx.HTTPStatusError) -> dict[str, Any]:
    """Format an HTTP status error as a standard error-response dict."""
    status = exc.response.status_code
    reason = exc.response.text[:500]
    logger.error("api_error status=%d", status)
    return {
        "error": f"TeamCity API error: {status}",
        "reason": reason,
    }


def connection_error(exc: httpx.RequestError) -> dict[str, Any]:
    """Format a connection error as a standard error-response dict."""
    logger.error("connection_error error=%s", exc)
    return {
        "error": "Failed to connect to TeamCity",
        "reason": str(exc),
    }


def not_found(entity_type: str, entity_id: str) -> dict[str, Any]:
    """Format a not-found error response."""
    return {"error": f"{entity_type} '{entity_id}' not found"}
