"""Tests for pagination helpers."""

from __future__ import annotations

from mcp_teamcity.pagination import build_pagination, clamp_limit


def test_clamp_limit_default_when_none() -> None:
    assert clamp_limit(None, default=50, max_limit=500) == 50


def test_clamp_limit_upper_bound() -> None:
    assert clamp_limit(10_000, default=50, max_limit=500) == 500


def test_clamp_limit_lower_bound() -> None:
    assert clamp_limit(0, default=50, max_limit=500) == 1
    assert clamp_limit(-5, default=50, max_limit=500) == 1


def test_clamp_limit_passthrough() -> None:
    assert clamp_limit(25, default=50, max_limit=500) == 25


def test_build_pagination_next_and_prev() -> None:
    meta = build_pagination(2, 50, {"nextHref": "/x", "prevHref": "/y"})
    assert meta == {"page": 2, "limit": 50, "has_next_page": True, "has_prev_page": True}


def test_build_pagination_no_more_pages() -> None:
    meta = build_pagination(1, 50, {})
    assert meta["has_next_page"] is False
    assert meta["has_prev_page"] is False


def test_build_pagination_clamps_page() -> None:
    meta = build_pagination(0, 50, {})
    assert meta["page"] == 1
