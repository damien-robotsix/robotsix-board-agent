#!/usr/bin/env python3
"""Check that ticket-kind string literals are consistent with constants.

Scans the source tree for string literals that appear to be ticket
"kind" values and verifies they match the canonical constants defined
in ``robotsix_board_agent.constants``.

Usage::

    python scripts/check_kind_literals.py

Exit 0 when all checks pass; exit 1 with specific messages otherwise.
"""

from __future__ import annotations

import ast
import sys
import types
from pathlib import Path

# ---------------------------------------------------------------------------
# Inject stubs for optional dependencies before importing the package.
# robotsix-agent-comm is a 'prod' extra — not installed by the CI reusable
# workflow (which runs ``uv sync --frozen`` without extras).  Without this
# injection, importing *anything* from robotsix_board_agent fails.
# ---------------------------------------------------------------------------


def _inject_agent_comm_stubs() -> None:
    """Inject minimal stdlib stubs for ``robotsix_agent_comm`` modules."""
    # Parent package (must exist before any subpackage import).
    _comm_mod = sys.modules.get("robotsix_agent_comm")
    if _comm_mod is None:
        _comm_mod = types.ModuleType("robotsix_agent_comm")
        _comm_mod.__path__ = []
        sys.modules["robotsix_agent_comm"] = _comm_mod

    # robotsix_agent_comm.sdk — BrokeredAgent.
    _sdk_mod = sys.modules.get("robotsix_agent_comm.sdk")
    if _sdk_mod is None:
        _sdk_mod = types.ModuleType("robotsix_agent_comm.sdk")
        _sdk_mod.__path__ = []
        sys.modules["robotsix_agent_comm.sdk"] = _sdk_mod
    if not hasattr(_sdk_mod, "BrokeredAgent"):

        class _BrokeredAgentStub:
            pass

        _sdk_mod.BrokeredAgent = _BrokeredAgentStub  # type: ignore[attr-defined]

    # robotsix_agent_comm.protocol — Error, Message, Request, Response.
    _proto_mod = sys.modules.get("robotsix_agent_comm.protocol")
    if _proto_mod is None:
        _proto_mod = types.ModuleType("robotsix_agent_comm.protocol")
        sys.modules["robotsix_agent_comm.protocol"] = _proto_mod
    for _proto_name in ("Error", "Message", "Request", "Response"):
        if not hasattr(_proto_mod, _proto_name):
            setattr(_proto_mod, _proto_name, type(_proto_name, (), {}))


_inject_agent_comm_stubs()

# ---------------------------------------------------------------------------
# Ensure the local package is importable even when running with bare
# ``python`` (not ``uv run python``).  The CI reusable workflow calls
# ``python scripts/check_kind_literals.py`` without ``uv run``, so the
# package may not be on sys.path unless we add ``src/`` explicitly.
# This is safe even when the package IS installed — importing it via
# ``src/`` on sys.path takes precedence, which gives us the exact
# version under test.
# ---------------------------------------------------------------------------
_script_dir = Path(__file__).resolve().parent
_src_dir = str(_script_dir.parent / "src")
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

# ---------------------------------------------------------------------------
# Import the constants module (the single source of truth for kind values)
# ---------------------------------------------------------------------------
from robotsix_board_agent.constants import DEFAULT_TICKET_KIND  # noqa: E402

# ---------------------------------------------------------------------------
# Valid kinds — add new recognised kinds here as the board API evolves
# ---------------------------------------------------------------------------
_VALID_KINDS: frozenset[str] = frozenset({DEFAULT_TICKET_KIND})

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _is_kind_context(node: ast.AST) -> bool:
    """Return True if *node* appears in a 'kind' parameter/argument context."""
    parent = getattr(node, "_parent", None)
    if parent is None:
        return False

    # ``kind=<literal>`` keyword argument
    if isinstance(parent, ast.keyword) and parent.arg == "kind":
        return True

    # ``"kind": <literal>`` dict value
    if isinstance(parent, ast.Dict):
        for key, value in zip(parent.keys, parent.values, strict=False):
            if value is node:
                if isinstance(key, ast.Constant) and key.value == "kind":
                    return True
                break

    return False


def _set_parents(tree: ast.AST) -> None:
    """Walk *tree* and attach ``_parent`` references to every node."""
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            child._parent = node  # type: ignore[attr-defined]


def _find_kind_literals(source_path: Path) -> list[tuple[int, str]]:
    """Return (lineno, literal_value) for every string constant found in a
    position that looks like a 'kind' value context within *source_path*."""
    try:
        source = source_path.read_text()
    except OSError:
        return []

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    _set_parents(tree)

    results: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant):
            continue
        if not isinstance(node.value, str):
            continue
        if not _is_kind_context(node):
            continue
        results.append((node.lineno, node.value))

    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    """Run the kind-literals consistency check."""
    repo_root = Path(__file__).resolve().parent.parent
    src_dir = repo_root / "src"
    errors: list[str] = []

    for py_file in sorted(src_dir.rglob("*.py")):
        literals = _find_kind_literals(py_file)
        for lineno, literal in literals:
            if literal not in _VALID_KINDS:
                errors.append(
                    f"{py_file.relative_to(repo_root)}:{lineno}: "
                    f"kind literal {literal!r} is not in the known valid set "
                    f"{sorted(_VALID_KINDS)!r}. If this is a new valid kind, "
                    f"add it to _VALID_KINDS in {Path(__file__).name}."
                )

    if errors:
        for msg in errors:
            print(msg)
        return 1

    print("check_kind_literals ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
