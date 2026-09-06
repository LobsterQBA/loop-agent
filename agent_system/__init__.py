"""Loop Agent: a readable loop, local tools, memory, and trace."""

from importlib.metadata import PackageNotFoundError, version

from agent_system.agent import AgentSystem, AgentTurn
from agent_system.memory import MemoryStore
from agent_system.models import DemoModel, LiveModel
from agent_system.tools import ToolRegistry, build_tools

try:
    __version__ = version("loop-agent")
except PackageNotFoundError:
    __version__ = "0+unknown"

__all__ = [
    "AgentSystem",
    "AgentTurn",
    "DemoModel",
    "LiveModel",
    "MemoryStore",
    "ToolRegistry",
    "__version__",
    "build_tools",
]
