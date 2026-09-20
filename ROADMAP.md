# Roadmap

Direction: this server is a stepping stone to a real app with a structured protocol and a proper client. The core (`chat_server/hub.py`) is transport-agnostic and tested, so each step below is a self-contained addition.

Steps are roughly in recommended order. Status: `[ ]` todo, `[x]` done.

## 1. Refactor and tests `[x]`

Split the script into a package: hub (chat logic, no I/O), events, TCP transport, state persistence, entry point. 25 tests over the hub, persistence and real sockets. Wire behaviour for `nc` unchanged. Fixed the Ctrl-C hang on Python 3.12+ when clients are connected.

## 2. Structured message records `[x]`

`Message` (room, sender, text, unix `ts`) is now the unit stored in the room deque and on disk, as a list of `{"sender", "text", "ts"}` objects per room. Wire text for `nc` is unchanged.

## 3. Hardening `[ ]`

Small, independent items. Each is a few lines plus a test now that the hub is isolated.

- Join notification to the room being entered (there is none today, only a leave notice).
- Reject empty or malformed usernames and room names; cap message length.
- Constant-time password compare (`hmac.compare_digest`) and a delay after failed attempts.
- Structured logging instead of `print`.
- Optional: prune rooms that are empty and have no history.

## 4. JSON-lines transport `[ ]`

One JSON object per line, sharing the hub with the TCP transport. Cheapest proof that the sink design works, and the natural backend for a terminal client (for example with `textual`).

- New module `chat_server/jsonl.py` with its own `render` and a parser for incoming commands.
- Either a second port or a protocol switch on the first line.
- Tests mirror `tests/test_tcp.py`.

## 5. WebSocket transport and browser client `[ ]`

Same idea as step 4 but reachable from a browser, which is easier for friends than installing anything.

- Needs one server-side dependency (`websockets`).
- A single HTML page as the client.
- Once step 4 exists this is mostly a second `render` and a different socket API.

## 6. Accounts and TLS `[ ]`

Per-user passwords instead of the shared one, and TLS via an `ssl` context on the listener. Matters once strangers can reach the server; less urgent while it is friends only.

## 7. Deployment `[ ]`

Dockerfile or systemd unit, with a persistent volume or directory for the state file, so the server runs somewhere reachable.

## Notes

- History is capped at 10 messages per room, kept in memory and on disk whether or not the room has members. Rooms are never deleted.
- On-disk history entries carry a unix timestamp.
- State is written every `--save-interval` seconds (default 10) and once on Ctrl-C. A crash can lose up to one interval of messages.
- Run tests with `.venv/bin/pytest`. Run the server with `CHAT_PASSWORD=... python3 -m chat_server`.
