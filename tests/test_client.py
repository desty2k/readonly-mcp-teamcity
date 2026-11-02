"""Tests for the TeamCity HTTP client (exercises the real httpx stack via respx)."""

from __future__ import annotations

import httpx
import pytest
import respx

from mcp_teamcity.client import TeamCityClient
from mcp_teamcity.settings import TeamCitySettings


@pytest.fixture
def settings() -> TeamCitySettings:
    return TeamCitySettings(base_url="https://teamcity.example.com", token="abc123")


@respx.mock
async def test_get_parses_json_and_sends_bearer(settings: TeamCitySettings) -> None:
    route = respx.get("https://teamcity.example.com/app/rest/server").mock(
        return_value=httpx.Response(200, json={"version": "2024.1"})
    )
    client = TeamCityClient(settings)
    try:
        data = await client.get("/app/rest/server")
        assert data == {"version": "2024.1"}
        assert route.called
        assert route.calls.last.request.headers["authorization"] == "Bearer abc123"
    finally:
        await client.close()


@respx.mock
async def test_get_passes_params(settings: TeamCitySettings) -> None:
    route = respx.get("https://teamcity.example.com/app/rest/builds").mock(
        return_value=httpx.Response(200, json={"count": 0, "build": []})
    )
    client = TeamCityClient(settings)
    try:
        await client.get("/app/rest/builds", params={"locator": "count:1"})
        assert route.calls.last.request.url.params["locator"] == "count:1"
    finally:
        await client.close()


@respx.mock
async def test_get_text_returns_body(settings: TeamCitySettings) -> None:
    respx.get("https://teamcity.example.com/downloadBuildLog.html").mock(
        return_value=httpx.Response(200, text="log line 1\nlog line 2")
    )
    client = TeamCityClient(settings)
    try:
        text = await client.get_text("/downloadBuildLog.html", params={"buildId": "9"})
        assert text == "log line 1\nlog line 2"
    finally:
        await client.close()


@respx.mock
async def test_get_raises_on_error_status(settings: TeamCitySettings) -> None:
    respx.get("https://teamcity.example.com/app/rest/server").mock(
        return_value=httpx.Response(500, text="server error")
    )
    client = TeamCityClient(settings)
    try:
        with pytest.raises(httpx.HTTPStatusError):
            await client.get("/app/rest/server")
    finally:
        await client.close()


# --- read-only guarantee ---------------------------------------------------


def test_client_exposes_only_read_methods() -> None:
    """The client's public surface is GET-only; adding a write method must fail this test."""
    public = {name for name in dir(TeamCityClient) if not name.startswith("_")}
    assert public == {"get", "get_text", "close"}


@respx.mock
async def test_client_only_sends_get_requests(settings: TeamCitySettings) -> None:
    route = respx.route(host="teamcity.example.com").mock(return_value=httpx.Response(200, json={}))
    client = TeamCityClient(settings)
    try:
        await client.get("/app/rest/server")
        await client.get_text("/downloadBuildLog.html", params={"buildId": "1"})
    finally:
        await client.close()
    assert route.call_count == 2
    assert {call.request.method for call in route.calls} == {"GET"}


def test_tools_reach_teamcity_only_through_the_client() -> None:
    """No tool module talks to httpx directly or calls a write verb on anything."""
    import pathlib
    import re

    src = pathlib.Path(__file__).parents[1] / "src" / "mcp_teamcity"
    write_call = re.compile(r"\.(post|put|patch|delete)\(|method=\"(POST|PUT|PATCH|DELETE)\"", re.IGNORECASE)
    offenders = []
    for path in src.rglob("*.py"):
        text = path.read_text()
        if write_call.search(text):
            offenders.append(path.name)
        if path.parent.name == "tools" and "httpx.AsyncClient" in text:
            offenders.append(path.name)
    assert offenders == []
