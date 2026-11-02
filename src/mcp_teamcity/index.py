"""In-memory index of all build configurations and projects, preloaded at startup.

Powers :func:`mcp_teamcity.tools.find_config.find_build_config`'s fuzzy search.
The index is loaded once on startup (blocking, so search is warm before the
server accepts requests) and refreshed on a background timer. A failed load
keeps the previous contents, records the error so the tool can report it, and
is retried with backoff instead of waiting for the next full interval.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
from rapidfuzz import fuzz, process, utils

from mcp_teamcity.client import TeamCityClient

logger = logging.getLogger(__name__)

# Page size for the bulk buildTypes / projects fetch.
_PAGE_SIZE = 500

# rapidfuzz matches below this score are dropped from results.
_SCORE_CUTOFF = 50
# Projects are an extra hint next to the config results; only show strong ones.
_PROJECT_SCORE_CUTOFF = 70

# Two results are reported as ambiguous when their primary scores are within
# _AMBIGUOUS_MARGIN and their name scores within _AMBIGUOUS_NAME_MARGIN.
_AMBIGUOUS_MARGIN = 5.0
_AMBIGUOUS_NAME_MARGIN = 10.0

# Retry delays after a failed load (seconds), capped by the refresh interval.
_RETRY_DELAYS = (5, 15, 30, 60, 120)

_ROOT_PROJECT = "_Root"


@dataclass
class BuildConfigEntry:
    """A build configuration in the in-memory index."""

    build_type_id: str
    name: str
    project_id: str | None
    project_name: str
    description: str | None
    web_url: str | None
    search_text: str


@dataclass
class ProjectEntry:
    """A project in the in-memory index."""

    project_id: str
    name: str
    path: str
    parent_project_id: str | None
    description: str | None
    web_url: str | None
    search_text: str


def describe_load_error(exc: BaseException) -> str:
    """Turn a load failure into a sentence the model can relay to the user."""
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status == 401:
            return "TeamCity rejected the access token (HTTP 401). Check TEAMCITY_TOKEN."
        if status == 403:
            return "The access token cannot list build configurations (HTTP 403). Give its user view permissions."
        return f"TeamCity returned HTTP {status} while listing build configurations."
    if isinstance(exc, httpx.RequestError):
        return f"Cannot reach TeamCity at TEAMCITY_BASE_URL: {type(exc).__name__}: {exc}"
    return f"{type(exc).__name__}: {exc}"


@dataclass
class BuildConfigIndex:
    """Preloaded index of all build configurations and projects for fuzzy search."""

    _entries: list[BuildConfigEntry] = field(default_factory=list)
    _search_texts: list[str] = field(default_factory=list)
    _projects: list[ProjectEntry] = field(default_factory=list)
    _project_texts: list[str] = field(default_factory=list)
    _loaded: bool = False
    _refresh_task: asyncio.Task[None] | None = None
    last_error: str | None = None
    last_loaded_at: float | None = None
    _failures: int = 0

    @property
    def loaded(self) -> bool:
        return self._loaded

    @property
    def size(self) -> int:
        return len(self._entries)

    @property
    def project_count(self) -> int:
        return len(self._projects)

    async def load(self, client: TeamCityClient) -> bool:
        """Fetch every build configuration and project, paginating until exhausted.

        Never raises — the server keeps running with whatever the index held
        before (empty on first load). Returns whether the load succeeded.
        """
        logger.info("index_loading_started")
        try:
            entries = await self._fetch_build_types(client)
            projects = await self._fetch_projects(client)
        except Exception as exc:  # noqa: BLE001 — any failure is reported, not raised
            self._failures += 1
            self.last_error = describe_load_error(exc)
            logger.error("index_loading_failed error=%s", self.last_error)
            return False

        self._entries = entries
        self._search_texts = [e.search_text for e in entries]
        self._projects = projects
        self._project_texts = [p.search_text for p in projects]
        self._loaded = True
        self._failures = 0
        self.last_error = None
        self.last_loaded_at = time.time()
        logger.info("index_loading_complete build_configs=%d projects=%d", len(entries), len(projects))
        return True

    async def _paginate(self, client: TeamCityClient, path: str, fields: str, key: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        start = 0
        while True:
            params = {"locator": f"count:{_PAGE_SIZE},start:{start}", "fields": fields}
            data = await client.get(path, params=params)
            if not isinstance(data, dict):
                break
            page = data.get(key, [])
            items.extend(page)
            if "nextHref" not in data or len(page) < _PAGE_SIZE:
                break
            start += _PAGE_SIZE
        return items

    async def _fetch_build_types(self, client: TeamCityClient) -> list[BuildConfigEntry]:
        raw = await self._paginate(
            client,
            "/app/rest/buildTypes",
            "count,nextHref,buildType(id,name,description,projectId,projectName,webUrl)",
            "buildType",
        )
        entries: list[BuildConfigEntry] = []
        seen: set[str] = set()
        for bt in raw:
            bt_id = bt.get("id")
            if not bt_id or bt_id in seen:
                continue
            seen.add(bt_id)
            name = bt.get("name") or ""
            project_name = bt.get("projectName") or ""
            entries.append(
                BuildConfigEntry(
                    build_type_id=bt_id,
                    name=name,
                    project_id=bt.get("projectId"),
                    project_name=project_name,
                    description=bt.get("description"),
                    web_url=bt.get("webUrl"),
                    search_text=f"{project_name} {name}".lower(),
                )
            )
        return entries

    async def _fetch_projects(self, client: TeamCityClient) -> list[ProjectEntry]:
        raw = await self._paginate(
            client,
            "/app/rest/projects",
            "count,nextHref,project(id,name,parentProjectId,description,webUrl,archived)",
            "project",
        )
        by_id = {p["id"]: p for p in raw if p.get("id")}

        def path_of(pid: str) -> str:
            names: list[str] = []
            current: str | None = pid
            for _ in range(50):  # guards against a malformed parent cycle
                if not current or current == _ROOT_PROJECT or current not in by_id:
                    break
                names.append(by_id[current].get("name") or current)
                current = by_id[current].get("parentProjectId")
            return " / ".join(reversed(names))

        projects: list[ProjectEntry] = []
        for pid, p in by_id.items():
            if pid == _ROOT_PROJECT or p.get("archived"):
                continue
            path = path_of(pid)
            projects.append(
                ProjectEntry(
                    project_id=pid,
                    name=p.get("name") or pid,
                    path=path,
                    parent_project_id=p.get("parentProjectId"),
                    description=p.get("description"),
                    web_url=p.get("webUrl"),
                    search_text=path.lower(),
                )
            )
        return projects

    def search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Fuzzy-search build configurations by name and project path.

        The primary score is ``token_set_ratio`` against ``"<project path>
        <name>"``. Short queries often tie at 100 (``api`` matches every
        config under an ``API`` project), so ties are broken by how well the
        query matches the configuration name alone, then by plain similarity,
        which prefers shorter, closer names.
        """
        if not self._entries:
            return []

        matches = process.extract(
            query,
            self._search_texts,
            scorer=fuzz.token_set_ratio,
            limit=None,
            score_cutoff=_SCORE_CUTOFF,
            processor=utils.default_process,
        )
        q = utils.default_process(query)
        ranked = []
        for _text, score, idx in matches:
            name = utils.default_process(self._entries[idx].name)
            ranked.append((score, fuzz.WRatio(q, name), fuzz.ratio(q, name), idx))
        ranked.sort(key=lambda r: (r[0], r[1], r[2]), reverse=True)

        results = []
        for score, name_score, _ratio, idx in ranked[:limit]:
            entry = self._entries[idx]
            results.append(
                {
                    "id": entry.build_type_id,
                    "name": entry.name,
                    "project_id": entry.project_id,
                    "project_name": entry.project_name,
                    "description": entry.description,
                    "web_url": entry.web_url,
                    "score": round(score, 1),
                    "name_score": round(name_score, 1),
                }
            )
        return results

    def search_projects(self, query: str, limit: int = 3) -> list[dict[str, Any]]:
        """Fuzzy-search projects by their full path."""
        if not self._projects:
            return []
        matches = process.extract(
            query,
            self._project_texts,
            scorer=fuzz.token_set_ratio,
            limit=None,
            score_cutoff=_PROJECT_SCORE_CUTOFF,
            processor=utils.default_process,
        )
        q = utils.default_process(query)
        # A parent's path is a token subset of its children's paths, so ties
        # are common; prefer the project whose full path is closest to the query.
        ranked = sorted(
            ((score, fuzz.ratio(q, self._project_texts[idx]), idx) for _t, score, idx in matches),
            reverse=True,
        )
        return [
            {
                "id": self._projects[idx].project_id,
                "name": self._projects[idx].name,
                "path": self._projects[idx].path,
                "parent_project_id": self._projects[idx].parent_project_id,
                "web_url": self._projects[idx].web_url,
                "score": round(score, 1),
            }
            for score, _r, idx in ranked[:limit]
        ]

    @staticmethod
    def is_ambiguous(results: list[dict[str, Any]]) -> bool:
        """True when the top two results score too close to pick one with confidence."""
        if len(results) < 2:
            return False
        a, b = results[0], results[1]
        close_overall = a["score"] - b["score"] < _AMBIGUOUS_MARGIN
        close_by_name = a.get("name_score", 0) - b.get("name_score", 0) < _AMBIGUOUS_NAME_MARGIN
        return close_overall and close_by_name

    async def start_background_refresh(self, client: TeamCityClient, interval: int) -> None:
        """Start a background task that reloads the index on a timer."""
        self._refresh_task = asyncio.create_task(self._refresh_loop(client, interval))

    def _next_delay(self, interval: int) -> float:
        if self._failures == 0:
            return interval
        return min(interval, _RETRY_DELAYS[min(self._failures, len(_RETRY_DELAYS)) - 1])

    async def _refresh_loop(self, client: TeamCityClient, interval: int) -> None:
        while True:
            await asyncio.sleep(self._next_delay(interval))
            logger.info("index_refresh_started")
            await self.load(client)

    async def stop(self) -> None:
        if self._refresh_task:
            self._refresh_task.cancel()
            try:
                await self._refresh_task
            except asyncio.CancelledError:
                pass
