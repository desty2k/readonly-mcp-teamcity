"""Shared fixtures for all tests."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from mcp_teamcity.cache import BuildLogCache
from mcp_teamcity.client import TeamCityClient
from mcp_teamcity.index import BuildConfigIndex
from mcp_teamcity.server import AppContext
from mcp_teamcity.settings import TeamCitySettings


@pytest.fixture
def settings() -> TeamCitySettings:
    return TeamCitySettings(
        base_url="https://teamcity.example.com",
        token="test-token",
        transport="stdio",
        log_format="text",
        log_level="DEBUG",
    )


@pytest.fixture
def mock_client() -> TeamCityClient:
    """A fully mocked TeamCityClient where .get()/.get_text() are AsyncMocks."""
    client = MagicMock(spec=TeamCityClient)
    client.get = AsyncMock()
    client.get_text = AsyncMock()
    client.close = AsyncMock()
    return client


@pytest.fixture
def build_config_index() -> BuildConfigIndex:
    return BuildConfigIndex()


@pytest.fixture
def log_cache() -> BuildLogCache:
    return BuildLogCache()


@pytest.fixture
def app_context(mock_client: TeamCityClient, settings: TeamCitySettings) -> AppContext:
    return AppContext(
        client=mock_client,
        settings=settings,
        build_config_index=BuildConfigIndex(),
        log_cache=BuildLogCache(),
    )


@pytest.fixture
def mock_ctx(app_context: AppContext) -> MagicMock:
    """A mock FastMCP Context with lifespan_context set to app_context."""
    ctx = MagicMock()
    ctx.lifespan_context = app_context
    return ctx


# --- response builders -------------------------------------------------------


def make_build_response(builds: list[dict[str, Any]] | None = None, **extra: Any) -> dict[str, Any]:
    """Build a TeamCity /app/rest/builds list response."""
    if builds is None:
        builds = [
            {
                "id": 12345,
                "number": "1.2.3",
                "status": "SUCCESS",
                "state": "finished",
                "branchName": "main",
                "defaultBranch": True,
                "startDate": "20240101T000000+0000",
                "finishDate": "20240101T000500+0000",
                "buildType": {"id": "Proj_Build", "name": "Build", "projectId": "Proj"},
                "triggered": {"type": "user", "user": {"username": "alice", "name": "Alice"}},
            }
        ]
    return {"count": len(builds), "build": builds, **extra}


def make_project_response(projects: list[dict[str, Any]] | None = None, **extra: Any) -> dict[str, Any]:
    """Build a TeamCity /app/rest/projects list response."""
    if projects is None:
        projects = [
            {
                "id": "Proj",
                "name": "My Project",
                "description": "A project",
                "archived": False,
                "parentProjectId": "_Root",
                "buildTypes": {"count": 3},
                "projects": {"count": 1},
            }
        ]
    return {"count": len(projects), "project": projects, **extra}
