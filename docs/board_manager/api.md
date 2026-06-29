# Board Manager

`BoardManager` is an LLM-powered, natural-language board manager. It registers
on the central broker (pull/mailbox mode) and accepts natural-language
instructions — "close all stale draft tickets", "what is the status of the auth
epic?" — then acts directly on the board through its tool set.

## Initialisation

```python
from pathlib import Path
from robotsix_board_agent.board_manager import BoardManager
from robotsix_board_agent.config import BoardAgentSettings

settings = BoardAgentSettings(
    board_api_url="https://mill.example.com",
    board_api_token="sk-...",
    board_repo_id="my-repo",
    enable_write_ops=True,
)

manager = BoardManager(
    settings,
    broker_host="ai-broker.robotsix.net",
    broker_token="bk-...",
    memory_path=Path("memory.json"),
    broker_port=443,
    broker_scheme="https",
    agent_id="board-manager-my-repo",   # optional — defaults to board-manager-{repo_id}
    manager_model="openai/gpt-4o",      # optional — level-3 model
    recall_model="openai/gpt-4o-mini",  # optional — level-1 model
    max_conversations=200,
    timeout=120.0,
)
```

## Constructor parameters

| Parameter                | Type                 | Default                           | Purpose                                          |
|--------------------------|----------------------|-----------------------------------|--------------------------------------------------|
| `settings`               | `BoardAgentSettings` | (required)                        | Board API credentials and repository identity    |
| `broker_host`            | `str`                | (required)                        | Central broker hostname                          |
| `broker_token`           | `str`                | (required)                        | Bearer token for the broker                      |
| `memory_path`            | `Path`               | (required)                        | JSON file for conversation trace persistence     |
| `broker_port`            | `int`                | `443`                             | Broker port                                      |
| `broker_scheme`          | `str`                | `"https"`                         | `http` or `https`                                |
| `agent_id`               | `str \| None`        | `board-manager-{repo_id}`         | This manager's agent identifier on the broker    |
| `manager_model`          | `str \| None`        | (provider default)                | Model for the level-3 acting agent               |
| `recall_model`           | `str \| None`        | (provider default)                | Model for the level-1 recall agent               |
| `max_conversations`      | `int`                | `200`                             | Max Q→A pairs retained in memory                 |
| `max_recall_conversations`| `int`               | `50`                              | Max prior conversations fed into recall-prompt   |
| `simple_read_model`      | `str`                | `"haiku"`                         | Claude model alias for SIMPLE_READ-classified requests|
| `moderate_model`         | `str`                | `"sonnet"`                        | Claude model alias for MODERATE-classified requests (CRUD/dedup)|
| `classify_model`         | `str \| None`        | (provider default)                | Model override for the level-1 complexity classifier|
| `timeout`                | `float`              | `120.0`                           | Broker pull timeout in seconds                   |

## Natural-language interface

Incoming requests must include a JSON body with a `"message"` field containing
the user's natural-language instruction. Missing or blank
messages return a `BAD_REQUEST` error.

```python
# Sent over the broker as a Request body:
{"message": "list all tickets in progress"}
```

The manager runs the instruction through a two-stage LLM pipeline and returns a
`Response` with `{"reply": "<answer>"}`. After each turn the Q→A pair is
appended to persistent memory.

## LLM pipeline

### Level 1 — recall scan

A cheap level-1 agent scans the most recent conversations from the
conversation trace (up to `max_recall_conversations`, default 50) for
exchanges relevant to the new question. Older entries beyond this cap are
kept on disk for traceability but excluded from the recall prompt, preventing
accumulated history from bloating every invocation. This retrieves related
decisions, tickets, or tasks without the cost of a full context window. If
nothing is relevant, the recall agent replies `"none"`.

### Level 3 — acting manager

A level-3 agent with 16 board-operation tools + the `update_memory` and
`lookup_reference` tools processes the instruction. Its system prompt includes:

- The board repository identity
- The agent's **maintained memory** — a curated note of durable board state,
  ongoing tasks, and user preferences (not a transcript), capped at a few
  hundred words
- Any relevant prior exchanges from the level-1 recall scan

Reference material (state-machine catalog, repo registry, epic genealogy,
approval inventories) is **not** injected into every call — it is stored in
a separate on-disk file and fetched on-demand via the `lookup_reference` tool
only when a request genuinely needs it.

The level-3 agent runs the user's question through `h3.run_sync` and returns
its final output as the reply.

## Available tools

All tools wrap `BoardClient` methods and return JSON-dumped results capped at
12,000 characters. `BoardAPIError` exceptions are caught and returned as error
strings.

| Tool                 | Signature                                   | Board endpoint                         |
|----------------------|---------------------------------------------|----------------------------------------|
| `list_tickets`       | `state: str \| None = None`                 | `GET /tickets`                         |
| `get_ticket`         | `ticket_id: str`                            | `GET /tickets/{id}`                    |
| `board_cards`        | (none)                                      | `GET /board/cards`                     |
| `ticket_history`     | `ticket_id: str`                            | `GET /tickets/{id}/history`            |
| `merge_status`       | `ticket_id: str`                            | `GET /tickets/{id}/merge-status`       |
| `ticket_description` | `ticket_id: str`                            | `GET /tickets/{id}/description`        |
| `get_multiple_ticket_descriptions` | `ticket_ids: list[str]`        | `GET /tickets/{id}/description (×N)`   |
| `create_ticket`      | `title: str, description: str`              | `POST /tickets`                        |
| `comment`            | `ticket_id: str, body: str`                 | `POST /tickets/{id}/comments`          |
| `transition`         | `ticket_id: str, state: str, note: str = ""`| `POST /tickets/{id}/transition`        |
| `approve`            | `ticket_id: str`                            | `POST /tickets/{id}/approve`           |
| `mark_done`          | `ticket_id: str, note: str = ""`            | `POST /tickets/{id}/mark-done`         |
| `merge_now`          | `ticket_id: str`                            | `POST /tickets/{id}/merge-now`         |
| `migrate`            | `ticket_id: str, target_repo_id: str`       | `POST /tickets/{id}/migrate`           |
| `resume_blocked`     | `ticket_id: str`                            | `POST /tickets/{id}/resume-blocked`    |
| `set_priority`       | `ticket_id: str, priority: bool`            | `POST /tickets/{id}/priority`          |
| `update_memory`      | `memory: str`                               | (internal — writes maintained memory)  |
| `lookup_reference`   | `query: str`                                | (internal — searches reference material)|

The `update_memory` tool allows the level-3 agent to curate its own maintained
memory note. The agent is prompted to rewrite the note (not append) to keep it
concise and coherent. If the note exceeds the character cap, `update_memory`
returns a truncation notice so the agent can trim stale entries.

The `lookup_reference` tool searches a separate reference-material file
(state-machine catalog, repo registry, epic genealogy, approval inventories)
that is **not** injected on every call — the agent fetches it on-demand via
a keyword query when a request genuinely needs that information.

## Lifecycle

`BoardManager` inherits from `_ThreadedLoopMixin` (same as
`BrokeredBoardResponder`). Call `start()` to register with the broker and begin
listening, `stop()` to tear down.

```python
manager.start()
# ... manager serves requests ...
manager.stop()
```

## Error handling

| Condition          | Error code     | Meaning                                   |
|--------------------|----------------|-------------------------------------------|
| Missing/blank body | `BAD_REQUEST`  | No `message` field provided |
