"""TeamCity URL parser — converts web UI URLs to structured identifiers.

Supports both modern and legacy TeamCity URL formats:
- Modern: /project/X, /buildConfiguration/X, /buildConfiguration/X/123
- Short: /build/123, /change/45 (the web URLs TeamCity's REST API returns for
  queued builds and changes)
- Legacy: /viewLog.html?buildId=X, /viewType.html?buildTypeId=X,
  /project.html?projectId=X
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlparse


@dataclass
class ParsedTeamCityURL:
    """Result of parsing a TeamCity web URL."""

    url_type: str  # "project" | "build_config" | "build" | "build_log" | "change" | "unknown"
    project_id: str | None = None
    build_type_id: str | None = None
    build_id: str | None = None
    change_id: str | None = None
    tab: str | None = None
    extra: dict[str, str] = field(default_factory=dict)


# Modern URL patterns.
_PROJECT_RE = re.compile(r"/project/(?P<project_id>[A-Za-z0-9_]+)")
_BUILD_RE = re.compile(r"/buildConfiguration/(?P<build_type_id>[A-Za-z0-9_]+)/(?P<build_id>\d+)")
_BUILD_CONFIG_RE = re.compile(r"/buildConfiguration/(?P<build_type_id>[A-Za-z0-9_]+)")

# Short URL patterns.
_SHORT_BUILD_RE = re.compile(r"/build/(?P<build_id>\d+)/?$")
_CHANGE_RE = re.compile(r"/change/(?P<change_id>\d+)/?$")

# Legacy URL patterns.
_PROJECT_HTML_RE = re.compile(r"/project\.html$")
_VIEW_LOG_RE = re.compile(r"/viewLog\.html")
_VIEW_TYPE_RE = re.compile(r"/viewType\.html")


def _first_qs(query: dict[str, list[str]], key: str) -> str | None:
    """Extract the first value from a parsed query-string dict."""
    values = query.get(key)
    return values[0] if values else None


def parse_teamcity_url(url: str) -> ParsedTeamCityURL:
    """Parse a TeamCity web UI URL into structured identifiers.

    Handles both new-style (/project/X, /buildConfiguration/X/123) and legacy
    URLs (/viewLog.html?buildId=X, /viewType.html?buildTypeId=X).

    Args:
        url: Full TeamCity URL from the browser address bar.

    Returns:
        ParsedTeamCityURL with extracted identifiers.
    """
    parsed = urlparse(url)
    path = parsed.path
    query = parse_qs(parsed.query)

    # Modern: /buildConfiguration/{btId}/{buildId}
    m = _BUILD_RE.search(path)
    if m:
        return ParsedTeamCityURL(
            url_type="build",
            build_type_id=m.group("build_type_id"),
            build_id=m.group("build_id"),
            tab=_first_qs(query, "buildTab"),
        )

    # Modern: /buildConfiguration/{btId}
    m = _BUILD_CONFIG_RE.search(path)
    if m:
        return ParsedTeamCityURL(
            url_type="build_config",
            build_type_id=m.group("build_type_id"),
        )

    # Modern: /project/{projectId}
    m = _PROJECT_RE.search(path)
    if m:
        return ParsedTeamCityURL(
            url_type="project",
            project_id=m.group("project_id"),
        )

    # Short: /build/{buildId}
    m = _SHORT_BUILD_RE.search(path)
    if m:
        return ParsedTeamCityURL(url_type="build", build_id=m.group("build_id"), tab=_first_qs(query, "buildTab"))

    # Short: /change/{changeId}
    m = _CHANGE_RE.search(path)
    if m:
        return ParsedTeamCityURL(url_type="change", change_id=m.group("change_id"))

    # Legacy: /project.html?projectId=X
    if _PROJECT_HTML_RE.search(path) and _first_qs(query, "projectId"):
        return ParsedTeamCityURL(url_type="project", project_id=_first_qs(query, "projectId"))

    # Legacy: /viewLog.html?buildId=X&buildTypeId=Y
    if _VIEW_LOG_RE.search(path):
        return ParsedTeamCityURL(
            url_type="build_log",
            build_id=_first_qs(query, "buildId"),
            build_type_id=_first_qs(query, "buildTypeId"),
            tab=_first_qs(query, "tab"),
        )

    # Legacy: /viewType.html?buildTypeId=X
    if _VIEW_TYPE_RE.search(path):
        return ParsedTeamCityURL(
            url_type="build_config",
            build_type_id=_first_qs(query, "buildTypeId"),
        )

    return ParsedTeamCityURL(url_type="unknown")
