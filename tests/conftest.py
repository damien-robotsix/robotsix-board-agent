# mypy: ignore-errors

"""Shared test fixtures — network-free, agent-comm stubs injected.

Because the sandbox may lack ``robotsix-agent-comm``, we inject minimal
stubs into ``sys.modules`` before any test imports so that the agent
module can import them without error.
"""

from __future__ import annotations

import sys
import types
from dataclasses import dataclass
from typing import Any

import httpx
import pytest

# ---------------------------------------------------------------------------
# Agent-comm stubs
# ---------------------------------------------------------------------------

# Union type alias used in brokered.py / board_manager.py return types.
Message = Any


@dataclass
class Request:
    """Minimal agent-comm Request stub."""

    body: Any = None
    sender: str = ""
    request_id: str = "req-0"


@dataclass
class Response:
    """Minimal agent-comm Response stub with ``Response.to()`` classmethod."""

    result: Any = None
    error: Any = None
    request_id: str = ""
    body: Any = None

    @classmethod
    def to(cls, request: Request, *, body: Any = None) -> Response:
        return Response(result=body, body=body)


@dataclass
class Error:
    """Minimal agent-comm Error stub with ``Error.to()`` classmethod."""

    code: str = ""
    message: str = ""
    body: Any = None

    def __post_init__(self) -> None:
        if self.body is None:
            self.body = {"code": self.code, "message": self.message}

    @classmethod
    def to(cls, request: Request, *, code: str = "", message: str = "") -> Response:
        return Response(error={"code": code, "message": message})


class _OnRequest:
    """Callable attribute that stores a handler.

    Supports three usage patterns:
    - Constructor: ``Agent(on_request=fn)`` — sets the handler directly.
    - Call-setter: ``agent.on_request(fn)`` — calls to store *fn*.
    - Attribute read: ``agent.on_request`` — returns this wrapper, which
      is callable and delegates to the stored handler.
    """

    __slots__ = ("_handler",)

    def __init__(self, handler: Any = None) -> None:
        self._handler = handler

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        # If no handler is stored yet, the first call with a callable
        # sets it (brokered.py pattern: agent.on_request(fn)).
        if self._handler is None and len(args) == 1 and callable(args[0]):
            self._handler = args[0]
            return None
        # Otherwise, delegate to the stored handler.
        if self._handler is None:
            raise TypeError("No handler registered")
        return self._handler(*args, **kwargs)

    def __repr__(self) -> str:
        return repr(self._handler)


class Agent:
    """Minimal agent-comm Agent stub.

    ``on_request`` is a :class:`_OnRequest` descriptor — it can be set
    via constructor keyword, called as ``agent.on_request(fn)``, or read
    as ``agent.on_request`` (returning the registered handler).

    start()/stop() are synchronous, matching the real
    ``robotsix_agent_comm.sdk.agent.Agent``.
    """

    def __init__(
        self,
        agent_id: str = "",
        registry: Any = None,
        on_request: Any = None,
        transport: Any = None,
        pull: bool = False,
        timeout: float = 30.0,
        broker_host: str = "",
        broker_port: int = 443,
        broker_scheme: str = "https",
        broker_token: str = "",
    ) -> None:
        self.agent_id = agent_id
        self.registry = registry
        self.transport = transport
        self.pull = pull
        self.timeout = timeout
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.broker_scheme = broker_scheme
        self.broker_token = broker_token
        self._started = False
        # Wrap so both ``agent.on_request = x`` (via BoardAgent constructor)
        # and ``agent.on_request(x)`` (brokered call-setter) work.
        self.on_request: _OnRequest = (
            on_request if isinstance(on_request, _OnRequest) else _OnRequest(on_request)
        )

    def start(self) -> None:
        self._started = True
        if self.registry is not None:
            self.registry.register(self)

    def stop(self) -> None:
        self._started = False
        if self.registry is not None:
            self.registry.agents.pop(self.agent_id, None)

    def send_request(self, target: str, body: Any, timeout: float = 30.0) -> Any:
        """Send a request to *target* and return the reply."""
        agent = self.registry.agents.get(target) if self.registry else None
        if agent is None or agent.on_request._handler is None:
            return Error.to(
                Request(),
                code="NOT_FOUND",
                message=f"agent {target} not found",
            )
        request = Request(body=body, sender=self.agent_id)
        return agent.on_request._handler(request)

    def __enter__(self) -> Agent:
        # start() is async; call it but discard the coroutine — the
        # registry is populated by tests directly, so the agent does
        # not need to register itself to send requests.
        self.start()
        return self

    def __exit__(self, *args: Any) -> None:
        self.stop()


class Registry:
    """Minimal agent-comm Registry stub."""

    def __init__(self) -> None:
        self.agents: dict[str, Agent] = {}

    def register(self, agent: Agent) -> None:
        self.agents[agent.agent_id] = agent


def create_transport_pair(
    kind: str = "",
    broker_host: str = "",
    broker_port: int = 443,
    broker_scheme: str = "https",
    broker_token: str = "",
) -> tuple[Registry, Any]:
    """Return (registry, transport) for a brokered connection."""
    return Registry(), None


class BrokeredAgent:
    """Minimal ``robotsix_agent_comm.sdk.BrokeredAgent`` stub.

    Mirrors the real one: wraps :class:`Agent` over a registry/transport from
    :func:`create_transport_pair`, wires handlers, and delegates send/lifecycle.
    """

    def __init__(
        self,
        agent_id: str,
        *,
        broker_host: str = "",
        broker_token: str | None = "",
        broker_port: int = 443,
        broker_scheme: str = "https",
        timeout: float = 30.0,
        on_request: Any = None,
    ) -> None:
        registry, transport = create_transport_pair(
            "brokered",
            broker_host=broker_host,
            broker_port=broker_port,
            broker_scheme=broker_scheme,
            broker_token=broker_token or "",
        )
        self.agent_id = agent_id
        self._agent = Agent(
            agent_id,
            registry,
            transport=transport,
            pull=True,
            timeout=timeout,
            broker_host=broker_host,
            broker_port=broker_port,
            broker_scheme=broker_scheme,
            broker_token=broker_token or "",
        )
        if on_request is not None:
            self._agent.on_request(on_request)

    def on_request(self, handler: Any) -> Any:
        self._agent.on_request(handler)
        return handler

    def send_request(
        self, recipient: str, body: Any = None, *, timeout: float | None = None, **_: Any
    ) -> Any:
        return self._agent.send_request(
            recipient, body, timeout=timeout if timeout is not None else 30.0
        )

    def start(self) -> None:
        self._agent.start()

    def stop(self) -> None:
        self._agent.stop()

    def __enter__(self) -> BrokeredAgent:
        self.start()
        return self

    def __exit__(self, *args: Any) -> None:
        self.stop()


# ---------------------------------------------------------------------------
# Inject stubs into sys.modules (top-level + sub-packages).
# ---------------------------------------------------------------------------

_AGENT_COMM_MODULE = "robotsix_agent_comm"
if _AGENT_COMM_MODULE not in sys.modules:
    _mod = types.ModuleType(_AGENT_COMM_MODULE)
    _mod.Agent = Agent
    _mod.Registry = Registry
    _mod.Request = Request
    _mod.Response = Response
    _mod.Error = Error
    sys.modules[_AGENT_COMM_MODULE] = _mod

# Make the top-level module a package (add __path__) so sub-package
# imports like ``from robotsix_agent_comm.sdk.agent import Agent`` work.
_mod.__path__ = []  # type: ignore[attr-defined]

# Intermediate namespace packages.
for _pkg_name in (
    "robotsix_agent_comm.sdk",
    "robotsix_agent_comm.transport",
):
    if _pkg_name not in sys.modules:
        _pkg = types.ModuleType(_pkg_name)
        _pkg.__path__ = []  # type: ignore[attr-defined]
        sys.modules[_pkg_name] = _pkg

# Sub-package: robotsix_agent_comm.protocol
_PROTOCOL_MODULE = "robotsix_agent_comm.protocol"
if _PROTOCOL_MODULE not in sys.modules:
    _pmod = types.ModuleType(_PROTOCOL_MODULE)
    _pmod.Message = Message
    _pmod.Request = Request
    _pmod.Response = Response
    _pmod.Error = Error
    sys.modules[_PROTOCOL_MODULE] = _pmod

# Sub-package: robotsix_agent_comm.sdk.agent
_SDK_AGENT_MODULE = "robotsix_agent_comm.sdk.agent"
if _SDK_AGENT_MODULE not in sys.modules:
    _smod = types.ModuleType(_SDK_AGENT_MODULE)
    _smod.Agent = Agent
    sys.modules[_SDK_AGENT_MODULE] = _smod

# The sdk package exposes Agent + BrokeredAgent (consumers do
# ``from robotsix_agent_comm.sdk import BrokeredAgent``).
sys.modules["robotsix_agent_comm.sdk"].Agent = Agent  # type: ignore[attr-defined]
sys.modules["robotsix_agent_comm.sdk"].BrokeredAgent = BrokeredAgent  # type: ignore[attr-defined]

# Sub-package: robotsix_agent_comm.transport.brokered
_BROKERED_MODULE = "robotsix_agent_comm.transport.brokered"
if _BROKERED_MODULE not in sys.modules:
    _bmod = types.ModuleType(_BROKERED_MODULE)
    _bmod.create_transport_pair = create_transport_pair
    sys.modules[_BROKERED_MODULE] = _bmod


# ---------------------------------------------------------------------------
# Shared pytest fixtures
# ---------------------------------------------------------------------------

from robotsix_board_agent.config import BoardAgentSettings  # noqa: E402


@pytest.fixture
def settings() -> BoardAgentSettings:
    """Return a default settings instance pointing at a fake board."""
    return BoardAgentSettings(
        board_api_url="http://mock-board.test",
        board_api_token="test-token",
        board_repo_id="test-repo",
        enable_write_ops=True,
    )


@pytest.fixture
def registry() -> Registry:
    """Return a fresh agent-comm Registry stub."""
    return Registry()


@pytest.fixture
def mock_transport() -> httpx.MockTransport:
    """Return an httpx MockTransport that can be customised per-test.

    Tests should reassign ``transport.handler`` to control responses.
    """
    return httpx.MockTransport(lambda _: httpx.Response(200, json={}))


@pytest.fixture
async def client(settings: BoardAgentSettings, mock_transport: httpx.MockTransport) -> Any:
    """Return a BoardClient wired to the mock transport."""
    from robotsix_board_agent.client import BoardClient

    c = BoardClient(settings, transport=mock_transport)
    yield c
    await c.close()
