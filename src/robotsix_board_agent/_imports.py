"""Import fallback for robotsix_agent_comm.

Provides a testable, side-effect-isolated function that resolves
the agent-comm imports, with a fallback for sandbox environments
where pip cannot resolve the uv-specific git source.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


def _resolve_agent_comm() -> tuple[bool, Any, Any, Any, Any, Any]:
    """Resolve robotsix_agent_comm imports with a two-level fallback.

    Returns a tuple of ``(available, Agent, Error, Registry,
    Request, Response)``.  *available* is ``True`` only when the
    primary (non-fallback) import succeeded; individual names are
    ``None`` when neither import path worked.
    """
    try:
        from robotsix_agent_comm import Agent, Error, Registry, Request, Response
    except ImportError:
        pass  # primary import unavailable; will try fallback
    else:
        return True, Agent, Error, Registry, Request, Response

    # Try the bundled checkout fallback.
    _ref_dir = Path(__file__).resolve().parent.parent.parent / "_agent_comm_ref" / "src"
    if _ref_dir.is_dir() and str(_ref_dir) not in sys.path:
        sys.path.insert(0, str(_ref_dir))
    try:
        from robotsix_agent_comm import Agent, Error, Registry, Request, Response
    except ImportError:
        return False, None, None, None, None, None
    else:
        return False, Agent, Error, Registry, Request, Response


def _setup_langfuse_tracing() -> None:
    """Setup Langfuse tracing (idempotent; reads LANGFUSE_* env vars)."""
    try:
        from robotsix_llmio.core import setup_langfuse_tracing as _llmio_setup_langfuse_tracing

        _llmio_setup_langfuse_tracing()
    except ImportError:
        pass  # robotsix_llmio is optional; langfuse tracing unavailable
