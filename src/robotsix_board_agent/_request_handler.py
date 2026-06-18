"""Shared request-handling helper for structured board-op requests.

Used by :class:`~.agent.BoardAgent` and
:class:`~.brokered.BrokeredBoardResponder`.
"""

from __future__ import annotations

import json
from typing import Any

from robotsix_agent_comm.protocol import Error, Request

from .config import BoardAgentSettings
from .constants import BoardErrorCode
from .ops import OP_TABLE, WRITE_OPS, BoardOp


def _parse_and_validate(
    request: Request,
    settings: BoardAgentSettings,
) -> tuple[BoardOp | None, Any | None]:
    """Parse a request body into a validated :class:`BoardOp`.

    Returns ``(op, None)`` when parsing and validation succeed, or
    ``(None, error_response)`` when the request is malformed, the op
    is unknown, or the write gate blocks the operation.
    """
    # -- parse body --------------------------------------------------------
    body: dict[str, Any]
    if isinstance(request.body, dict):
        body = request.body
    elif isinstance(request.body, str):
        try:
            body = json.loads(request.body)
        except json.JSONDecodeError:
            return None, Error.to(
                request,
                code=BoardErrorCode.BAD_REQUEST.value,
                message="Request body must be valid JSON",
            )
    else:
        return None, Error.to(
            request,
            code=BoardErrorCode.BAD_REQUEST.value,
            message="Request body must be a JSON object",
        )

    # -- validate BoardOp --------------------------------------------------
    try:
        op = BoardOp.model_validate(body)
    except Exception as exc:
        return None, Error.to(
            request,
            code=BoardErrorCode.BAD_REQUEST.value,
            message=f"Invalid operation: {exc}",
        )

    # -- unknown op --------------------------------------------------------
    if op.op not in OP_TABLE:
        return None, Error.to(
            request,
            code=BoardErrorCode.UNKNOWN_OP.value,
            message=f"Unknown op: {op.op}",
        )

    # -- write gate --------------------------------------------------------
    if op.op in WRITE_OPS and not settings.enable_write_ops:
        return None, Error.to(
            request,
            code=BoardErrorCode.WRITE_OPS_DISABLED.value,
            message=(f"Write operation '{op.op}' rejected: enable_write_ops is False"),
        )

    return op, None
