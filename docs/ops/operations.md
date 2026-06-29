# Operations Reference

The board agent supports 16 structured operations — 7 read, 9 write.
Each maps 1:1 to an existing board REST endpoint.

## Request format

```json
{"op": "<operation-name>", "args": {...}}
```

## Read operations

| Op              | Args                                 | Endpoint                          | Returns          |
|-----------------|--------------------------------------|-----------------------------------|------------------|
| `list_tickets`  | `state?`, `repo_id?`                 | `GET /tickets`                    | `{"tickets": […]}` |
| `get_ticket`    | `ticket_id: str`                     | `GET /tickets/{id}`               | ticket dict      |
| `board_cards`   | `repo_id?`                           | `GET /board/cards`                | `{"cards": […]}`  |
| `history`       | `ticket_id: str`                     | `GET /tickets/{id}/history`       | `{"history": […]}` |
| `merge_status`  | `ticket_id: str`                     | `GET /tickets/{id}/merge-status`  | merge-status dict |
| `description`   | `ticket_id: str`                     | `GET /tickets/{id}/description`   | description dict |
| `get_multiple_ticket_descriptions` | `ticket_ids: list[str]` | `GET /tickets/{id}/description` (×N) | `{"descriptions": […]}` |

## Write operations

All write operations require `enable_write_ops=True` (the default).
If writes are disabled, the agent returns an Error with code
`WRITE_OPS_DISABLED`.

| Op               | Args                                          | Endpoint                           | Returns       |
|------------------|-----------------------------------------------|------------------------------------|---------------|
| `create_ticket`  | `title`, `description`, `source?`, `kind?`, `repo_id?` | `POST /tickets`                   | new ticket    |
| `comment`        | `ticket_id`, `body`, `author?`                | `POST /tickets/{id}/comments`      | new comment   |
| `transition`     | `ticket_id`, `state`, `note?`                 | `POST /tickets/{id}/transition`    | updated ticket|
| `approve`        | `ticket_id`                                   | `POST /tickets/{id}/approve`       | result dict   |
| `mark_done`      | `ticket_id`, `note?`                          | `POST /tickets/{id}/mark-done`     | result dict   |
| `merge_now`      | `ticket_id`                                   | `POST /tickets/{id}/merge-now`     | result dict   |
| `resume_blocked` | `ticket_id`                                   | `POST /tickets/{id}/resume-blocked`| result dict   |
| `migrate`        | `ticket_id`, `target_repo_id`, `note?`        | `POST /tickets/{id}/migrate`       | result dict   |
| `set_priority`   | `ticket_id`, `priority: bool`                 | `POST /tickets/{id}/priority`      | result dict   |

## Error responses

| Code                 | Meaning                                      |
|----------------------|----------------------------------------------|
| `UNKNOWN_OP`         | The operation name is not recognised.         |
| `WRITE_OPS_DISABLED` | `enable_write_ops` is `False`.                |
| `BOARD_API_ERROR`    | The upstream board API returned a non-2xx.    |
| `BAD_REQUEST`        | The request body could not be parsed.         |
