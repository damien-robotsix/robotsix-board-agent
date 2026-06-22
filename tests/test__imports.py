"""Tests for :mod:`robotsix_board_agent._imports` — import resolution with fallback."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

from robotsix_board_agent._imports import _resolve_agent_comm

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pop_agent_comm_modules() -> dict[str, object]:
    """Remove all robotsix_agent_comm entries from sys.modules and return them."""
    popped: dict[str, object] = {}
    for key in list(sys.modules):
        if key == "robotsix_agent_comm" or key.startswith("robotsix_agent_comm."):
            popped[key] = sys.modules.pop(key)
    return popped


def _restore_agent_comm_modules(modules: dict[str, object]) -> None:
    """Restore previously-popped agent-comm modules into sys.modules."""
    for key, mod in modules.items():
        sys.modules[key] = mod


# ---------------------------------------------------------------------------
# _resolve_agent_comm
# ---------------------------------------------------------------------------


class TestResolveAgentCommSuccess:
    """Primary import succeeds (conftest stubs are in sys.modules)."""

    def test_available_true_and_all_symbols_returned(self) -> None:
        """When primary import works, available=True and all 5 symbols are set."""
        available, agent, error, registry, request, response = _resolve_agent_comm()

        assert available is True
        assert agent is not None
        assert error is not None
        assert registry is not None
        assert request is not None
        assert response is not None


class TestResolveAgentCommFallback:
    """Primary import fails; bundled checkout exists and succeeds."""

    def test_fallback_returns_available_false_with_symbols(self) -> None:
        """After removing stubs from sys.modules and mocking the checkout
        directory, the fallback import succeeds and returns available=False
        with all symbols set."""
        saved = _pop_agent_comm_modules()
        try:
            with patch.object(Path, "is_dir", return_value=True) as mock_is_dir:
                # Re-insert the top-level stub when is_dir is called so the
                # second import inside _resolve_agent_comm finds it.  We
                # overwrite unconditionally because the first failed import
                # may have loaded a system-installed module that lacks our
                # stub symbols.
                def _on_is_dir() -> bool:
                    if "robotsix_agent_comm" in saved:
                        sys.modules["robotsix_agent_comm"] = saved["robotsix_agent_comm"]
                    return True

                mock_is_dir.side_effect = _on_is_dir

                available, agent, error, registry, request, response = _resolve_agent_comm()

                assert available is False
                assert agent is not None
                assert error is not None
                assert registry is not None
                assert request is not None
                assert response is not None
        finally:
            _restore_agent_comm_modules(saved)

    def test_fallback_inserts_bundled_path_into_sys_path(self) -> None:
        """When the bundled checkout directory exists and the path is not
        already in sys.path, the function inserts it."""
        saved = _pop_agent_comm_modules()
        try:
            # Ensure the constructed path is not already in sys.path.
            # We compute the same path _resolve_agent_comm would compute.
            import robotsix_board_agent._imports as _mod

            _ref_path = str(
                Path(_mod.__file__).resolve().parent.parent.parent / "_agent_comm_ref" / "src"
            )

            # Remove it if it happens to be present.
            sys_path_before = [p for p in sys.path if p != _ref_path]
            with patch.object(sys, "path", sys_path_before):
                with patch.object(Path, "is_dir", return_value=True) as mock_is_dir:

                    def _on_is_dir() -> bool:
                        if "robotsix_agent_comm" in saved:
                            sys.modules["robotsix_agent_comm"] = saved["robotsix_agent_comm"]
                        return True

                    mock_is_dir.side_effect = _on_is_dir

                    _resolve_agent_comm()

                # After the call, sys.path should have the bundled path inserted.
                assert _ref_path in sys.path
        finally:
            _restore_agent_comm_modules(saved)


class TestResolveAgentCommFullFailure:
    """Both import paths fail — no stubs, no bundled checkout."""

    def test_both_imports_fail_returns_available_false_all_none(self) -> None:
        """When neither the primary import nor the fallback succeeds, the
        function returns available=False and None for every symbol."""
        saved = _pop_agent_comm_modules()
        try:
            available, agent, error, registry, request, response = _resolve_agent_comm()

            assert available is False
            assert agent is None
            assert error is None
            assert registry is None
            assert request is None
            assert response is None
        finally:
            _restore_agent_comm_modules(saved)
