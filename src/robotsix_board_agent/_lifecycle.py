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
        """Start the async runtime, then register and listen."""
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

    def _run(self, coro: Any) -> Any:
        """Run *coro* to completion on the owned event loop."""
        assert self._loop is not None  # noqa: S101 — set in start()
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result()
