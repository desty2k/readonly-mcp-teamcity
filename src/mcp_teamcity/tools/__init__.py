"""Tool modules for the TeamCity MCP server.

Each module exposes a single ``register(mcp: FastMCP) -> None`` that defines its
tools as nested ``@mcp.tool()`` functions. ``server.create_server`` imports and
registers them in order.
"""
