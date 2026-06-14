"""robotsix-board-agent — board lifecycle agent over agent-comm."""

from .agent import BoardAgent
from .client import BoardAPIError, BoardClient
from .config import BoardAgentSettings
from .ops import BoardOp, UnknownOpError, dispatch

__all__ = [
    "BoardAPIError",
    "BoardAgent",
    "BoardAgentSettings",
    "BoardClient",
    "BoardOp",
    "UnknownOpError",
    "dispatch",
]
