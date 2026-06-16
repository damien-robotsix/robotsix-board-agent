# Config Reference

`BoardAgentSettings` is a pydantic model that holds the configuration
for the board agent and client.

## Fields

| Field               | Type    | Default | Description                                                    |
|---------------------|---------|---------|----------------------------------------------------------------|
| `board_api_url`     | `str`   | —       | Base URL of the board REST API (e.g. `http://localhost:8000`). |
| `board_api_token`   | `str`   | —       | Bearer token sent as `Authorization: Bearer <token>`.          |
| `board_repo_id`     | `str`   | —       | The `repo_id` / board ID to scope operations to.               |
| `enable_write_ops`  | `bool`  | `True`  | When `False`, all write ops return an Error.                   |

## Usage

```python
from robotsix_board_agent import BoardAgentSettings

settings = BoardAgentSettings(
    board_api_url="http://localhost:8000",
    board_api_token="sk-...",
    board_repo_id="my-repo",
    enable_write_ops=True,
)
```

All values are passed explicitly by the caller — this is **not** a
pydantic `BaseSettings` model that reads from environment variables.
