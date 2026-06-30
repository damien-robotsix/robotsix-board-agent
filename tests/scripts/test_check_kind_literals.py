"""Tests for scripts/check_kind_literals.py."""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path

import pytest
from scripts.check_kind_literals import (
    _find_kind_literals,
    _is_kind_context,
    _read_default_ticket_kind,
    _set_parents,
    main,
)

# ---------------------------------------------------------------------------
# _is_kind_context
# ---------------------------------------------------------------------------


def _make_ast(source: str) -> ast.AST:
    """Parse *source* as an AST module and attach parent references."""
    tree = ast.parse(textwrap.dedent(source))
    _set_parents(tree)
    return tree


def _find_constant(tree: ast.AST, value: str) -> ast.Constant:
    """Return the first ast.Constant node in *tree* with string *value*."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value == value:
            return node
    raise AssertionError(f"Constant {value!r} not found in AST")


def test_is_kind_context_keyword_arg() -> None:
    """A string in a ``kind=<literal>`` keyword argument is a kind context."""
    tree = _make_ast("func(kind='task')")
    node = _find_constant(tree, "task")
    assert _is_kind_context(node) is True


def test_is_kind_context_dict_value() -> None:
    """A string in a ``{'kind': <literal>}`` dict is a kind context."""
    tree = _make_ast("{'kind': 'task'}")
    node = _find_constant(tree, "task")
    assert _is_kind_context(node) is True


def test_is_kind_context_unrelated_keyword_arg() -> None:
    """A string in a non-kind keyword argument is NOT a kind context."""
    tree = _make_ast("func(title='task')")
    node = _find_constant(tree, "task")
    assert _is_kind_context(node) is False


def test_is_kind_context_unrelated_dict_key() -> None:
    """A string under a dict key that is not 'kind' is NOT a kind context."""
    tree = _make_ast("{'type': 'task'}")
    node = _find_constant(tree, "task")
    assert _is_kind_context(node) is False


def test_is_kind_context_no_parent() -> None:
    """A node with no _parent attribute is NOT a kind context."""
    node = ast.Constant(value="task")
    # _parent is not set
    assert _is_kind_context(node) is False


def test_is_kind_context_dict_key_itself_is_not_kind() -> None:
    """The key 'kind' itself (not its value) is NOT a kind context."""
    tree = _make_ast("{'kind': 'task'}")
    # Find the key string "kind", not the value "task"
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and node.value == "kind":
            assert _is_kind_context(node) is False
            return
    raise AssertionError("Key 'kind' not found")


# ---------------------------------------------------------------------------
# _read_default_ticket_kind
# ---------------------------------------------------------------------------


def test_read_default_ticket_kind_found(tmp_path: Path) -> None:
    """Returns the DEFAULT_TICKET_KIND value from a valid constants.py."""
    constants = tmp_path / "constants.py"
    constants.write_text('DEFAULT_TICKET_KIND = "bug"\n')
    assert _read_default_ticket_kind(constants) == "bug"


def test_read_default_ticket_kind_other_assign(tmp_path: Path) -> None:
    """Ignores other assignments and only extracts DEFAULT_TICKET_KIND."""
    constants = tmp_path / "constants.py"
    constants.write_text(
        textwrap.dedent("""\
            OTHER_CONSTANT = "ignored"
            DEFAULT_TICKET_KIND = "feature"
            ANOTHER_CONSTANT = 42
        """)
    )
    assert _read_default_ticket_kind(constants) == "feature"


def test_read_default_ticket_kind_not_found(tmp_path: Path) -> None:
    """Exits with error when DEFAULT_TICKET_KIND is not in the file."""
    constants = tmp_path / "constants.py"
    constants.write_text("OTHER = 'value'\n")
    with pytest.raises(SystemExit) as exc_info:
        _read_default_ticket_kind(constants)
    assert exc_info.value.code is not None
    assert "DEFAULT_TICKET_KIND not found" in str(exc_info.value.code)


def test_read_default_ticket_kind_file_missing(tmp_path: Path) -> None:
    """Exits with error when the file cannot be read."""
    missing = tmp_path / "nonexistent.py"
    with pytest.raises(SystemExit) as exc_info:
        _read_default_ticket_kind(missing)
    assert exc_info.value.code is not None
    assert "cannot read" in str(exc_info.value.code)


# ---------------------------------------------------------------------------
# _find_kind_literals
# ---------------------------------------------------------------------------


def test_find_kind_literals_keyword_args(tmp_path: Path) -> None:
    """Discovers kind literals in keyword argument context."""
    source = tmp_path / "example.py"
    source.write_text(
        textwrap.dedent("""\
            thing = Ticket(kind="task")
            other = Ticket(kind="bug")
        """)
    )
    results = _find_kind_literals(source)
    assert results == [(1, "task"), (2, "bug")]


def test_find_kind_literals_dict_values(tmp_path: Path) -> None:
    """Discovers kind literals in dict value context."""
    source = tmp_path / "example.py"
    source.write_text(
        textwrap.dedent("""\
            data = {"kind": "task", "other": "ignored"}
        """)
    )
    results = _find_kind_literals(source)
    assert results == [(1, "task")]


def test_find_kind_literals_non_kind_context_excluded(tmp_path: Path) -> None:
    """Does not return literals that are not in a kind context."""
    source = tmp_path / "example.py"
    source.write_text(
        textwrap.dedent("""\
            name = "task"
            title = "bug"
            kind = "task"
            foo(bar="task")
        """)
    )
    results = _find_kind_literals(source)
    # "kind = 'task'" on line 3 is an assignment, not a keyword arg
    # None of these lines is a kind context
    assert results == []


def test_find_kind_literals_syntax_error_returns_empty(tmp_path: Path) -> None:
    """Returns an empty list for files with syntax errors."""
    source = tmp_path / "broken.py"
    source.write_text("this is not valid python {{{{{\n")
    assert _find_kind_literals(source) == []


def test_find_kind_literals_missing_file_returns_empty(tmp_path: Path) -> None:
    """Returns an empty list when the file does not exist."""
    missing = tmp_path / "nonexistent.py"
    assert _find_kind_literals(missing) == []


def test_find_kind_literals_empty_file(tmp_path: Path) -> None:
    """Returns an empty list for an empty file."""
    source = tmp_path / "empty.py"
    source.write_text("")
    assert _find_kind_literals(source) == []


def test_find_kind_literals_variable_keyword(tmp_path: Path) -> None:
    """Discovers kind literals even when the value is on a different source line."""
    source = tmp_path / "example.py"
    source.write_text(
        textwrap.dedent("""\
            thing = Ticket(
                kind="task"
            )
        """)
    )
    results = _find_kind_literals(source)
    assert results == [(2, "task")]


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def test_main_passes_on_clean_sources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Returns 0 when all kind literals in the tree match the default."""
    # Create a minimal src tree with a valid kind literal.
    src = tmp_path / "src"
    src.mkdir()
    (src / "__init__.py").write_text("")

    example = src / "example.py"
    example.write_text('ticket = Ticket(kind="task")\n')

    # Patch the module-level globals so main() scans our tmp tree.
    monkeypatch.setattr("scripts.check_kind_literals._REPO_ROOT", tmp_path)
    # The script reads _DEFAULT_KIND from the real constants.py at import time.
    # We rely on the default being "task", which matches the literal above.

    assert main() == 0


def test_main_fails_on_unknown_kind(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Returns 1 when a kind literal is not in the valid set."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "__init__.py").write_text("")

    example = src / "example.py"
    example.write_text('ticket = Ticket(kind="unknown_kind")\n')

    monkeypatch.setattr("scripts.check_kind_literals._REPO_ROOT", tmp_path)

    # "unknown_kind" is not the default "task" and not in _VALID_KINDS.
    assert main() == 1


def test_main_prints_errors_on_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Prints specific error messages when literals don't match."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "__init__.py").write_text("")

    example = src / "example.py"
    example.write_text('ticket = Ticket(kind="unknown_kind")\n')

    monkeypatch.setattr("scripts.check_kind_literals._REPO_ROOT", tmp_path)

    main()
    captured = capsys.readouterr()
    assert "unknown_kind" in captured.out
    assert "example.py" in captured.out
