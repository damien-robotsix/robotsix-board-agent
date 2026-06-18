# Brokered Board Responder

`BrokeredBoardResponder` is the production entry point for structured board
operations over the agent-comm broker. It wraps a `BoardClient` and the
operation dispatcher behind a pull/mailbox `Agent` that listens for incoming
structured-op requests from a central broker — NAT-safe (outbound HTTP only,
the broker never dials back in).

## Initialisation

```python
from robotsix_board_agent.brokered import BrokeredBoardResponder
from robotsix_board_agent.config import BoardAgentSettings

settings = BoardAgentSettings(
    board_api_url="https://mill.example.com",
    board_api_token="sk-...",
    board_repo_id="my-repo",
    enable_write_ops=True,
)

responder = BrokeredBoardResponder(
    settings,
    broker_host="ai-broker.robotsix.net",
    broker_token="bk-...",
    broker_port=443,
    broker_scheme="https",
    agent_id="board-my-repo",       # optional — defaults to board-{repo_id}
    timeout=30.0,                   # broker pull timeout in seconds
)
```

## Constructor parameters

| Parameter       | Type                  | Default                  | Purpose                                        |
|-----------------|-----------------------|--------------------------|------------------------------------------------|
| `settings`      | `BoardAgentSettings`  | (required)               | Board API credentials and write-gate config    |
| `broker_host`   | `str`                 | (required)               | Central broker hostname                        |
| `broker_token`  | `str`                 | (required)               | Bearer token for the broker                    |
| `broker_port`   | `int`                 | `443`                    | Broker port                                    |
| `broker_scheme` | `str`                 | `"https"`                | `http` or `https`                              |
| `agent_id`      | `str \| None`         | `board-{repo_id}`        | This responder's agent identifier on the broker |
| `timeout`       | `float`               | `30.0`                   | Broker pull timeout in seconds                 |

## Lifecycle

`BrokeredBoardResponder` inherits from `_ThreadedLoopMixin`. It is synchronous
on the outside; all async board-client calls run on a dedicated daemon-thread
event loop.

### `start()`

Creates the internal event loop, registers the agent with the broker, and begins
listening for requests. Blocks until registration completes.

```python
responder.start()
```

### `stop()`

Deregisters the agent, closes the board client, and shuts down the event loop.
Thread-safe — may be called from any thread.

```python
responder.stop()
```

## Structured-op protocol

Incoming requests carry a JSON body with two fields:

| Field  | Type   | Purpose                                    |
|--------|--------|--------------------------------------------|
| `op`   | `str`  | Operation name (must be a key in `OP_TABLE`) |
| `args` | `dict` | Per-operation arguments                    |

The responder parses the body with `_parse_and_validate`, which maps `op` to a
`BoardOp` (including pydantic validation of `args`). Unknown ops return an
`UNKNOWN_OP` error.

## Write gate

When `settings.enable_write_ops` is `False` (the default is `True`; set to `False` to gate writes), any operation in
the `WRITE_OPS` set is rejected with a `WRITE_OPS_DISABLED` error before
dispatch. Write ops include `create_ticket`, `comment`, `transition`,
`approve`, `mark_done`, `merge_now`, `resume_blocked`, `migrate`, and
`set_priority`.

## Error handling

| Condition              | Error code          | Meaning                                        |
|------------------------|---------------------|------------------------------------------------|
| Malformed body         | `BAD_REQUEST`       | Body is not a JSON object or not valid JSON    |
| Invalid operation      | `BAD_REQUEST`       | `BoardOp` pydantic validation failed (missing/invalid `op` or `args`) |
| Unknown op             | `UNKNOWN_OP`        | `op` is not a key in `OP_TABLE`                |
| Write ops disabled     | `WRITE_OPS_DISABLED`| `enable_write_ops` is `False` and op is a write |
| Board API failure      | `BOARD_API_ERROR`   | Board client raised `BoardAPIError` (non-2xx)  |

Board API errors include the upstream `status_code` and `detail` in the error
message. `BAD_REQUEST` errors include a human-readable description of the parse
or validation failure.
