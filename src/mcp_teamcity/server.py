"""FastMCP server with lifespan, instructions, and tool registration."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from mcp_teamcity import __version__
from mcp_teamcity.cache import BuildLogCache
from mcp_teamcity.client import TeamCityClient
from mcp_teamcity.index import BuildConfigIndex
from mcp_teamcity.settings import TeamCitySettings

logger = logging.getLogger(__name__)

MCP_INSTRUCTIONS = """\
Read-only access to a JetBrains TeamCity CI/CD server. This server can search and \
inspect projects, build configurations, builds, build logs, test results, build \
problems, investigations, the build queue, agents, and VCS changes. It cannot \
trigger, cancel, pin, tag, or modify anything — every operation is a read.

## TeamCity Hierarchy

**Project** → contains **Build Configurations** → each produces **Builds** (runs).

- **Project**: Organizational container. Projects nest (parent/child). The root \
project `_Root` contains all top-level projects. A project has a stable ID (e.g. \
`MyProject`) and a display name that can change.
- **Build Configuration** (a.k.a. "build type" or "job"): Defines WHAT to build \
and HOW — steps, triggers, parameters, VCS roots. Has a globally unique build \
type ID (e.g. `MyProject_Build`).
- **Build**: A single run of a configuration. Has a numeric build ID (globally \
unique) and a build number (a display string like "1.2.3-456", scoped to its \
configuration).

## ID vs Name vs URL

Users may identify entities by ID, by name, or by a web URL:
- **IDs** (`MyProject`, `MyProject_Deploy`, `12345`) — use directly in tools.
- **Names** ("My Project", "Deploy to Prod") — resolve with search/fuzzy tools.
- **URLs** — call `resolve_teamcity_url` FIRST to extract IDs, then query.

## Finding Build Configurations

- **Structured search** (`search_build_configs`): filter by exact project ID, \
build type ID, or paused state. Best when you know the project or identifier.
- **Fuzzy search** (`find_build_config`): match free-text against every \
configuration name and its full project path. Best for vague descriptions, \
abbreviations, or partial names. Results carry a relevance score.

## Build Status Values

- **SUCCESS** — all steps passed.
- **FAILURE** — a step or test failed.
- **ERROR** — infrastructure failure (agent issue, timeout, OOM).
- **UNKNOWN** — running or not yet determined.

A build can be both running and carry a preliminary status that may change when \
it finishes.

## Data Interpretation

- Empty results mean no matches were found, not zero — never conclude a \
configuration has no builds from an empty result.
- Build numbers are display strings, not sequential integers; do not do \
arithmetic on them. Order by build ID.
- Durations are in milliseconds; convert for the user.
- Timestamps use TeamCity's ISO 8601 form (yyyyMMdd'T'HHmmss±ZZZZ).

## Branch Handling

- The default branch is `<default>` in the API (usually `main`/`master`).
- Branch names are case-sensitive.

## Investigating Failures

To understand WHY a build failed, start with `diagnose_build`: it returns the \
build problems, failed tests and the error lines of the log in one call. The \
structured tools behind it are `get_build_problems` (compilation/exit-code/\
dependency failures) and `get_build_test_results` (failed tests). Logs can be \
100K+ lines: jump to matches with `search_build_log`, or page through \
`get_build_log`. The last lines of a log are usually TeamCity's own finishing \
steps (artifact publishing), not the error.
"""


# Every tool only reads. Clients use these hints to auto-approve read-only
# tools; openWorldHint because results come from an external system.
READ_ONLY_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=True,
)


class _ReadOnlyRegistrar:
    """Passes tool registrations through to FastMCP with read-only annotations."""

    def __init__(self, mcp: FastMCP) -> None:
        self._mcp = mcp

    def tool(self, *args: Any, **kwargs: Any) -> Any:
        kwargs.setdefault("annotations", READ_ONLY_ANNOTATIONS)
        return self._mcp.tool(*args, **kwargs)


@dataclass
class AppContext:
    """Shared application state available to all tools."""

    client: TeamCityClient
    settings: TeamCitySettings
    build_config_index: BuildConfigIndex
    log_cache: BuildLogCache


def create_server(settings: TeamCitySettings | None = None) -> FastMCP:
    """Build and return the configured FastMCP server."""
    if settings is None:
        settings = TeamCitySettings()  # type: ignore[call-arg]

    @asynccontextmanager
    async def lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
        logger.info("server_starting transport=%s", settings.transport)

        client = TeamCityClient(settings)
        index = BuildConfigIndex()
        log_cache = BuildLogCache(max_bytes=settings.log_cache_max_bytes, ttl=settings.log_cache_ttl)

        # Preload the build-config index so fuzzy search is warm, then keep it
        # fresh in the background.
        await index.load(client)
        await index.start_background_refresh(client, settings.index_refresh_interval)

        logger.info("server_ready build_configs_indexed=%d", index.size)

        try:
            yield AppContext(
                client=client,
                settings=settings,
                build_config_index=index,
                log_cache=log_cache,
            )
        finally:
            await index.stop()
            await client.close()
            logger.info("server_stopped")

    mcp = FastMCP(
        "TeamCity CI/CD",
        version=__version__,
        instructions=MCP_INSTRUCTIONS,
        lifespan=lifespan,
    )

    # Register all tool modules. Imported here (not at module scope) to avoid
    # import-time cycles with the server module.
    from mcp_teamcity.tools import (
        agents,
        artifacts,
        build_configs,
        build_logs,
        builds,
        changes,
        diagnose,
        find_config,
        problems,
        projects,
        queue,
        server_info,
        tests,
        url_resolve,
    )

    for module in [
        projects,
        build_configs,
        builds,
        build_logs,
        tests,
        problems,
        queue,
        agents,
        changes,
        artifacts,
        diagnose,
        find_config,
        url_resolve,
        server_info,
    ]:
        module.register(_ReadOnlyRegistrar(mcp))

    return mcp
