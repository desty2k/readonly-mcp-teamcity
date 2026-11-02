"""Pagination helpers.

TeamCity list responses carry ``nextHref`` / ``prevHref`` fields when more pages
exist. Tools request those fields and translate the user-facing ``page`` /
``limit`` into TeamCity's ``start`` / ``count`` locator dimensions.
"""

from __future__ import annotations

from typing import Any


def build_pagination(page: int, limit: int, data: dict[str, Any]) -> dict[str, Any]:
    """Build standard pagination metadata from a TeamCity list response.

    ``has_next_page`` follows TeamCity's documented pagination contract — the
    presence of ``nextHref`` in the response (callers must request it in
    ``fields``). ``has_prev_page`` is derived from the 1-indexed page rather than
    ``prevHref``, which the API does not guarantee on every response.
    """
    page = max(1, page)
    return {
        "page": page,
        "limit": limit,
        "has_next_page": "nextHref" in data,
        "has_prev_page": page > 1,
    }


def clamp_limit(limit: int | None, default: int = 50, max_limit: int = 500) -> int:
    """Clamp a limit value to safe bounds."""
    if limit is None:
        return default
    return max(1, min(limit, max_limit))
