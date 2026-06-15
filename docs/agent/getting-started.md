# Getting Started

Configure the board agent, register it with an agent-comm `Registry`,
and send structured operations.

## 1. Install

```bash
pip install robotsix-board-agent
```

Or via git dependency (uv):

```toml
[tool.uv.sources]
robotsix-board-agent = { git = "https://github.com/damien-robotsix/robotsix-board-agent.git", rev = "main" }
```

## 2. Configure

Create a `BoardAgentSettings` instance with your board's credentials:

```python
from robotsix_board_agent import BoardAgentSettings

settings = BoardAgentSettings(
    board_api_url="http://localhost:8000",
    board_api_token="sk-...",
    board_repo_id="my-repo",
    enable_write_ops=True,   # optional, defaults to True
)
```

## 3. Register the agent

```python
from robotsix_agent_comm import Registry
from robotsix_board_agent import BoardAgent

registry = Registry()
agent = BoardAgent(settings, registry)
await agent.start()
```

The agent registers with id `board-<repo_id>` (or a custom id passed
via `agent_id=`).

## 4. Send structured operations

Other agents (or test code) send requests with a JSON body:

```json
{"op": "<name>", "args": {...}}
```

The agent dispatches the operation to the board API and returns a
`Response` with the result, or an `Error` on failure.

Read example — list open tickets:

```json
{"op": "list_tickets", "args": {"state": "open"}}
```

Write example — create a ticket:

```json
{"op": "create_ticket", "args": {"title": "Fix bug", "description": "It broke."}}
```

If `enable_write_ops` is `False`, write operations return an Error with
code `WRITE_OPS_DISABLED`.

## 5. Stop

```python
await agent.stop()
```

This deregisters the agent and closes the HTTP client.
