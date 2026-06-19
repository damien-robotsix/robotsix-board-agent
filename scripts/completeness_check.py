#!/usr/bin/env python3
"""Cross-module completeness checks for ``robotsix_board_agent``.

Performs seven deterministic runtime-introspection checks (A-G) that verify
the five tightly-coupled modules — ``ops.py``, ``client.py``, ``agent.py``,
``config.py``, ``__init__.py`` — haven't drifted out of sync.

Usage::

    python scripts/completeness_check.py

Exit 0 when all checks pass; exit 1 (with specific messages) otherwise.
"""

from __future__ import annotations

import ast
import inspect
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Import the package under inspection
# ---------------------------------------------------------------------------
import robotsix_board_agent
import robotsix_board_agent.config as _config_mod
import robotsix_board_agent.ops as _ops_mod
from robotsix_board_agent.client import BoardClient
from robotsix_board_agent.ops import OP_TABLE, WRITE_OPS

# ===========================================================================
# Helper utilities
# ===========================================================================


def _source_text(obj: Any) -> str | None:
    """Return the source text of *obj*, or ``None``."""
    try:
        return inspect.getsource(obj)
    except OSError, TypeError:
        return None


def _parse_source(obj: Any) -> ast.AST | None:
    """Parse the source of *obj* into an AST, or ``None``."""
    src = _source_text(obj)
    if src is None:
        return None
    try:
        return ast.parse(src)
    except SyntaxError:
        return None


def _client_method_calls_in_handler(handler: Callable[..., Any]) -> set[str]:
    """Return names of ``BoardClient`` methods called directly by *handler*.

    Only finds calls of the form ``client.<method>(...)`` where *client* is
    the first parameter of the handler.
    """
    tree = _parse_source(handler)
    if tree is None:
        return set()
    methods: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute):
            continue
        if not isinstance(node.func.value, ast.Name):
            continue
        if node.func.value.id == "client":
            methods.add(node.func.attr)
    return methods


def _http_method_of_client_fn(method: Callable[..., Any]) -> str | None:
    """Return the HTTP method string (e.g. ``"GET"``, ``"POST"``) used in
    ``self._request(method, ...)`` inside *method*, or ``None``."""
    tree = _parse_source(method)
    if tree is None:
        return None
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "_request":
            continue
        if not isinstance(node.func.value, ast.Name):
            continue
        if node.func.value.id != "self":
            continue
        if not node.args:
            continue
        first_arg = node.args[0]
        if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
            return first_arg.value
    return None


def _imported_from_submodules(init_source: str) -> set[str]:
    """Parse ``__init__.py`` source and return names imported from
    relative submodules (``from .xxx import ...``)."""
    tree = ast.parse(init_source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.module is None:
            continue
        # Only relative imports — ``.agent``, ``.client``, etc.
        if not node.module.startswith("."):
            continue
        for alias in node.names:
            names.add(alias.name)
    return names


# ===========================================================================
# Individual checks
# ===========================================================================


def check_a(op_table: dict[str, Any], ops_mod: Any) -> list[str]:
    """Check A — OP_TABLE → handler existence.

    Every value in *op_table* must be a callable whose ``__name__`` exists
    in the ``robotsix_board_agent.ops`` module namespace.
    """
    errors: list[str] = []
    for op_name, handler in op_table.items():
        if not callable(handler):
            errors.append(f"Check A: OP_TABLE[{op_name!r}] value is not callable")
            continue
        hname = handler.__name__
        if not hasattr(ops_mod, hname):
            errors.append(
                f"Check A: OP_TABLE[{op_name!r}] handler {hname!r} "
                f"not found in robotsix_board_agent.ops"
            )
    return errors


def check_b(op_table: dict[str, Any], ops_mod: Any, client_cls: type) -> list[str]:
    """Check B — Handler → OP_TABLE coverage.

    Every function in *ops_mod* whose name matches ``_<snake_case>`` and
    whose first parameter is ``client: BoardClient`` must appear as a value
    in *op_table*.  ``dispatch`` is excluded explicitly.
    """
    errors: list[str] = []
    for name, obj in inspect.getmembers(ops_mod, inspect.isfunction):
        # Exclude dispatch — it's the dispatcher, not a handler.
        if name == "dispatch":
            continue
        # Handler convention: name starts with underscore.
        if not name.startswith("_"):
            continue
        # First parameter must be ``client: BoardClient``.
        try:
            sig = inspect.signature(obj)
        except ValueError, TypeError:
            continue
        params = list(sig.parameters.values())
        if not params:
            continue
        first = params[0]
        if first.name != "client":
            continue
        ann = first.annotation
        if ann is inspect.Parameter.empty:
            continue
        # With ``from __future__ import annotations`` the annotation is a
        # string; otherwise it is the class itself.
        if not (ann is client_cls or ann == "BoardClient"):
            continue

        # Must be wired into OP_TABLE.
        if obj not in op_table.values():
            errors.append(
                f"Check B: ops.{name}() matches handler convention but is not wired into OP_TABLE"
            )
    return errors


def check_c(op_table: dict[str, Any], client_cls: type) -> list[str]:
    """Check C — OP_TABLE → client method existence.

    For every OP_TABLE entry the handler must reference at least one
    ``BoardClient`` method, and every referenced method must actually exist
    on ``BoardClient``.
    """
    errors: list[str] = []
    for op_name, handler in op_table.items():
        methods = _client_method_calls_in_handler(handler)
        if not methods:
            errors.append(
                f"Check C: OP_TABLE[{op_name!r}] handler does not call any BoardClient method"
            )
            continue
        for method_name in methods:
            if not hasattr(client_cls, method_name):
                errors.append(
                    f"Check C: OP_TABLE[{op_name!r}] handler calls "
                    f"client.{method_name}() but BoardClient has no "
                    f"such method"
                )
    return errors


def check_d(op_table: dict[str, Any], client_cls: type) -> list[str]:
    """Check D — Client method → OP_TABLE coverage.

    Every public ``BoardClient`` method (excluding ``close``, ``_request``,
    ``_get_client``, and any Python dunder) must be called by at least one
    handler function referenced in *op_table*.
    """
    # Collect every client method called by any handler.
    called: set[str] = set()
    for handler in op_table.values():
        called.update(_client_method_calls_in_handler(handler))

    exclude = {"close", "_request", "_get_client"}
    errors: list[str] = []
    for name, _obj in inspect.getmembers(client_cls, inspect.isfunction):
        if name in exclude:
            continue
        if name.startswith("__") and name.endswith("__"):
            continue
        if name.startswith("_"):
            continue
        if name not in called:
            errors.append(
                f"Check D: BoardClient.{name}() is not called by any "
                f"handler in OP_TABLE (unreachable from agent-comm)"
            )
    return errors


def check_e(
    op_table: dict[str, Any],
    write_ops: frozenset[str],
    client_cls: type,
) -> list[str]:
    """Check E — WRITE_OPS consistency.

    Asserts:
    1. ``WRITE_OPS`` ⊆ ``OP_TABLE.keys()``.
    2. Every OP_TABLE entry whose handler calls a ``POST``-based client
       method must be in ``WRITE_OPS``.
    """
    errors: list[str] = []

    # (1) WRITE_OPS is a subset of OP_TABLE keys.
    for op_name in write_ops:
        if op_name not in op_table:
            errors.append(f"Check E: WRITE_OPS contains {op_name!r} which is not a key in OP_TABLE")

    # Build a mapping: op_name → set of HTTP methods used by its handler.
    op_http_methods: dict[str, set[str]] = {}
    for op_name, handler in op_table.items():
        methods = _client_method_calls_in_handler(handler)
        http_methods: set[str] = set()
        for method_name in methods:
            client_fn = getattr(client_cls, method_name, None)
            if client_fn is not None:
                hm = _http_method_of_client_fn(client_fn)
                if hm is not None:
                    http_methods.add(hm)
        op_http_methods[op_name] = http_methods

    # (2) POST-based handler → must be in WRITE_OPS.
    for op_name, http_methods in op_http_methods.items():
        if "POST" in http_methods and op_name not in write_ops:
            errors.append(
                f"Check E: OP_TABLE[{op_name!r}] calls a POST-based "
                f"client method but is not in WRITE_OPS"
            )

    return errors


def check_f(pkg: Any, init_source: str) -> list[str]:
    """Check F — ``__init__.py`` exports.

    1. Every name in ``robotsix_board_agent.__all__`` must be importable
       from ``robotsix_board_agent``.
    2. Every name imported from a submodule in ``__init__.py`` must appear
       in the package-level ``__all__``.
    """
    errors: list[str] = []
    pkg_all: list[str] = getattr(pkg, "__all__", [])

    # (1) __all__ names must be importable.
    for name in pkg_all:
        if not hasattr(pkg, name):
            errors.append(
                f"Check F: __all__ includes {name!r} but it is not "
                f"importable from robotsix_board_agent"
            )

    # (2) Submodule imports in __init__.py must be in __all__.
    imported = _imported_from_submodules(init_source)
    for name in imported:
        if name not in pkg_all:
            errors.append(f"Check F: {name!r} imported in __init__.py but not listed in __all__")

    return errors


def check_g(config_mod: Any, pkg_dir: Path) -> list[str]:
    """Check G — Config field consumption.

    Every field name declared in ``BoardAgentSettings.model_fields`` must
    appear as a substring in at least one ``.py`` source file under the
    package directory.
    """
    errors: list[str] = []
    settings_cls = getattr(config_mod, "BoardAgentSettings", None)
    if settings_cls is None:
        errors.append("Check G: BoardAgentSettings not found in config module")
        return errors

    # pydantic v2 uses ``model_fields``; v1 uses ``__fields__``.
    model_fields: dict[str, Any] = getattr(settings_cls, "model_fields", None) or getattr(
        settings_cls, "__fields__", {}
    )

    if not model_fields:
        errors.append("Check G: BoardAgentSettings.model_fields is empty or missing")
        return errors

    # Collect all .py source files under the package directory.
    source_paths: list[Path] = []
    for py_file in pkg_dir.rglob("*.py"):
        source_paths.append(py_file)

    for field_name in model_fields:
        found = False
        for py_file in source_paths:
            try:
                src = py_file.read_text()
            except OSError:
                continue
            if field_name in src:
                found = True
                break
        if not found:
            errors.append(
                f"Check G: Config field {field_name!r} is not consumed "
                f"in any .py file under {pkg_dir}"
            )

    return errors


# ===========================================================================
# Main
# ===========================================================================


def main() -> int:
    """Run all checks and return 0 on success, 1 on any failure."""
    # Package directory (for Check G).
    pkg_dir = Path(inspect.getfile(_config_mod)).parent

    # Source of __init__.py (for Check F).
    init_path = Path(inspect.getfile(robotsix_board_agent))
    init_source = init_path.read_text()

    # Ordered checks — label, function, args.
    checks: list[tuple[str, Callable[..., list[str]], tuple[Any, ...]]] = [
        ("A", check_a, (OP_TABLE, _ops_mod)),
        ("B", check_b, (OP_TABLE, _ops_mod, BoardClient)),
        ("C", check_c, (OP_TABLE, BoardClient)),
        ("D", check_d, (OP_TABLE, BoardClient)),
        ("E", check_e, (OP_TABLE, WRITE_OPS, BoardClient)),
        ("F", check_f, (robotsix_board_agent, init_source)),
        ("G", check_g, (_config_mod, pkg_dir)),
    ]

    all_errors: list[tuple[str, list[str]]] = []
    for label, check_fn, args in checks:
        errs = check_fn(*args)
        if errs:
            all_errors.append((label, errs))
        else:
            print(f"Check {label} ✓")

    if all_errors:
        for _label, errs in all_errors:
            for msg in errs:
                print(msg)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
