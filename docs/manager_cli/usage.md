# Manager CLI

`robotsix-board-manager` is the command-line tool for talking to a
`BoardManager` over the broker in natural language.

## Invocation

```bash
robotsix-board-manager "<natural-language instruction>"
```

All positional arguments are joined into a single message string.

### Examples

```bash
robotsix-board-manager "close all stale draft tickets"
robotsix-board-manager "what is the status of the auth epic?"
robotsix-board-manager "list all tickets in review"
robotsix-board-manager "create a ticket: fix login timeout bug in auth service"
```

## Environment variables

| Variable                  | Default                          | Required | Purpose                              |
|---------------------------|----------------------------------|----------|--------------------------------------|
| `BOARD_MANAGER_CLI_TOKEN` | —                                | **Yes**  | Bearer token for this CLI on the broker |
| `ROBOTSIX_BROKER_HOST`    | `ai-broker.robotsix.net`         | No       | Broker hostname                      |
| `ROBOTSIX_BROKER_PORT`    | `443`                            | No       | Broker port                          |
| `ROBOTSIX_BROKER_SCHEME`  | `https`                          | No       | `http` or `https`                    |
| `BOARD_MANAGER_CLI_ID`    | `board-manager-cli`              | No       | This CLI's agent id on the broker    |
| `BOARD_MANAGER_TARGET`    | `board-manager-robotsix-mill`    | No       | Target manager agent id to talk to   |

## Exit codes

| Code | Meaning                                                         |
|------|-----------------------------------------------------------------|
| `0`  | Success — the manager returned a `Response` with a `"reply"`    |
| `1`  | The manager returned an `Error` (printed to stdout)             |
| `2`  | Missing arguments or `BOARD_MANAGER_CLI_TOKEN` not set          |

## How it works

1. The CLI joins all positional arguments into a message string.
2. It reads `BOARD_MANAGER_CLI_TOKEN` — exits with code 2 if unset.
3. It creates an `Agent` in pull/mailbox mode with a 180-second broker timeout.
4. It sends a request to the target manager agent with `{"message": message}`.
5. The reply is printed to stdout — the `"reply"` field if present, otherwise
   the raw body.

## Programmatic use

The `main()` function accepts an optional `argv` list and returns an exit code:

```python
from robotsix_board_agent.manager_cli import main

exit_code = main(["list in-progress tickets"])
```
