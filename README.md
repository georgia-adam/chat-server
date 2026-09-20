# chat-server

A small asyncio TCP chat server. Multi-room, plaintext, with in-memory state and periodic JSON persistence.

## Connect

1. Run `nc <server-address> <port>` (*ask me for the address and port*).
2. Enter the password when prompted (*ask me if you know me*).
3. Pick a username.
4. Start chatting.

**Commands:**

- `/join <room>` — switch rooms (default is `lobby`)
- `/who` — list users in your room
- `/quit` — disconnect

Windows users don't have `nc` by default — install [ncat](https://nmap.org/ncat/) (`choco install nmap`) or run the same `nc` command from WSL.

## Run locally

Requires Python 3.10+. No external dependencies.

```sh
CHAT_PASSWORD=hunter2 python3 -m chat_server
```

Options: `--host` (default `0.0.0.0`), `--port` (default `8888`), `--state-file` (default `chat_state.json`), `--save-interval` seconds (default `10`).

Then connect from another terminal:

```sh
nc 127.0.0.1 8888
```

## Development

The package splits into a transport-agnostic core and a TCP transport:

- `chat_server/hub.py` — rooms, sessions, history, join/leave logic. No I/O; emits events to a per-session sink.
- `chat_server/events.py` — the event types the hub emits.
- `chat_server/tcp.py` — the `nc`-compatible line protocol: handshake, command parsing, rendering events to text, per-client send queue.
- `chat_server/state.py` — atomic JSON persistence.

Run the tests:

```sh
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
```
