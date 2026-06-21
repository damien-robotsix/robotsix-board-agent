"""BoardAgent — an agent-comm ``Agent`` that exposes board operations.

Wraps the board REST client behind agent-comm message handling so
other agents can drive a board programmatically.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from robotsix_agent_comm import Registry, Request, Response

from ._imports import _resolve_agent_comm
from ._request_handler import _parse_and_validate
from .client import BoardAPIError, BoardClient
from .config import BoardAgentSettings
from .constants import BoardErrorCode
from .ops import dispatch

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Import robotsix-agent-comm, with a fallback for sandbox environments where
# pip cannot resolve the uv-specific git source.
# ---------------------------------------------------------------------------
_agent_comm_available, _Agent, _Error, _Registry, _Request, _Response = _resolve_agent_comm()

# ---------------------------------------------------------------------------
# Setup structured logging via robotsix-llmio's shared helper (idempotent).
# ---------------------------------------------------------------------------
try:
    from robotsix_llmio.logging import setup_logging as _llmio_setup_logging

    _llmio_setup_logging(loggers=["robotsix_board_agent"])
except ImportError:
    import logging as _logging

    _logging.basicConfig(
        level=_logging.INFO,
        format="%(levelname)s:%(name)s:%(message)s",
    )


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
            self._agent = _Agent(
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
        op, error = _parse_and_validate(request, self.settings)
        if error is not None:
            return error
        assert op is not None  # noqa: S101 — _parse_and_validate invariant
        logger.info("Request received: op=%s", op.op)
        try:
            result = await dispatch(self.client, op)
        except BoardAPIError as exc:
            logger.error(
                "Board API error: op=%s status=%d detail=%s",
                op.op,
                exc.status_code,
                exc.detail,
            )
            return _Error.to(
                request,
                code=BoardErrorCode.BOARD_API_ERROR.value,
                message=f"Board API error {exc.status_code}: {exc.detail}",
            )
        logger.info("Response sent: op=%s", op.op)
        return _Response(result=result)

    # -- lifecycle ---------------------------------------------------------

    async def start(self) -> None:
        """Register the agent and start listening."""
        if self._agent is not None:
            self._agent.start()

    async def stop(self) -> None:
        """Deregister the agent and stop listening."""
        if self._agent is not None:
            self._agent.stop()
        await self.client.close()
