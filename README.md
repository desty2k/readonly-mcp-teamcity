# readonly-mcp-teamcity

[![CI](https://github.com/desty2k/readonly-mcp-teamcity/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/desty2k/readonly-mcp-teamcity/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/readonly-mcp-teamcity.svg)](https://pypi.org/project/readonly-mcp-teamcity/)
[![Python](https://img.shields.io/pypi/pyversions/readonly-mcp-teamcity.svg)](https://pypi.org/project/readonly-mcp-teamcity/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A read-only Model Context Protocol (MCP) server that lets AI agents explore a
JetBrains TeamCity server: projects, build configurations, builds, logs, test
results, problems, the queue, agents, and VCS changes. 29 tools, all of them
reads.

## Quick start

With [uv](https://docs.astral.sh/uv/) installed, there is nothing else to install:

```bash
claude mcp add teamcity \
  -e TEAMCITY_BASE_URL=https://teamcity.example.com \
  -e TEAMCITY_TOKEN=your-token \
  -- uvx readonly-mcp-teamcity
```

`uvx` downloads the package into a cached, isolated environment and runs it.
Python 3.11 or newer.

<!-- mcp-name: io.github.desty2k/teamcity -->

> **Read-only by design.** This server only ever issues `GET` requests (a test
> fails if the HTTP client gains any other method). It cannot trigger, cancel,
> pin, tag, or modify anything in TeamCity, and every tool is annotated
> `readOnlyHint`. Scope the token read-only on the TeamCity side as a second
> line of defense: see [Token](#token). Read
> [why I build read-only MCP servers](https://blog.wentland.io/blog/why-read-only-mcp/).

## Token

Create a token under **Profile → Access Tokens**. Set **Permissions scope** to
**Limit per project**, pick the root project (or the projects the agent should
see), and choose the **Read-only** preset. A token scoped that way cannot
change anything even if a client misbehaves.

The Read-only preset selects the 14 `VIEW_*` permissions TeamCity marks as
read-only, including global ones for agent details and server settings. A
token never gets more than its owner has: with a token from a user who has only
the Project viewer role, agent tools still work, and `get_server_health`
reports metrics as unavailable but still returns health items. Checked against
TeamCity 2026.2.1, where a preset token could not pin a build (HTTP 403).

## Tools

### Projects

| Tool | Description |
|------|-------------|
| `search_projects` | Search projects by name, ID, or parent; browse the hierarchy. |
| `get_project_details` | Full project: child projects, build configs, parameters. |

### Build configurations

| Tool | Description |
|------|-------------|
| `search_build_configs` | Structured search by project ID, build type ID, or paused state. |
| `find_build_config` | Fuzzy search across config names and project paths; flags ambiguous matches and lists matching projects. |
| `get_build_config_details` | Steps, triggers, parameters, VCS roots, settings, agent requirements. |
| `get_build_config_branches` | Branches a configuration can build, with default/active status. |

### Builds

| Tool | Description |
|------|-------------|
| `search_builds` | Search build history filtered by config, project, status, branch, date, etc. |
| `get_build_details` | One build: status, agent, revisions, parameters, dependencies, test summary, tags. |
| `get_build_statistics` | Numeric metrics: durations, test counts, coverage, artifact size. |
| `get_build_chain` | Snapshot-dependency chain upstream (depends-on) and downstream (dependents). |

### Logs

| Tool | Description |
|------|-------------|
| `get_build_log` | Paginated log retrieval with `tail` and line-range support. |
| `search_build_log` | Full-text search within a build log, with surrounding context. |

### Tests & problems

| Tool | Description |
|------|-------------|
| `diagnose_build` | Why a build failed, in one call: problems, failed tests (unmuted first) and the error lines of the log. |
| `get_build_test_results` | Test occurrences for a build, filterable by status. |
| `get_test_details` | One test occurrence: failure reason, history brackets, mute/investigation state. |
| `get_build_problems` | Structured failure reasons (compilation, exit code, dependency). |
| `search_investigations` | Active investigations by project, build config, or assignee. |
| `list_muted_tests` | Currently muted tests with scope, who muted them, and why. |

### Infrastructure

| Tool | Description |
|------|-------------|
| `get_build_queue` | Builds waiting for an agent, with wait reasons. |
| `search_agents` | Build agents with connection/authorization/enabled state and current build. |
| `list_agent_pools` | Agent pools with agent and project counts. |
| `get_agent_details` | One agent's state with enabled/authorized comments, last activity, current build. |
| `list_build_artifacts` | Browse a build's artifact tree (one directory level). |
| `get_build_artifact_content` | Read a text artifact (size-capped, line-paginated). |
| `search_changes` | VCS changes (commits) by build, config, project, committer, or since-commit. |
| `get_change_details` | One change with its full modified-file list. |
| `resolve_teamcity_url` | Parse a TeamCity web URL into project / build-config / build / change IDs. |
| `get_server_info` | TeamCity version, build number, and uptime. |
| `get_server_health` | Server health items + runtime metrics (CPU, memory, queue). |

## Install

Run it without installing (recommended):

```bash
uvx readonly-mcp-teamcity
```

Or install it into an environment:

```bash
uv tool install readonly-mcp-teamcity   # or: pip install readonly-mcp-teamcity
```

## Docker

The image serves the streamable HTTP transport on port 8080. That transport has
no authentication, so publish it on the host's loopback only:

```bash
docker run --rm \
  -e TEAMCITY_BASE_URL=https://teamcity.example.com \
  -e TEAMCITY_TOKEN=your-token \
  -p 127.0.0.1:8080:8080 \
  ghcr.io/desty2k/readonly-mcp-teamcity:latest
```

## Configuration

All configuration comes from `TEAMCITY_*` environment variables.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TEAMCITY_BASE_URL` | yes | — | TeamCity server base URL (e.g. `https://teamcity.example.com`). |
| `TEAMCITY_TOKEN` | yes | — | REST API bearer token. See [Token](#token). |
| `TEAMCITY_TIMEOUT` | no | `30` | HTTP request timeout (seconds). |
| `TEAMCITY_MAX_RETRIES` | no | `3` | Retries for transient network / 5xx errors. |
| `TEAMCITY_POOL_MAX_CONNECTIONS` | no | `20` | httpx connection-pool size. |
| `TEAMCITY_DEFAULT_LIMIT` | no | `50` | Default page size for list tools. |
| `TEAMCITY_MAX_LIMIT` | no | `500` | Maximum page size. |
| `TEAMCITY_INDEX_REFRESH_INTERVAL` | no | `300` | Seconds between fuzzy-index refreshes. A failed load is retried sooner. |
| `TEAMCITY_LOG_CACHE_MAX_BYTES` | no | `67108864` | Size cap of the build-log cache. Logs of running builds are never cached. |
| `TEAMCITY_LOG_CACHE_TTL` | no | `300` | Seconds a finished build's log stays cached. |
| `TEAMCITY_TRANSPORT` | no | `stdio` | `stdio`, `http`, or `sse`. |
| `TEAMCITY_HTTP_HOST` | no | `127.0.0.1` | Bind address for `http`/`sse`. These transports have no authentication; a non-loopback address logs a warning. |
| `TEAMCITY_HTTP_PORT` | no | `8080` | Port for the `http`/`sse` transports. |
| `TEAMCITY_LOG_FORMAT` | no | `json` | `json` (production) or `text` (local dev). |
| `TEAMCITY_LOG_LEVEL` | no | `INFO` | `DEBUG`, `INFO`, `WARNING`, or `ERROR`. |

See [`.env.example`](.env.example) for a copy-paste template.

## OpenTelemetry tracing

Tracing is opt-in and a no-op when disabled. The base install carries no OTel
SDK; install the extra and enable it to export spans for each upstream TeamCity
call:

```bash
pip install 'readonly-mcp-teamcity[otel]'
export TEAMCITY_OTEL_ENABLED=true
export TEAMCITY_OTEL_ENDPOINT=http://localhost:4317   # optional; falls back to OTEL_EXPORTER_OTLP_ENDPOINT
```

| Variable | Default | Description |
|----------|---------|-------------|
| `TEAMCITY_OTEL_ENABLED` | `false` | Master switch for tracing. |
| `TEAMCITY_OTEL_SERVICE_NAME` | `readonly-mcp-teamcity` | `service.name` on every span. |
| `TEAMCITY_OTEL_ENDPOINT` | unset | OTLP collector endpoint. |
| `TEAMCITY_OTEL_PROTOCOL` | `grpc` | `grpc` or `http/protobuf`. |
| `TEAMCITY_OTEL_CONSOLE_EXPORT` | `false` | Also print spans to stderr. |

## MCP client configuration

### Claude Desktop

Add to `claude_desktop_config.json` (`~/Library/Application Support/Claude/` on
macOS, `%APPDATA%\Claude\` on Windows):

```json
{
  "mcpServers": {
    "teamcity": {
      "command": "uvx",
      "args": ["readonly-mcp-teamcity"],
      "env": {
        "TEAMCITY_BASE_URL": "https://teamcity.example.com",
        "TEAMCITY_TOKEN": "your-token"
      }
    }
  }
}
```

### Claude Code

See [Quick start](#quick-start).

## How it compares

As of November 2026. Check the projects themselves before relying on this.

| | This server | JetBrains MCP (2026.1+) | Daghis 2.12.12 | itcaat 1.0.8 | kate-horshchar 1.4.0 |
|---|---|---|---|---|---|
| Writes | none, by construction | personal builds in the default safe mode; more with brave mode | trigger and cancel by default; a full mode the agent can switch on | trigger, cancel, pin, tag; no off switch | none, GET only |
| Runs where | your machine | the TeamCity server (`/app/mcp`) | your machine | your machine | your machine |
| Find a config from a vague name | fuzzy index over names and project paths | not documented | locator only | locator partial match | no |
| Paste a TeamCity URL | modern, short and legacy URLs | not documented | no | no | no |

Sources: [JetBrains AI agent integration](https://www.jetbrains.com/help/teamcity/ai-agent-integration.html),
[JetBrains/teamcity-mcp](https://github.com/JetBrains/teamcity-mcp),
[Daghis/teamcity-mcp](https://github.com/Daghis/teamcity-mcp),
[itcaat/teamcity-mcp](https://github.com/itcaat/teamcity-mcp),
[kate-horshchar/teamcity-qa-mcp](https://github.com/kate-horshchar/teamcity-qa-mcp).
The JetBrains plugin README and its help page disagree on whether brave mode is
on by default; check your server's setting.

Use the built-in server if you want an agent to act on TeamCity. Use this one
when the agent should only look.

## Example questions

- "Find the deploy pipeline for the auth service."
- "Show me the last 10 builds for `Proj_Build` and which failed."
- "Why did build 12345 fail?" (one `diagnose_build` call)
- "What tests failed in that build, and what was the error?"
- "Search the build log for `OutOfMemoryError`."
- "Which agents are offline right now?"
- "What's in the build queue and why is it waiting?"
- "Who is investigating the failures in the Payments project?"
- "What commits went into this build?"
- "Resolve `https://teamcity.example.com/buildConfiguration/Proj_Build/12345`."

## Development

```bash
git clone https://github.com/desty2k/readonly-mcp-teamcity
cd readonly-mcp-teamcity
uv sync --all-extras
uv run pytest --cov
uv run ruff check .
uv run ruff format --check .
```

A live smoke test against a real server (reads credentials from `.env`):

```bash
uv run python tests/smoke_test.py
```

## License

MIT — see [LICENSE](LICENSE).
