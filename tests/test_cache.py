"""Tests for the build-log TTL cache."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from mcp_teamcity.cache import BuildLogCache
from mcp_teamcity.client import TeamCityClient


def _client(*logs: str, state: str = "finished") -> MagicMock:
    client = MagicMock(spec=TeamCityClient)
    client.get = AsyncMock(return_value={"state": state})
    client.get_text = AsyncMock(side_effect=list(logs))
    return client


async def test_get_lines_splits_log() -> None:
    client = _client("line1\nline2\nline3")
    lines = await BuildLogCache().get_lines(client, "123")
    assert lines == ["line1", "line2", "line3"]


async def test_finished_build_log_is_cached() -> None:
    client = _client("a\nb")
    cache = BuildLogCache()

    first = await cache.get(client, "123")
    second = await cache.get(client, "123")

    assert first.lines == second.lines == ["a", "b"]
    assert first.finished and second.finished
    # Second call served from cache — no second download.
    client.get_text.assert_awaited_once()


async def test_running_build_log_is_not_cached() -> None:
    client = _client("a", "a\nb", state="running")
    cache = BuildLogCache()

    first = await cache.get(client, "7")
    second = await cache.get(client, "7")

    assert first.lines == ["a"]
    assert second.lines == ["a", "b"]
    assert not second.finished
    assert client.get_text.await_count == 2
    assert cache.size_bytes == 0


async def test_unknown_state_is_treated_as_running() -> None:
    client = _client("a", "a")
    client.get = AsyncMock(return_value=None)
    cache = BuildLogCache()
    await cache.get(client, "7")
    await cache.get(client, "7")
    assert client.get_text.await_count == 2


async def test_log_larger_than_cap_is_served_but_not_cached() -> None:
    big = "\n".join("x" * 100 for _ in range(100))
    client = _client(big, big)
    cache = BuildLogCache(max_bytes=1000)

    result = await cache.get(client, "1")
    await cache.get(client, "1")

    assert len(result.lines) == 100
    assert client.get_text.await_count == 2
    assert cache.size_bytes == 0


async def test_byte_cap_evicts_older_logs() -> None:
    log = "\n".join("y" * 100 for _ in range(10))  # about 1.5 KB
    client = _client(log, log, log, log)
    cache = BuildLogCache(max_bytes=4000)

    await cache.get(client, "1")
    await cache.get(client, "2")
    await cache.get(client, "3")

    assert cache.size_bytes <= 4000
    await cache.get(client, "1")  # evicted, downloaded again
    assert client.get_text.await_count == 4


async def test_distinct_builds_download_separately() -> None:
    client = _client("log-a", "log-b")
    cache = BuildLogCache()

    a = await cache.get_lines(client, "1")
    b = await cache.get_lines(client, "2")

    assert a == ["log-a"]
    assert b == ["log-b"]
    assert client.get_text.await_count == 2
