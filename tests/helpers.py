"""Shared test helpers."""

from __future__ import annotations

from typing import Any


class FakeMCP:
    """Minimal FastMCP stand-in that captures registered tool functions.

    ``register(fake)`` runs the module's nested ``@mcp.tool()`` definitions; each
    decorated function is stored by name. Tests then call it directly, passing a
    mock Context as the first positional argument.
    """

    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self, *args: Any, **kwargs: Any):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator


def extract_tools(module) -> dict[str, Any]:
    """Register a tool module on a FakeMCP and return a name -> function mapping."""
    fake = FakeMCP()
    module.register(fake)
    return fake.tools
