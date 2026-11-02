# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/), and this project adheres to
[Semantic Versioning](https://semver.org/).

## [1.0.1] - 2026-11-03

### Changed

- The README, the PyPI page and the MCP Registry entry link to the blog post
  about this server.

## [1.0.0] - 2026-11-02

First public release: a read-only MCP server for JetBrains TeamCity with 29
tools across projects, build configurations, builds, logs, tests, problems,
investigations, mutes, the queue, agents, artifacts, VCS changes, URL
resolution, and server status and health.

### Highlights

- Every request is a `GET`; tests fail if the client gains another method.
  Every tool is annotated `readOnlyHint`.
- `diagnose_build` answers "why did this build fail?" in one call: build
  problems, failed tests with details (unmuted first), failed snapshot
  dependencies, and the log lines TeamCity marked as errors plus lines with
  error keywords, with context.
- Fuzzy build-configuration search (`find_build_config`) backed by an in-memory
  index of configurations and projects, preloaded at startup and refreshed in
  the background. Close matches are flagged as ambiguous.
- TeamCity web-URL resolver (`resolve_teamcity_url`) for modern, short and
  legacy URLs.
- Build logs with pagination, tail and full-text search, served from a
  size-capped cache that never holds a running build's log.
- Build artifacts: browse the tree and read text artifacts with line and
  per-line bounds.
- Build-chain traversal, muted-test listing, per-agent details, and combined
  server health and metrics.
- IDs are validated and free text is escaped before it reaches a locator;
  artifact paths cannot contain `..`.
- Structured JSON or text logging, optional OpenTelemetry tracing, stdio, HTTP
  and SSE transports (HTTP and SSE bind 127.0.0.1 by default), and a Docker
  image.
- Python 3.11 or newer.

### Fixed before release (found against a live TeamCity 2026.2)

- `search_builds` without `branch` returned default-branch builds only.
- `search_changes` with a commit SHA in `since_change` failed with HTTP 400.
- `get_build_log` returned the whole range when both `start_line` and
  `end_line` were given, ignoring `max_lines`.
- Agent OS name was always empty.
