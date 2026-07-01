"""Tests for pure helper functions in scripts/completeness_check.py.

Covers the 6 AST-parsing / source-introspection helpers that are testable
in isolation without importing the full robotsix_board_agent package.
"""

from __future__ import annotations

import ast
import inspect
import os.path
import textwrap
from pathlib import Path
from unittest.mock import patch

from scripts.completeness_check import (
    _client_method_calls_in_handler,
    _env_keys_in_test_patches,
    _http_method_of_client_fn,
    _imported_from_submodules,
    _parse_source,
    _source_text,
)

# ---------------------------------------------------------------------------
# Module-level helpers for testing AST-walking functions.
#
# These MUST be defined at module level so that ``inspect.getsource`` returns
# source without leading indentation — ``ast.parse`` rejects indented source.
# ---------------------------------------------------------------------------


def _handler_with_single_client_call(client: object) -> None:
    client.get_ticket("123")


def _handler_with_multiple_client_calls(client: object) -> None:
    client.get_ticket("123")
    client.list_tickets()
    client.get_ticket("456")


def _handler_with_no_client_calls(client: object) -> None:
    print("hello")


def _handler_with_non_client_attribute(client: object) -> None:
    other.do_something()  # type: ignore[name-defined]  # noqa: F821
    client.get_ticket("123")


def _handler_with_attribute_access_not_call(client: object) -> None:
    _ = client.get_ticket  # attribute access, not a call


# NOTE: _http_method_of_client_fn walks the AST of the function body.  Because
# ``_parse_source`` calls ``ast.parse`` directly on the output of
# ``inspect.getsource`` without dedenting, methods defined inside a class
# (which have leading indentation) cause a ``SyntaxError`` and return None.
# The helpers below are standalone functions with ``self`` as the first
# parameter — they produce the right AST structure without indentation
# issues.  The indentation gap in ``_parse_source`` is a known limitation;
# the test file documents it via
# ``test_http_method_class_method_indentation_returns_none`` below.


def _get_ticket(self) -> None:
    self._request("GET", "/tickets/1")


def _create_ticket(self) -> None:
    self._request("POST", "/tickets", json={})


def _helper(self) -> None:
    pass


def _dynamic_method(self, verb: str) -> None:
    self._request(verb, "/path")


def _fn_with_local_request() -> None:
    def _request(method: str, path: str) -> None:
        pass

    _request("GET", "/path")


class _FakeClientMethod:
    """Class whose methods have indented source — used to test the
    indentation limitation of _http_method_of_client_fn."""

    def get_ticket(self) -> None:
        self._request("GET", "/tickets/1")


# ---------------------------------------------------------------------------
# _source_text
# ---------------------------------------------------------------------------


def test_source_text_known_function() -> None:
    """Returns the source text of a pure-Python function that has source."""
    result = _source_text(os.path.join)
    assert isinstance(result, str)
    assert "def join" in result


def test_source_text_builtin_returns_none() -> None:
    """Returns None for a built-in function (no source)."""
    assert _source_text(len) is None


def test_source_text_integer_returns_none() -> None:
    """Returns None for a non-callable object without source."""
    assert _source_text(42) is None


def test_source_text_oserror_returns_none() -> None:
    """Returns None when inspect.getsource raises OSError."""

    def _dummy() -> None:
        pass

    with patch.object(inspect, "getsource", side_effect=OSError("mock")):
        assert _source_text(_dummy) is None


# ---------------------------------------------------------------------------
# _parse_source
# ---------------------------------------------------------------------------


def test_parse_source_valid_function() -> None:
    """Returns an AST for a function with parseable source."""
    tree = _parse_source(os.path.join)
    assert tree is not None
    assert isinstance(tree, ast.AST)


def test_parse_source_no_source_returns_none() -> None:
    """Returns None when _source_text returns None (e.g. built-in)."""
    assert _parse_source(len) is None


def test_parse_source_syntax_error_returns_none() -> None:
    """Returns None when the source text has a syntax error."""

    def _dummy() -> None:
        pass

    with patch("scripts.completeness_check._source_text", return_value="def broken(:"):
        assert _parse_source(_dummy) is None


# ---------------------------------------------------------------------------
# _client_method_calls_in_handler
# ---------------------------------------------------------------------------


def test_client_method_calls_single_call() -> None:
    """Finds a single client.<method>() call in the handler."""
    methods = _client_method_calls_in_handler(_handler_with_single_client_call)
    assert methods == {"get_ticket"}


def test_client_method_calls_multiple_calls() -> None:
    """Finds multiple distinct client.<method>() calls."""
    methods = _client_method_calls_in_handler(_handler_with_multiple_client_calls)
    assert methods == {"get_ticket", "list_tickets"}


def test_client_method_calls_no_client_calls() -> None:
    """Returns an empty set when the handler makes no client.* calls."""
    methods = _client_method_calls_in_handler(_handler_with_no_client_calls)
    assert methods == set()


def test_client_method_calls_non_client_attribute() -> None:
    """Does not include calls on objects that are not named 'client'."""
    methods = _client_method_calls_in_handler(_handler_with_non_client_attribute)
    assert methods == {"get_ticket"}


def test_client_method_calls_not_a_call() -> None:
    """Does not match attribute access that is not a call."""
    methods = _client_method_calls_in_handler(_handler_with_attribute_access_not_call)
    assert methods == set()


# ---------------------------------------------------------------------------
# _http_method_of_client_fn
# ---------------------------------------------------------------------------


def test_http_method_get() -> None:
    """Returns 'GET' when the function calls self._request('GET', ...)."""
    result = _http_method_of_client_fn(_get_ticket)
    assert result == "GET"


def test_http_method_post() -> None:
    """Returns 'POST' when the function calls self._request('POST', ...)."""
    result = _http_method_of_client_fn(_create_ticket)
    assert result == "POST"


def test_http_method_no_request_call() -> None:
    """Returns None when the function does not call self._request."""
    result = _http_method_of_client_fn(_helper)
    assert result is None


def test_http_method_non_constant_first_arg() -> None:
    """Returns None when the first arg to _request is not a string constant."""
    result = _http_method_of_client_fn(_dynamic_method)
    assert result is None


def test_http_method_variable_named_request() -> None:
    """Does not match a call to a plain _request() function (not on self)."""
    result = _http_method_of_client_fn(_fn_with_local_request)
    assert result is None


def test_http_method_class_method_indentation_returns_none() -> None:
    """Returns None for a class method because its source has leading
    indentation, which ``ast.parse`` rejects — a known limitation of
    ``_parse_source``."""
    result = _http_method_of_client_fn(_FakeClientMethod.get_ticket)
    assert result is None


# ---------------------------------------------------------------------------
# _imported_from_submodules
# ---------------------------------------------------------------------------


def test_imported_from_submodules_relative_imports() -> None:
    """Parses __init__.py source with ``from .xxx import ...`` statements.

    NOTE: The function currently checks ``node.module.startswith(".")``,
    but Python's AST strips the leading dots from ``module`` — they are
    stored in ``node.level`` instead.  This means the function returns an
    empty set for all inputs (the check-gate is always False).  The test
    documents current behaviour; a fix is out of scope for this ticket.
    """
    source = textwrap.dedent("""\
        from .agent import BoardAgent
        from .client import BoardClient
        from .config import BoardAgentSettings
    """)
    names = _imported_from_submodules(source)
    # Current behaviour: always empty because the dot-prefix gate fails.
    assert names == set()


def test_imported_from_submodules_multi_import() -> None:
    """Handles ``from .module import A, B, C`` (currently returns empty)."""
    source = "from .ops import OP_TABLE, WRITE_OPS, dispatch\n"
    names = _imported_from_submodules(source)
    assert names == set()


def test_imported_from_submodules_no_relative_imports() -> None:
    """Returns an empty set when there are no relative imports."""
    source = textwrap.dedent("""\
        import os
        from pathlib import Path
        from typing import Any
    """)
    names = _imported_from_submodules(source)
    assert names == set()


def test_imported_from_submodules_empty_source() -> None:
    """Returns an empty set for an empty __init__.py."""
    names = _imported_from_submodules("")
    assert names == set()


def test_imported_from_submodules_absolute_import_excluded() -> None:
    """Does not include names from absolute (non-relative) imports."""
    source = "from robotsix_board_agent.client import BoardClient\n"
    names = _imported_from_submodules(source)
    assert names == set()


def test_imported_from_submodules_skips_import_without_module() -> None:
    """Does not crash on ``from . import foo`` (module is None)."""
    source = "from . import something\n"
    names = _imported_from_submodules(source)
    assert names == set()


# ---------------------------------------------------------------------------
# _env_keys_in_test_patches
# ---------------------------------------------------------------------------


def test_env_keys_single_patch(tmp_path: Path) -> None:
    """Extracts keys from a single patch.dict(os.environ, {...}) call."""
    test_file = tmp_path / "test_env.py"
    test_file.write_text(
        textwrap.dedent("""\
            from unittest.mock import patch
            patch.dict(
                os.environ,
                {"BOARD_API_URL": "https://example.com", "BOARD_API_TOKEN": "tok"},
            )
        """)
    )
    keys = _env_keys_in_test_patches(test_file)
    assert keys == {"BOARD_API_URL", "BOARD_API_TOKEN"}


def test_env_keys_multiple_patches(tmp_path: Path) -> None:
    """Extracts keys across multiple patch.dict calls."""
    test_file = tmp_path / "test_env.py"
    test_file.write_text(
        textwrap.dedent("""\
            patch.dict(os.environ, {"A": "1"})
            patch.dict(os.environ, {"B": "2", "C": "3"})
        """)
    )
    keys = _env_keys_in_test_patches(test_file)
    assert keys == {"A", "B", "C"}


def test_env_keys_no_patches(tmp_path: Path) -> None:
    """Returns an empty set when there are no patch.dict(os.environ, ...) calls."""
    test_file = tmp_path / "test_env.py"
    test_file.write_text(
        textwrap.dedent("""\
            def test_thing():
                assert True
        """)
    )
    keys = _env_keys_in_test_patches(test_file)
    assert keys == set()


def test_env_keys_empty_file(tmp_path: Path) -> None:
    """Returns an empty set for an empty file."""
    test_file = tmp_path / "test_env.py"
    test_file.write_text("")
    keys = _env_keys_in_test_patches(test_file)
    assert keys == set()


def test_env_keys_syntax_error(tmp_path: Path) -> None:
    """Returns an empty set when the file has a syntax error."""
    test_file = tmp_path / "test_env.py"
    test_file.write_text("this is not valid python {{{{{\n")
    keys = _env_keys_in_test_patches(test_file)
    assert keys == set()


def test_env_keys_missing_file(tmp_path: Path) -> None:
    """Returns an empty set when the file does not exist."""
    missing = tmp_path / "nonexistent.py"
    keys = _env_keys_in_test_patches(missing)
    assert keys == set()


def test_env_keys_skips_non_dict_second_arg(tmp_path: Path) -> None:
    """Does not crash when the second arg to patch.dict is not a dict literal."""
    test_file = tmp_path / "test_env.py"
    test_file.write_text(
        textwrap.dedent("""\
            env_vars = {"BOARD_API_URL": "x"}
            patch.dict(os.environ, env_vars)
        """)
    )
    keys = _env_keys_in_test_patches(test_file)
    assert keys == set()


def test_env_keys_skips_non_string_keys(tmp_path: Path) -> None:
    """Only collects keys that are string constants."""
    test_file = tmp_path / "test_env.py"
    test_file.write_text(
        textwrap.dedent("""\
            KEY = "BOARD_API_URL"
            patch.dict(os.environ, {KEY: "val"})
        """)
    )
    keys = _env_keys_in_test_patches(test_file)
    assert keys == set()


def test_env_keys_non_os_environ_first_arg(tmp_path: Path) -> None:
    """Does not match patch.dict when the first arg is not os.environ."""
    test_file = tmp_path / "test_env.py"
    test_file.write_text(
        textwrap.dedent("""\
            patch.dict(other.module, {"KEY": "val"})
        """)
    )
    keys = _env_keys_in_test_patches(test_file)
    assert keys == set()


def test_env_keys_fully_qualified_patch_not_matched(tmp_path: Path) -> None:
    """unittest.mock.patch.dict is NOT matched — the AST gate requires
    func.value to be a simple Name('patch'), not an Attribute chain."""
    test_file = tmp_path / "test_env.py"
    test_file.write_text(
        textwrap.dedent("""\
            import unittest.mock
            unittest.mock.patch.dict(os.environ, {"BOARD_REPO_ID": "repo"})
        """)
    )
    keys = _env_keys_in_test_patches(test_file)
    assert keys == set()
