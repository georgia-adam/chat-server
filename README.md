# chat-server

A small asyncio TCP chat server. Multi-room, plaintext, with in-memory state and periodic JSON persistence.

## Connect

1. Run `nc <server-address> <port>` (ask me for the address and port).
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
CHAT_PASSWORD=hunter2 python3 chat_server.py
```

Then connect from another terminal:

```sh
nc 127.0.0.1 8888
```
