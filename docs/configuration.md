# Configuration

`robotsix-board-agent` is configured through environment variables.

## Environment variables

| Variable | Required | Default | Used by | Purpose |
|---|---|---|---|---|
| `BOARD_MANAGER_CLI_TOKEN` | Yes | — | `manager_cli` | Broker bearer token for the CLI |
| `BOARD_MANAGER_CLI_ID` | No | `board-manager-cli` | `manager_cli` | Agent ID for the CLI |
| `BOARD_MANAGER_TARGET` | No | `board-manager-robotsix-mill` | `manager_cli` | Manager agent ID to target |
| `ROBOTSIX_BROKER_HOST` | No | `ai-broker.robotsix.net` | `manager_cli` | Broker hostname |
| `ROBOTSIX_BROKER_PORT` | No | `443` | `manager_cli` | Broker port |
| `ROBOTSIX_BROKER_SCHEME` | No | `https` | `manager_cli` | Broker scheme (`http` or `https`) |
| `LOG_LEVEL` | No | `INFO` (agent), `WARNING` (manager_cli) | `agent`, `manager_cli` | Logging verbosity: `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL` |

### Per-component details

**`agent.py`** reads `LOG_LEVEL` at module load and passes it to
`robotsix_llmio.logging.setup_logging`. Default: `INFO`.

**`manager_cli.py`** reads all seven variables in `main()`:

- `LOG_LEVEL` controls stdlib `logging.basicConfig`. Default: `WARNING`.
- `BOARD_MANAGER_CLI_TOKEN` is required; the CLI exits with code 2 if unset.
- `BOARD_MANAGER_CLI_ID`, `ROBOTSIX_BROKER_HOST`, `ROBOTSIX_BROKER_PORT`,
  `ROBOTSIX_BROKER_SCHEME` are passed to `BrokeredAgent`.
- `BOARD_MANAGER_TARGET` selects which agent to message through the broker.
