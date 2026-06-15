# robotsix-board-agent

A reusable **agent-comm** agent that exposes the mill board's full ticket
lifecycle over structured messages — query, file, comment, transition,
approve, merge, resume, migrate — so other agents can drive a board
programmatically.

Consumed by both **robotsix-mill** and **robotsix-auto-mail** as a git
dependency — built once, run twice, each pointed at its own board.

## Quick start

```python
from robotsix_board_agent import BoardAgent, BoardAgentSettings
from robotsix_agent_comm import Registry

settings = BoardAgentSettings(
    board_api_url="http://localhost:8000",
    board_api_token="sk-...",
    board_repo_id="my-repo",
)
registry = Registry()
agent = BoardAgent(settings, registry)
await agent.start()
```

Send a structured operation (e.g. via another agent):

```json
{"op": "create_ticket", "args": {"title": "Fix bug", "description": "It broke."}}
```

See [docs/agent/getting-started.md](docs/agent/getting-started.md) for details and
[docs/ops/operations.md](docs/ops/operations.md) for the full operation reference.

## License

MIT — see [LICENSE](LICENSE).
