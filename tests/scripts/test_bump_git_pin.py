"""Tests for scripts/bump_git_pin.py."""

import textwrap
from pathlib import Path

import pytest
from scripts.bump_git_pin import bump


def _make_pyproject(package_name: str, rev: str) -> str:
    return textwrap.dedent(f"""\
        [project]
        name = "test"

        [tool.uv.sources]
        {package_name} = {{ git = "https://example.com/repo.git", rev = "{rev}" }}
    """)


def test_bump_updates_rev(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Replaces the rev value while preserving surrounding TOML."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(_make_pyproject("my-pkg", "abc123"))

    monkeypatch.setattr("scripts.bump_git_pin.PYPROJECT", pyproject)

    assert bump("my-pkg", "def456") is True

    content = pyproject.read_text()
    assert 'rev = "def456"' in content
    assert 'rev = "abc123"' not in content
    # Comments and other TOML remain intact.
    assert "[project]" in content
    assert 'git = "https://example.com/repo.git"' in content


def test_bump_no_match_is_noop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Returns False and leaves the file unchanged when the package is absent."""
    pyproject = tmp_path / "pyproject.toml"
    orig = _make_pyproject("other-pkg", "abc123")
    pyproject.write_text(orig)

    monkeypatch.setattr("scripts.bump_git_pin.PYPROJECT", pyproject)

    assert bump("missing-pkg", "def456") is False
    assert pyproject.read_text() == orig


def test_bump_multi_entry_updates_first(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When the package name appears in multiple entries, only the first is changed."""
    pyproject = tmp_path / "pyproject.toml"
    content = _make_pyproject("my-pkg", "abc123") + _make_pyproject("my-pkg", "abc123")
    pyproject.write_text(content)

    monkeypatch.setattr("scripts.bump_git_pin.PYPROJECT", pyproject)

    assert bump("my-pkg", "def456") is True
    result = pyproject.read_text()
    assert result.count('rev = "def456"') == 1
    assert result.count('rev = "abc123"') == 1
