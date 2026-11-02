"""Tests for the build-configuration fuzzy index."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx

from mcp_teamcity.client import TeamCityClient
from mcp_teamcity.index import BuildConfigEntry, BuildConfigIndex


def _entry(bt_id: str, name: str, project_name: str) -> BuildConfigEntry:
    return BuildConfigEntry(
        build_type_id=bt_id,
        name=name,
        project_id="Proj",
        project_name=project_name,
        description=None,
        web_url=f"https://tc/{bt_id}",
        search_text=f"{project_name} {name}".lower(),
    )


def _populate(index: BuildConfigIndex, entries: list[BuildConfigEntry]) -> None:
    index._entries = entries
    index._search_texts = [e.search_text for e in entries]
    index._loaded = True


def test_search_empty_index_returns_empty() -> None:
    index = BuildConfigIndex()
    assert index.search("anything") == []


def test_search_ranks_relevant_match_first() -> None:
    index = BuildConfigIndex()
    _populate(
        index,
        [
            _entry("Payments_DeployProd", "Deploy Prod", "Payments / API"),
            _entry("Billing_NightlyTest", "Nightly Test", "Billing"),
        ],
    )
    results = index.search("deploy api prod", limit=5)
    assert results
    assert results[0]["id"] == "Payments_DeployProd"
    assert results[0]["score"] >= 50
    assert "web_url" in results[0]


def test_search_respects_limit() -> None:
    index = BuildConfigIndex()
    _populate(index, [_entry(f"C{i}", "Deploy Prod", "Payments") for i in range(10)])
    results = index.search("deploy prod", limit=3)
    assert len(results) <= 3


async def test_load_paginates_and_dedupes() -> None:
    client = MagicMock(spec=TeamCityClient)
    client.get = AsyncMock(
        return_value={
            "count": 2,
            "buildType": [
                {"id": "A", "name": "Build A", "projectName": "Proj", "webUrl": "u"},
                {"id": "A", "name": "Build A dup", "projectName": "Proj", "webUrl": "u"},
                {"id": "B", "name": "Build B", "projectName": "Proj", "webUrl": "u"},
            ],
        }
    )
    index = BuildConfigIndex()
    await index.load(client)
    assert index.loaded is True
    # 'A' is deduped, so only A and B remain.
    assert index.size == 2


async def test_load_never_crashes_on_error() -> None:
    client = MagicMock(spec=TeamCityClient)
    client.get = AsyncMock(side_effect=RuntimeError("boom"))
    index = BuildConfigIndex()
    await index.load(client)  # must not raise
    assert index.loaded is False
    assert index.size == 0


def test_short_query_ties_are_broken_by_name() -> None:
    index = BuildConfigIndex()
    _populate(
        index,
        [
            _entry("Api_DeployStaging", "API – deploy staging", "Payments / API"),
            _entry("Api_DeployProduction", "API – deploy production", "Payments / API"),
            _entry("Api_Build", "API – build", "Payments / API"),
        ],
    )
    results = index.search("api", limit=3)
    # All three score 100 on the project path; the shortest, closest name wins.
    assert [r["score"] for r in results] == [100.0, 100.0, 100.0]
    assert results[0]["id"] == "Api_Build"


def test_reordered_words_prefer_the_better_name_match() -> None:
    index = BuildConfigIndex()
    _populate(
        index,
        [
            _entry("Api_DeployStaging", "API – deploy staging", "Payments / API"),
            _entry("Api_DeployProduction", "API – deploy production", "Payments / API"),
        ],
    )
    results = index.search("prod deploy payments", limit=2)
    assert results[0]["id"] == "Api_DeployProduction"


def test_ambiguity_flag() -> None:
    index = BuildConfigIndex()
    _populate(
        index,
        [
            _entry("A_Unit", "auth-service unit tests", "Identity"),
            _entry("A_Integration", "auth-service integration tests", "Identity"),
            _entry("Docs", "Docs site build", "Platform"),
        ],
    )
    assert index.is_ambiguous(index.search("auth-service tests"))
    assert not index.is_ambiguous(index.search("docs site"))


def _status_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://tc/app/rest/buildTypes")
    return httpx.HTTPStatusError("err", request=request, response=httpx.Response(status, request=request))


async def test_load_records_a_readable_error() -> None:
    client = MagicMock(spec=TeamCityClient)
    client.get = AsyncMock(side_effect=_status_error(401))
    index = BuildConfigIndex()
    assert await index.load(client) is False
    assert "401" in index.last_error
    assert "TEAMCITY_TOKEN" in index.last_error

    client.get = AsyncMock(side_effect=httpx.ConnectError("connection refused"))
    await index.load(client)
    assert "Cannot reach TeamCity" in index.last_error


async def test_failed_refresh_keeps_old_entries_and_retries_sooner() -> None:
    index = BuildConfigIndex()
    _populate(index, [_entry("A", "Build A", "Proj")])
    client = MagicMock(spec=TeamCityClient)
    client.get = AsyncMock(side_effect=_status_error(503))
    await index.load(client)
    assert index.loaded and index.size == 1
    assert index._next_delay(300) == 5
    await index.load(client)
    assert index._next_delay(300) == 15
    assert index._next_delay(10) == 10


async def test_load_indexes_projects_with_full_paths() -> None:
    async def fake_get(path, params=None):
        if path == "/app/rest/buildTypes":
            return {"buildType": [{"id": "Pay_Api_Build", "name": "Build", "projectName": "Payments / API"}]}
        return {
            "project": [
                {"id": "_Root", "name": "<Root project>"},
                {"id": "Pay", "name": "Payments", "parentProjectId": "_Root"},
                {"id": "Pay_Api", "name": "API", "parentProjectId": "Pay"},
                {"id": "Old", "name": "Old stuff", "parentProjectId": "_Root", "archived": True},
            ]
        }

    client = MagicMock(spec=TeamCityClient)
    client.get = AsyncMock(side_effect=fake_get)
    index = BuildConfigIndex()
    await index.load(client)
    assert index.project_count == 2
    found = index.search_projects("payments api")
    assert found[0]["id"] == "Pay_Api"
    assert found[0]["path"] == "Payments / API"
