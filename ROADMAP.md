# Roadmap

Direction: this server is a stepping stone to a real app with a structured protocol and a proper client. The core (`chat_server/hub.py`) is transport-agnostic and tested, so each step below is a self-contained addition.

Steps are roughly in recommended order. Status: `[ ]` todo, `[x]` done.

## 1. Refactor and tests `[x]`

Split the script into a package: hub (chat logic, no I/O), events, TCP transport, state persistence, entry point. 25 tests over the hub, persistence and real sockets. Wire behaviour for `nc` unchanged. Fixed the Ctrl-C hang on Python 3.12+ when clients are connected.

## 2. Structured message records `[x]`

`Message` (room, sender, text, unix `ts`) is now the unit stored in the room deque and on disk, as a list of `{"sender", "text", "ts"}` objects per room. Wire text for `nc` is unchanged.

## 3. Hardening `[x]`

- Entering a room now notifies its members (`UserJoined`, rendered as `bob has joined gaming.`), mirroring the leave notice.
- Usernames and room names must match `[A-Za-z0-9_-]{1,32}`. A bad username closes the connection; a bad `/join` argument is an error and the user stays put. Messages over 1000 characters are rejected; empty lines are dropped.
- Password compare uses `hmac.compare_digest`, and a wrong password stalls the connection for 2 seconds before the rejection to slow guessing.
- `logging` replaces `print`: connections, logins, joins, auth failures and save errors, with `--log-level`.
- Rooms with no members and no history are deleted when the last member leaves.

## 4. JSON-lines transport `[x]`

`chat_server/jsonl.py` listens on a second port (`--jsonl-port`, default 8889) and shares the hub with the `nc` transport, so users on either can talk in the same rooms. One JSON object per line in both directions; the module docstring is the protocol reference. Every server object has a `type`, errors carry a stable `code`, and the first client line must be `{"type": "login", "password", "username"}`. Tests in `tests/test_jsonl.py` mirror the TCP ones, plus one that mixes an `nc` client and a JSON client in a room.

## 5. WebSocket transport and browser client `[ ]`

Same objects as step 4 but reachable from a browser, which is easier for friends than installing anything.

- Needs one server-side dependency (`websockets`).
- A single HTML page as the client.
- The wire objects and command parser in `jsonl.py` are reusable as is; only the framing (WebSocket frames instead of lines) and the socket API differ.

## 6. Accounts and TLS `[ ]`

Per-user passwords instead of the shared one, and TLS via an `ssl` context on the listener. Matters once strangers can reach the server; less urgent while it is friends only.

## 7. Deployment `[ ]`

Dockerfile or systemd unit, with a persistent volume or directory for the state file, so the server runs somewhere reachable.

## Notes

- History is capped at 10 messages per room, kept in memory and on disk whether or not the room has members. A room is deleted only when it is empty and has no history.
- On-disk history entries carry a unix timestamp.
- State is written every `--save-interval` seconds (default 10) and once on Ctrl-C. A crash can lose up to one interval of messages.
- Run tests with `.venv/bin/pytest`. Run the server with `CHAT_PASSWORD=... python3 -m chat_server`.
