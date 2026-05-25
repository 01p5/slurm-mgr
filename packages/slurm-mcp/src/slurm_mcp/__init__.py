"""slurm-mcp — MCP server exposing Slurm s* commands as tools."""
from .tools import TOOLS, dispatch_tool

__all__ = ["TOOLS", "dispatch_tool"]
