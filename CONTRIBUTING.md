# Contributing to robotsix-board-agent

Welcome! This guide will help you set up your development environment and
submit changes.

## Development environment

This project uses [uv](https://docs.astral.sh/uv/) for dependency management.
Install uv and then sync the project:

```bash
uv sync
```

This installs all dependencies (including dev and docs groups) into a local
virtual environment.

## Running tests

```bash
uv run pytest
```

Tests live under `tests/` and use pytest with asyncio support.  To run a
subset of tests, pass a path or `-k` expression:

```bash
uv run pytest tests/path/to/test_file.py
uv run pytest -k "pattern"
```

## Linting and formatting

```bash
# Lint
uv run ruff check .

# Format check (CI mode)
uv run ruff format . --check

# Auto-format in place
uv run ruff format .
```

## Type checking

```bash
uv run mypy
```

The project uses strict mypy settings (`strict = true` in `pyproject.toml`).

## Pre-commit hooks

Pre-commit hooks run automatically on each commit. Install them once:

```bash
uv run pre-commit install
```

The hooks run ruff (check + format), mypy, bandit, detect-secrets, and
general file hygiene checks.  You can also run them manually without
committing:

```bash
uv run pre-commit run --all-files
```

## Pull request process

1. Create a feature branch from `main`.
2. Make your changes, including tests for new functionality.
3. Run the full CI check locally:
   ```bash
   uv run ruff check . && uv run ruff format . --check && uv run mypy && uv run pytest
   ```
4. **Update the changelog.**  Add an entry under `## [Unreleased]` in
   `CHANGELOG.md` describing your change.  Use the appropriate subheading:
   `### Added`, `### Fixed`, `### Changed`, `### Deprecated`, `### Removed`,
   or `### Security`.  If your PR does not need a changelog entry (e.g.
   docs-only, refactoring, dependency bump), add the `skip-changelog` label.
5. Open a pull request.  CI will run the same checks automatically.
6. Wait for review; address feedback if requested.
7. Once approved and CI passes, your PR will be merged.

## Style conventions

- Python 3.14+ only (PEP 758 syntax is expected).
- Line length: 100 characters (ruff).
- Double quotes for strings (ruff).
- Use `ruff format` — don't fight the formatter.
