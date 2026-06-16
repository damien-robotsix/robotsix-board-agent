"""robotsix-board-agent — board lifecycle agent over agent-comm."""

from .agent import BoardAgent
from .client import BoardAPIError, BoardClient
from .config import BoardAgentSettings
from .ops import OP_TABLE, WRITE_OPS, BoardOp, UnknownOpError, dispatch

__all__ = [
    "OP_TABLE",
    "WRITE_OPS",
    "BoardAPIError",
    "BoardAgent",
    "BoardAgentSettings",
    "BoardClient",
    "BoardOp",
    "UnknownOpError",
    "dispatch",
]
