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
import json
import logging
import threading
from typing import Any

from robotsix_agent_comm.protocol import Error, Message, Request, Response
from robotsix_agent_comm.sdk.agent import Agent
from robotsix_agent_comm.transport.brokered import create_transport_pair

from .client import BoardAPIError, BoardClient
from .config import BoardAgentSettings
from .constants import BoardErrorCode
from .ops import OP_TABLE, WRITE_OPS, BoardOp, dispatch

logger = logging.getLogger(__name__)


class BrokeredBoardResponder:
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
        self.settings = settings
        self.client = BoardClient(settings)
        self.agent_id = agent_id or f"board-{settings.board_repo_id}"
        registry, transport = create_transport_pair(
            "brokered",
            broker_host=broker_host,
            broker_port=broker_port,
            broker_scheme=broker_scheme,
            broker_token=broker_token,
        )
        self._agent = Agent(
            self.agent_id,
            registry,
            transport=transport,
            pull=True,
            timeout=timeout,
        )
        self._agent.on_request(self._handle_request)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread: threading.Thread | None = None

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        """Start the async runtime, then register + listen on the broker."""
        if self._loop is not None:
            return
        loop = asyncio.new_event_loop()
        thread = threading.Thread(
            target=loop.run_forever, name=f"{self.agent_id}-loop", daemon=True
        )
        thread.start()
        self._loop = loop
        self._loop_thread = thread
        self._agent.start()
        logger.info("BrokeredBoardResponder %r listening via broker", self.agent_id)

    def stop(self) -> None:
        """Stop listening, close the board client, and stop the runtime."""
        self._agent.stop()
        loop = self._loop
        thread = self._loop_thread
        self._loop = None
        self._loop_thread = None
        if loop is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(self.client.close(), loop).result(timeout=5.0)
        except Exception:
            logger.warning("board client close failed during stop", exc_info=True)
        loop.call_soon_threadsafe(loop.stop)
        if thread is not None:
            thread.join(timeout=2.0)
        loop.close()

    # -- request handling --------------------------------------------------

    def _run(self, coro: Any) -> Any:
        """Run *coro* to completion on the responder's event loop."""
        assert self._loop is not None  # noqa: S101 — set in start() before use
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result()

    def _handle_request(self, request: Request) -> Message:
        """Validate the structured op, enforce the write gate, and dispatch."""
        body: dict[str, Any]
        if isinstance(request.body, dict):
            body = request.body
        elif isinstance(request.body, str):
            try:
                body = json.loads(request.body)
            except json.JSONDecodeError:
                return Error.to(
                    request,
                    code=BoardErrorCode.BAD_REQUEST.value,
                    message="Request body must be valid JSON",
                )
        else:
            return Error.to(
                request,
                code=BoardErrorCode.BAD_REQUEST.value,
                message="Request body must be a JSON object",
            )

        try:
            op = BoardOp.model_validate(body)
        except Exception as exc:
            return Error.to(
                request,
                code=BoardErrorCode.BAD_REQUEST.value,
                message=f"Invalid operation: {exc}",
            )

        if op.op not in OP_TABLE:
            return Error.to(
                request,
                code=BoardErrorCode.UNKNOWN_OP.value,
                message=f"Unknown op: {op.op}",
            )

        if op.op in WRITE_OPS and not self.settings.enable_write_ops:
            return Error.to(
                request,
                code=BoardErrorCode.WRITE_OPS_DISABLED.value,
                message=(f"Write operation '{op.op}' rejected: enable_write_ops is False"),
            )

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
