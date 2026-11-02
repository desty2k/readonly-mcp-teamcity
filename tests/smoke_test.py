"""Manual smoke test against a live TeamCity server.

Run with:  uv run python tests/smoke_test.py

Loads credentials from the environment (or a local .env), exercises a handful of
read-only endpoints, and prints PASS/FAIL per check. This is NOT a pytest test —
it has no ``test_*`` functions and only runs under ``__main__``.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from mcp_teamcity.client import TeamCityClient
from mcp_teamcity.settings import TeamCitySettings

GREEN = "\033[92m"
RED = "\033[91m"
RESET = "\033[0m"


def _load_env() -> None:
    """Minimal .env loader so the script has no extra dependency."""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


async def _run() -> int:
    _load_env()
    try:
        settings = TeamCitySettings()  # type: ignore[call-arg]
    except Exception as exc:
        print(f"{RED}FAIL{RESET} settings: {exc}")
        print("Set TEAMCITY_BASE_URL and TEAMCITY_TOKEN (env or .env).")
        return 1

    client = TeamCityClient(settings)
    failures = 0

    async def check(label: str, coro) -> None:
        nonlocal failures
        try:
            result = await coro
            summary = ""
            if isinstance(result, dict):
                summary = result.get("version") or str(result.get("count", ""))
            print(f"{GREEN}PASS{RESET} {label} {summary}".rstrip())
        except Exception as exc:
            failures += 1
            print(f"{RED}FAIL{RESET} {label}: {exc}")

    try:
        await check("server_info", client.get("/app/rest/server", params={"fields": "version,buildNumber"}))
        await check("projects", client.get("/app/rest/projects", params={"locator": "count:1", "fields": "count"}))
        await check(
            "build_types",
            client.get("/app/rest/buildTypes", params={"locator": "count:1", "fields": "count"}),
        )
        await check("agents", client.get("/app/rest/agents", params={"locator": "count:1", "fields": "count"}))
    finally:
        await client.close()

    print()
    if failures:
        print(f"{RED}{failures} check(s) failed{RESET}")
        return 1
    print(f"{GREEN}All checks passed{RESET}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_run()))
