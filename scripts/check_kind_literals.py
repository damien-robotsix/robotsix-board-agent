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
from pathlib import Path

# ---------------------------------------------------------------------------
# Locate the repo root and parse DEFAULT_TICKET_KIND from constants.py.
# We use AST parsing to avoid importing the package, because the CI
# reusable workflow runs this script with bare ``python`` (not
# ``uv run python``), so the package and its dependencies may not be
# importable.
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent
_CONSTANTS_PATH = _REPO_ROOT / "src" / "robotsix_board_agent" / "constants.py"


def _read_default_ticket_kind(path: Path) -> str:
    """Parse *path* and return the value of ``DEFAULT_TICKET_KIND``."""
    try:
        source = path.read_text()
    except OSError:
        sys.exit(f"ERROR: cannot read {path}")

    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if (
                isinstance(target, ast.Name)
                and target.id == "DEFAULT_TICKET_KIND"
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            ):
                return node.value.value
    sys.exit(f"ERROR: DEFAULT_TICKET_KIND not found in {path}")


_DEFAULT_KIND = _read_default_ticket_kind(_CONSTANTS_PATH)

# ---------------------------------------------------------------------------
# Valid kinds — add new recognised kinds here as the board API evolves
# ---------------------------------------------------------------------------
_VALID_KINDS: frozenset[str] = frozenset({_DEFAULT_KIND})

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
    src_dir = _REPO_ROOT / "src"
    errors: list[str] = []

    for py_file in sorted(src_dir.rglob("*.py")):
        literals = _find_kind_literals(py_file)
        for lineno, literal in literals:
            if literal not in _VALID_KINDS:
                errors.append(
                    f"{py_file.relative_to(_REPO_ROOT)}:{lineno}: "
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
