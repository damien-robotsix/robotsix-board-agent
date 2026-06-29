# Constants Reference

Shared defaults and error codes used across the board agent package.

## Default constants

| Constant                  | Value          | Usage                                              |
|---------------------------|----------------|----------------------------------------------------|
| `DEFAULT_TICKET_SOURCE`   | `"agent"`      | Default `source` field when creating tickets.      |
| `DEFAULT_TICKET_KIND`     | `"task"`       | Default `kind` field when creating tickets.         |
| `DEFAULT_COMMENT_AUTHOR`  | `"board-agent"`| Default `author` field when posting comments.       |
| `DEFAULT_NOTE`            | `""`           | Default `note` field for transitions and mark-done. |

These constants are consumed by the Pydantic argument models in
`ops.py` and by the client methods in `client.py`.

## BoardErrorCode

```python
from robotsix_board_agent.constants import BoardErrorCode
```

An enum of error codes used in agent-comm `Error` responses:

| Member               | Value                  | Description                                    |
|----------------------|------------------------|------------------------------------------------|
| `BAD_REQUEST`        | `"BAD_REQUEST"`        | The request body could not be parsed.           |
| `UNKNOWN_OP`         | `"UNKNOWN_OP"`         | The operation name is not recognised.           |
| `WRITE_OPS_DISABLED` | `"WRITE_OPS_DISABLED"` | Write operations are disabled via settings.     |
| `BOARD_API_ERROR`    | `"BOARD_API_ERROR"`    | The upstream board API returned a non-2xx.      |
