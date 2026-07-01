# AGENT.md — robotsix-board-agent

Hard rules that agents MUST follow when operating on this repo. Violating
these rules will produce incorrect proposals, broken tests, or unsafe
changes.

## Testing conventions

### BoardClient: use `httpx.MockTransport`, never `unittest.mock.patch`

`BoardClient` (in `src/robotsix_board_agent/client.py`) wraps
`httpx.AsyncClient`.  It accepts an optional `transport=` kwarg — inject an
`httpx.MockTransport` to intercept every HTTP call without touching the
network.

```python
import httpx
from robotsix_board_agent.client import BoardClient

transport = httpx.MockTransport(lambda _: httpx.Response(200, json={"key": "val"}))
# Reassign transport.handler per-test to control responses.
client = BoardClient(settings, transport=transport)
```

The shared `mock_transport` fixture in `tests/conftest.py` returns a bare
mock (200, `{}`).  Individual tests reassign `mock_transport.handler` to
customise the response.

Never mock `httpx.AsyncClient` or any of its methods directly — the
`transport=` injection is the designated seam.

### BoardManager: patch `_converse` or the agent-comm imports

`BoardManager` (in `src/robotsix_board_agent/board_manager.py`) has two
key seams:

- **`_handle_request` tests**: `patch.object(manager, "_converse",
  return_value=...)` — isolates request dispatch from the LLM loop.
- **`_converse` tests**: patch at import-source level:
  - `patch("robotsix_llmio.build_agent_for_level")` — returns a mock agent.
  - `patch("robotsix_llmio.core.run.run_agent")` — returns canned output.

### Agent-comm stubs are injected in conftest

The entire `robotsix_agent_comm` package is stubbed in `sys.modules` by
`tests/conftest.py`.  Tests that need agent-comm types (`Agent`, `Registry`,
`Request`, `Response`, `BrokeredAgent`) get them from these stubs — **never**
import the real `robotsix-agent-comm` SDK in tests.

If you add a test that needs a new agent-comm type/attribute, add it to the
stubs in `tests/conftest.py` — do NOT add `robotsix-agent-comm` as a test
dependency.

## Configuration invariants

### `BoardAgentSettings` (src/robotsix_board_agent/config.py)

A plain `pydantic.BaseModel` (NOT `pydantic_settings.BaseSettings`):

| Field | Type | Purpose |
|---|---|---|
| `board_api_url` | `str` | Base URL of the mill board REST API |
| `board_api_token` | `str` | Bearer token for API auth |
| `board_repo_id` | `str` | Repo identifier for ticket scoping |
| `enable_write_ops` | `bool` | Default `True`; set `False` for read-only agents |
| `max_output_chars` | `int` | Default `2000`; max chars in final reply before truncation (0 disables) |

All fields are passed explicitly by the caller — there is no automatic
env-var loading.  The caller (e.g. `robotsix-mill` or `robotsix-auto-mail`)
reads env vars like `BOARD_API_URL`, `BOARD_API_TOKEN`, `BOARD_REPO_ID`
itself and constructs the model.

**Do not** convert this model to `BaseSettings` or add `Field(env=...)`
annotations — the env-var loading is owned by the consuming repos, not
by this library.

**When adding a new field** to `BoardAgentSettings` in `config.py`, add
a corresponding row to the field table above so the documentation stays
in sync with the code.

### Environment variables (consumed by callers, not this library)

| Variable | Purpose |
|---|---|
| `BOARD_API_URL` | Board REST API base URL |
| `BOARD_API_TOKEN` | API bearer token |
| `BOARD_REPO_ID` | Repo identifier |
| `LANGFUSE_PUBLIC_KEY` | Langfuse public key (read by `setup_langfuse_tracing`) |
| `LANGFUSE_SECRET_KEY` | Langfuse secret key |
| `LANGFUSE_HOST` | Langfuse host URL |
| `OPENROUTER_API_KEY` | OpenRouter API key (consumed by mill/auto-mail) |

## Board API contract

This agent communicates with a **remote REST API** at `board_api_url` — it
does NOT import `robotsix-board` or any board-internal modules.

The `BoardClient` class in `src/robotsix_board_agent/client.py` is the
single integration point:

- All requests go through `_request(method, path, **kwargs)`.
- Auth is a Bearer token in the `Authorization` header.
- Endpoints mirror the board's REST API: `/tickets`, `/tickets/{id}`,
  `/repos/{repo_id}/cards`, `/merge`, etc.

**Never** add a direct `import robotsix_board` or `from robotsix_board ...`
anywhere in this repo.  The contract is HTTP, not Python imports.

## Langfuse tracing

Two modules call `setup_langfuse_tracing()` from
`robotsix_llmio.core` — both at module level, inside try/except ImportError
guards (so the library works without `robotsix_llmio` installed):

- `src/robotsix_board_agent/agent.py` (line ~55)
- `src/robotsix_board_agent/board_manager.py` (line ~33)

The call is idempotent — it is safe (and intentional) to call it from both
modules.  The try/except guard MUST be preserved — removing it would make
`robotsix_llmio` a hard dependency.

When adding a new module that exercises LLM paths, add the same
idempotent `setup_langfuse_tracing()` call at module level with the
try/except ImportError guard.

## Logging delegation

Logging setup delegates to `robotsix_llmio.logging.setup_logging` in
`src/robotsix_board_agent/agent.py` (module level, inside try/except
ImportError):

```python
try:
    from robotsix_llmio.logging import setup_logging as _llmio_setup_logging
    _llmio_setup_logging(loggers=["robotsix_board_agent"])
except ImportError:
    import logging as _logging
    _logging.basicConfig(level=_logging.INFO, ...)
```

The call is idempotent so it is safe on repeated imports.  Other modules
(e.g. `board_manager.py`) use `logging.getLogger(__name__)` and rely on this
setup having already run.

**Never** add a second logging framework (loguru, structlog, etc.).  The
stdlib `logging` module configured by `robotsix_llmio.logging` is the single
source of truth for all log output in this repo.

## Tool registration (OP_TABLE)

`src/robotsix_board_agent/ops.py` defines `OP_TABLE` — a flat `dict[str,
Callable]` mapping operation names to async handler functions.
`BoardManager._build_tools()` reads this table to build LLM tools.

To add a new board operation:

1. Define a Pydantic `*Args` model for the operation's arguments.
2. Write an `async def _<op_name>(client: BoardClient, args: dict[str, Any])
   -> dict[str, Any]` handler that validates args and calls the appropriate
   `BoardClient` method.
3. Add `"op_name": _op_name` to `OP_TABLE`.
4. If the operation mutates data, add `"op_name"` to the `WRITE_OPS`
   frozenset.

The `dispatch()` function wraps `OP_TABLE` lookups and raises
`UnknownOpError` on unknown operations.

Do NOT add ops that bypass `OP_TABLE` — every operation the agent can
execute MUST be registered there so tool building and access control
(write-op gating) remain consistent.

## General invariants

- **Python 3.14+ only.**  PEP 758 syntax (bare `except A, B:`) is expected
  and enforced by ruff.
- **`ruff format` is the single formatter.**  Do not add black, isort, or
  other formatters.  Line length: 100 characters, double quotes.
- **`mypy --strict`.**  New code must pass strict mypy.
- **Pre-commit hooks** run ruff, mypy, bandit, detect-secrets, and
  file-hygiene checks.  Run `uv run pre-commit run --all-files` before
  proposing changes.
- **uv lockfile.**  `uv.lock` is committed.  When `pyproject.toml` deps
  change, run `uv lock` and commit the updated lockfile.  Never hand-edit
  `uv.lock`.
- **No generated artifacts.**  Do not commit build output, coverage reports,
  or compiled assets.

## Documentation conventions

- **`mkdocs.yml` nav entries.**  When adding a new documentation file under
  `docs/`, add a corresponding entry in `mkdocs.yml` under the `nav:` section.
  A missing nav entry makes the page undiscoverable from the documentation
  sidebar even if it is referenced from other docs or listed in
  `modules.yaml`.
