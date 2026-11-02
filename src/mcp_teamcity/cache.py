"""TTL cache for build logs, capped by size.

Both ``get_build_log`` and ``search_build_log`` need the full text of a build
log, which TeamCity only exposes as a single (potentially very large) download.
Caching the split lines for a short TTL means repeated queries against the same
build — paging through a log, then searching it — download it only once.

Two limits keep the cache honest:

- The cache holds at most ``max_bytes`` of log text (approximate, counted as
  characters plus a fixed per-line overhead). A log larger than that on its
  own is served but not cached.
- Logs of builds that have not finished are never cached: they are still
  growing, and a cached copy would hide new lines for the whole TTL.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from cachetools import TTLCache

from mcp_teamcity.client import TeamCityClient

logger = logging.getLogger(__name__)

# Rough per-line cost of a Python str object on top of its characters.
_LINE_OVERHEAD_BYTES = 56

DEFAULT_MAX_BYTES = 64 * 1024 * 1024
DEFAULT_TTL = 300


@dataclass(frozen=True)
class BuildLog:
    lines: list[str]
    finished: bool


def _approx_size(lines: list[str]) -> int:
    return sum(len(line) for line in lines) + _LINE_OVERHEAD_BYTES * len(lines)


class BuildLogCache:
    """TTL cache of finished build logs, keyed by build ID and capped by size."""

    def __init__(self, max_bytes: int = DEFAULT_MAX_BYTES, ttl: int = DEFAULT_TTL) -> None:
        self.max_bytes = max_bytes
        self._cache: TTLCache[str, list[str]] = TTLCache(maxsize=max_bytes, ttl=ttl, getsizeof=_approx_size)

    @property
    def size_bytes(self) -> int:
        return int(self._cache.currsize)

    async def get(self, client: TeamCityClient, build_id: str) -> BuildLog:
        """Return the build log split into lines, downloading on cache miss."""
        cached = self._cache.get(build_id)
        if cached is not None:
            return BuildLog(cached, finished=True)

        # Ask for the state before downloading: if the build is finished now,
        # the log we download next is final.
        state = await client.get(f"/app/rest/builds/id:{build_id}", params={"fields": "state"})
        finished = isinstance(state, dict) and state.get("state") == "finished"

        # plain=true forces text output rather than relying on content negotiation.
        full_log = await client.get_text("/downloadBuildLog.html", params={"buildId": build_id, "plain": "true"})
        lines = full_log.splitlines()

        if not finished:
            logger.debug("build_log_not_cached build_id=%s reason=running", build_id)
        elif _approx_size(lines) > self.max_bytes:
            logger.info("build_log_not_cached build_id=%s reason=too_large line_count=%d", build_id, len(lines))
        else:
            self._cache[build_id] = lines
            logger.debug("build_log_cached build_id=%s line_count=%d", build_id, len(lines))
        return BuildLog(lines, finished=finished)

    async def get_lines(self, client: TeamCityClient, build_id: str) -> list[str]:
        return (await self.get(client, build_id)).lines
