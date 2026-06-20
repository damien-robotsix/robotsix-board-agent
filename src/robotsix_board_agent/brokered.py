"""Brokered board responder built on the *shipping* agent-comm SDK.

:class:`~robotsix_board_agent.agent.BoardAgent` targets a future async
agent-comm API that currently exists only as test stubs and cannot run against
the real broker. This module provides a responder that integrates with the
agent-comm that actually ships: the synchronous
:class:`~robotsix_agent_comm.sdk.agent.Agent` in **pull/mailbox** mode, talking
to a central broker over outbound HTTP only (NAT-safe — the broker never dials
back in, so the board API can stay on a private host).

It reuses the real :class:`~robotsix_board_agent.client.BoardClient` and
:func:`~robotsix_board_agent.ops.dispatch`; their async calls run on a
dedicated event loop the responder owns, so the client's persistent
``httpx.AsyncClient`` has one stable loop for its whole lifetime.
"""

from __future__ import annotations

import asyncio
import logging
import threading

from robotsix_agent_comm.protocol import Error, Message, Request, Response

from ._lifecycle import _build_brokered_agent, _ThreadedLoopMixin
from ._request_handler import _parse_and_validate
from .client import BoardAPIError, BoardClient
from .config import BoardAgentSettings
from .constants import BoardErrorCode
from .ops import dispatch

logger = logging.getLogger(__name__)


class BrokeredBoardResponder(_ThreadedLoopMixin):
    """Serve board operations over an agent-comm broker in pull (mailbox) mode.

    Construct with the board settings and the broker coordinates, then
    :meth:`start` to register + listen and :meth:`stop` to tear down. The
    responder is synchronous on the outside (matching the shipping ``Agent``);
    the board client's async calls are driven on an internal event loop.
    """

    def __init__(
        self,
        settings: BoardAgentSettings,
        *,
        broker_host: str,
        broker_token: str,
        broker_port: int = 443,
        broker_scheme: str = "https",
        agent_id: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        """Initialise the brokered board responder.

        *settings* — the board configuration (repo id, board URL, auth token).
        *broker_host*/*broker_port*/*broker_scheme*/*broker_token* — broker
        connection details for the agent-comm layer.  *agent_id* — custom broker
        agent id (defaults to ``board-{repo_id}``).  *timeout* — broker operation
        timeout in seconds.
        """
        self.settings = settings
        self.client = BoardClient(settings)
        self.agent_id = agent_id or f"board-{settings.board_repo_id}"
        self._agent = _build_brokered_agent(
            self.agent_id,
            broker_host=broker_host,
            broker_port=broker_port,
            broker_scheme=broker_scheme,
            broker_token=broker_token,
            timeout=timeout,
            on_request=self._handle_request,
        )
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread: threading.Thread | None = None

    # -- request handling --------------------------------------------------

    def _handle_request(self, request: Request) -> Message:
        """Validate the structured op, enforce the write gate, and dispatch."""
        op, error = _parse_and_validate(request, self.settings)
        if error is not None:
            return error
        assert op is not None  # noqa: S101 — _parse_and_validate invariant
        try:
            result = self._run(dispatch(self.client, op))
        except BoardAPIError as exc:
            return Error.to(
                request,
                code=BoardErrorCode.BOARD_API_ERROR.value,
                message=f"Board API error {exc.status_code}: {exc.detail}",
            )
        logger.info("board op served: op=%s", op.op)
        return Response.to(request, body=result)
