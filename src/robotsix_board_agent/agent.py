"""BoardAgent — an agent-comm ``Agent`` that exposes board operations.

Wraps the board REST client behind agent-comm message handling so
other agents can drive a board programmatically.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

from .client import BoardAPIError, BoardClient
from .config import BoardAgentSettings
from .ops import OP_TABLE, WRITE_OPS, BoardOp, UnknownOpError, dispatch

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Import robotsix-agent-comm, with a fallback for sandbox environments where
# pip cannot resolve the uv-specific git source.
# ---------------------------------------------------------------------------
_agent_comm_available = True
try:
    from robotsix_agent_comm import Agent, Error, Registry, Request, Response
except ImportError:
    _agent_comm_available = False
    # Try the bundled checkout fallback.
    from pathlib import Path as _Path

    _REF = _Path(__file__).resolve().parent.parent.parent / "_agent_comm_ref" / "src"
    if _REF.is_dir() and str(_REF) not in sys.path:
        sys.path.insert(0, str(_REF))
    try:
        from robotsix_agent_comm import Agent, Error, Registry, Request, Response
    except ImportError:
        Agent = None
        Error = None
        Registry = None
        Request = None
        Response = None

# ---------------------------------------------------------------------------
# Setup structured logging via robotsix-llmio's shared helper (idempotent).
# ---------------------------------------------------------------------------
try:
    from robotsix_llmio.logging import setup_logging as _llmio_setup_logging

    _llmio_setup_logging(loggers=["robotsix_board_agent"])
except ImportError:
    pass


class BoardAgent:
    """An agent-comm Agent that wraps the board REST API.

    Usage::

        from robotsix_board_agent import BoardAgent, BoardAgentSettings
        from robotsix_agent_comm import Registry

        settings = BoardAgentSettings(
            board_api_url="http://localhost:8000",
            board_api_token="sk-...",
            board_repo_id="my-repo",
        )
        registry = Registry()
        agent = BoardAgent(settings, registry)
        await agent.start()
    """

    def __init__(
        self,
        settings: BoardAgentSettings,
        registry: Registry,
        agent_id: str | None = None,
    ) -> None:
        self.settings: BoardAgentSettings = settings
        self.client: BoardClient = BoardClient(settings)
        self.agent_id: str = agent_id or f"board-{settings.board_repo_id}"

        self._agent: Any = None
        if _agent_comm_available:
            self._agent = Agent(
                agent_id=self.agent_id,
                registry=registry,
                on_request=self._handle_request,
            )

    # -- request handler ---------------------------------------------------

    async def _handle_request(self, request: Request) -> Response:
        """Handle an incoming agent-comm request.

        Parses ``{"op": "...", "args": {...}}`` from the request body,
        validates the operation, and dispatches to the board client.
        """
        # Parse the structured operation from the request body.
        body: dict[str, Any]
        if isinstance(request.body, dict):
            body = request.body
        elif isinstance(request.body, str):
            try:
                body = json.loads(request.body)
            except json.JSONDecodeError:
                return Error.to(
                    request,
                    code="BAD_REQUEST",
                    message="Request body must be valid JSON",
                )
        else:
            return Error.to(
                request,
                code="BAD_REQUEST",
                message="Request body must be a JSON object",
            )

        try:
            op = BoardOp.model_validate(body)
        except Exception as exc:
            logger.warning("Bad request: %s", exc)
            return Error.to(
                request,
                code="BAD_REQUEST",
                message=f"Invalid operation: {exc}",
            )

        logger.info("Request received: op=%s", op.op)

        # Unknown op check.
        if op.op not in OP_TABLE:
            logger.warning("Unknown op requested: %s", op.op)
            return Error.to(
                request,
                code="UNKNOWN_OP",
                message=f"Unknown op: {op.op}",
            )

        # Write gate.
        if op.op in WRITE_OPS and not self.settings.enable_write_ops:
            logger.warning("Write op rejected (disabled): op=%s", op.op)
            return Error.to(
                request,
                code="WRITE_OPS_DISABLED",
                message=f"Write operation '{op.op}' rejected: enable_write_ops is False",
            )

        # Dispatch.
        try:
            result = await dispatch(self.client, op)
        except BoardAPIError as exc:
            logger.error(
                "Board API error: op=%s status=%d detail=%s",
                op.op,
                exc.status_code,
                exc.detail,
            )
            return Error.to(
                request,
                code="BOARD_API_ERROR",
                message=f"Board API error {exc.status_code}: {exc.detail}",
            )
        except UnknownOpError as exc:
            logger.error("Dispatch failed: unknown op=%s", op.op)
            return Error.to(
                request,
                code="UNKNOWN_OP",
                message=str(exc),
            )

        logger.info("Response sent: op=%s", op.op)
        return Response(result=result)

    # -- lifecycle ---------------------------------------------------------

    async def start(self) -> None:
        """Register the agent and start listening."""
        if self._agent is not None:
            await self._agent.start()

    async def stop(self) -> None:
        """Deregister the agent and stop listening."""
        if self._agent is not None:
            await self._agent.stop()
        await self.client.close()
