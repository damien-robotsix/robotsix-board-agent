# Client API

The `BoardClient` is a typed HTTP client for the mill board REST API.
Every public method maps 1:1 to a board endpoint.

## Initialisation

```python
from robotsix_board_agent import BoardClient, BoardAgentSettings

settings = BoardAgentSettings(
    board_api_url="http://localhost:8000",
    board_api_token="sk-...",
    board_repo_id="my-repo",
)

client = BoardClient(settings)
```

For testing, inject a mock transport via the `transport=` keyword argument:

```python
import httpx

client = BoardClient(settings, transport=httpx.MockTransport(handler))
```

## Read operations

| Method          | Args                          | Endpoint                          | Returns              |
|-----------------|-------------------------------|-----------------------------------|----------------------|
| `list_tickets`  | `state?`, `repo_id?`          | `GET /tickets`                    | `list[dict]`         |
| `get_ticket`    | `ticket_id: str`              | `GET /tickets/{id}`               | `dict`               |
| `board_cards`   | `repo_id?`                    | `GET /board/cards`                | `list[dict]`         |
| `history`       | `ticket_id: str`              | `GET /tickets/{id}/history`       | `list[dict]`         |
| `merge_status`  | `ticket_id: str`              | `GET /tickets/{id}/merge-status`  | `dict`               |
| `description`   | `ticket_id: str`              | `GET /tickets/{id}/description`   | `dict`               |

All read methods are async and return parsed JSON from the board API.

## Write operations

| Method            | Args                                          | Endpoint                            | Returns     |
|-------------------|-----------------------------------------------|-------------------------------------|-------------|
| `create_ticket`   | `title`, `description`, `source?`, `kind?`, `repo_id?`, `**kwargs` | `POST /tickets`                    | `dict`      |
| `add_comment`     | `ticket_id`, `body`, `author?`                | `POST /tickets/{id}/comments`       | `dict`      |
| `transition`      | `ticket_id`, `state`, `note?`                 | `POST /tickets/{id}/transition`     | `dict`      |
| `approve`         | `ticket_id`                                   | `POST /tickets/{id}/approve`        | `dict`      |
| `mark_done`       | `ticket_id`, `note?`                          | `POST /tickets/{id}/mark-done`      | `dict`      |
| `merge_now`       | `ticket_id`                                   | `POST /tickets/{id}/merge-now`      | `dict`      |
| `resume_blocked`  | `ticket_id`                                   | `POST /tickets/{id}/resume-blocked` | `dict`      |
| `migrate`         | `ticket_id`, `target_repo_id`, `note?`        | `POST /tickets/{id}/migrate`        | `dict`      |
| `set_priority`    | `ticket_id`, `priority: bool`                 | `POST /tickets/{id}/priority`       | `dict`      |

## Lifecycle

Call `await client.close()` to release the underlying `httpx.AsyncClient`
and free connections.

## Error handling

All methods raise `BoardAPIError` when the board API returns a non-2xx
status. The exception carries `status_code` (int) and `detail` (str)
attributes.
