"""Shared threaded event-loop lifecycle mixin.

Provides :class:`_ThreadedLoopMixin` — a mixin for classes that own a
dedicated asyncio event loop on a daemon thread, used by
:class:`~.brokered.BrokeredBoardResponder` and
:class:`~.board_manager.BoardManager`.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any

from robotsix_agent_comm.sdk import BrokeredAgent

logger = logging.getLogger(__name__)


class _ThreadedLoopMixin:
    """Mixin providing :meth:`start`, :meth:`stop`, and :meth:`_run`.

    Subclasses must set the following attributes in ``__init__``
    (typically to ``None`` initially)::

        self._loop: asyncio.AbstractEventLoop | None
        self._loop_thread: threading.Thread | None

    And must have:

        self._agent  — an object with ``start()`` and ``stop()`` methods
        self.client  — a :class:`~.client.BoardClient` whose ``close()``
                       is a coroutine
        self.agent_id — a string used for the thread name and log message
    """

    _loop: asyncio.AbstractEventLoop | None
    _loop_thread: threading.Thread | None
    _agent: Any
    client: Any
    agent_id: str

    def start(self) -> None:
        """Register with the broker and begin listening for operations."""
        if self._loop is not None:
            return
        loop = asyncio.new_event_loop()
        thread = threading.Thread(
            target=loop.run_forever,
            name=f"{self.agent_id}-loop",
            daemon=True,
        )
        thread.start()
        self._loop = loop
        self._loop_thread = thread
        self._agent.start()
        logger.info("%s %r listening via broker", type(self).__name__, self.agent_id)

    def stop(self) -> None:
        """Deregister from the broker and tear down the event loop."""
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

    def _run(self, coro: Any) -> Any:
        """Run *coro* to completion on the owned event loop."""
        assert self._loop is not None  # noqa: S101 — set in start()
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result()


def _build_brokered_agent(
    agent_id: str,
    *,
    broker_host: str,
    broker_port: int,
    broker_scheme: str,
    broker_token: str,
    timeout: float,
    on_request: Any,
) -> BrokeredAgent:
    """Construct a :class:`~robotsix_agent_comm.sdk.BrokeredAgent` with the
    supplied broker connection parameters and request handler.

    Centralises the duplicated construction that every
    :class:`_ThreadedLoopMixin` subclass previously performed inline.
    """
    return BrokeredAgent(
        agent_id,
        broker_host=broker_host,
        broker_port=broker_port,
        broker_scheme=broker_scheme,
        broker_token=broker_token,
        timeout=timeout,
        on_request=on_request,
    )
