"""Shared constants for the board agent.

Single source of truth for default argument values used by both
the Pydantic models (``ops.py``) and the client methods (``client.py``).
"""

from enum import Enum

DEFAULT_TICKET_SOURCE = "agent"
DEFAULT_TICKET_KIND = "task"
DEFAULT_COMMENT_AUTHOR = "board-agent"
DEFAULT_NOTE = ""


class BoardErrorCode(Enum):
    """Error codes used in agent-comm ``Error`` responses."""

    BAD_REQUEST = "BAD_REQUEST"
    UNKNOWN_OP = "UNKNOWN_OP"
    WRITE_OPS_DISABLED = "WRITE_OPS_DISABLED"
    BOARD_API_ERROR = "BOARD_API_ERROR"
