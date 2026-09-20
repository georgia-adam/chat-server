"""JSON-lines TCP transport: one JSON object per line, sharing the Hub with the nc transport.

Server -> client objects always carry a "type":
  welcome  {username, room}            once, after a successful login
  message  {room, sender, text, ts}
  history  {room, messages: [{sender, text, ts}, ...]}
  presence {room, others: [username, ...]}
  joined   {room, username}
  left     {room, username}
  info     {text}
  error    {code, text}                a login error is followed by the connection closing

Client -> server objects:
  login    {password, username}        must be the first line sent
  say      {text}
  join     {room}
  who      {}
  quit     {}                          like /quit: the room is not remembered
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from .events import Error, Event, History, Info, Message, Presence, UserJoined, UserLeft
from .hub import NAME_RULE, Hub, InvalidUsername, Session, UsernameTaken
from .transport import CLOSE, FAIL_DELAY, QueueSink, password_matches

log = logging.getLogger(__name__)


# -- wire format -------------------------------------------------------------


def to_wire(event: Event) -> dict[str, Any]:
    match event:
        case Message(room, sender, text, ts):
            return {"type": "message", "room": room, "sender": sender, "text": text, "ts": ts}
        case History(room, messages):
            return {"type": "history", "room": room, "messages": [m.to_dict() for m in messages]}
        case Presence(room, others):
            return {"type": "presence", "room": room, "others": list(others)}
        case UserJoined(room, username):
            return {"type": "joined", "room": room, "username": username}
        case UserLeft(room, username):
            return {"type": "left", "room": room, "username": username}
        case Info(text):
            return {"type": "info", "text": text}
        case Error(text, code):
            return {"type": "error", "code": code, "text": text}
        case _:
            raise TypeError(f"unknown event {event!r}")


def render(event: Event) -> bytes:
    return (json.dumps(to_wire(event), ensure_ascii=False) + "\n").encode()


def parse(line: bytes) -> dict[str, Any] | None:
    """Decode one client line. Returns None unless it is a JSON object with a string "type"."""
    try:
        obj = json.loads(line)
    except ValueError:
        return None
    if not isinstance(obj, dict) or not isinstance(obj.get("type"), str):
        return None
    return obj


def handle_command(hub: Hub, session: Session, obj: dict[str, Any] | None) -> bool:
    """Apply one client object to the hub. Returns True if the client asked to quit."""
    if obj is None:
        session.send(Error("Expected a JSON object with a string \"type\".", "bad_request"))
        return False
    match obj["type"]:
        case "say":
            text = obj.get("text")
            if isinstance(text, str):
                hub.say(session, text.strip())
            else:
                session.send(Error("say needs a string \"text\".", "bad_request"))
        case "join":
            room = obj.get("room")
            hub.join(session, room if isinstance(room, str) else None)
        case "who":
            hub.who(session)
        case "quit":
            return True
        case other:
            session.send(Error(f"Unknown command: {other}", "unknown_command"))
    return False


# -- connection handling -----------------------------------------------------


async def pump(sink: QueueSink, writer: asyncio.StreamWriter) -> None:
    """Write queued events to one client. Ends on close sentinel, overflow, or socket error."""
    try:
        while True:
            event = await sink.queue.get()
            if event is CLOSE:
                return
            writer.write(render(event))
            await writer.drain()
            if sink.overflowed:
                return
    except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
        pass
    finally:
        writer.close()


async def _reject(writer: asyncio.StreamWriter, error: Error) -> None:
    writer.write(render(error))
    await writer.drain()


async def handle_client(
    hub: Hub,
    password: str,
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    *,
    fail_delay: float = FAIL_DELAY,
) -> None:
    addr = writer.get_extra_info("peername")
    peer = f"{addr[0]}:{addr[1]}" if addr else "?"
    session: Session | None = None
    sink = QueueSink()
    pump_task: asyncio.Task | None = None
    quitting = False
    log.info("jsonl connected peer=%s", peer)
    try:
        first = parse(await reader.readline())
        if first is None or first["type"] != "login":
            await _reject(writer, Error("First line must be a login object.", "bad_request"))
            return
        if not password_matches(str(first.get("password", "")), password):
            log.warning("jsonl auth failed peer=%s", peer)
            await asyncio.sleep(fail_delay)
            await _reject(writer, Error("Wrong password.", "auth"))
            return
        username = str(first.get("username", "")).strip()
        try:
            session = hub.login(username, sink)
        except InvalidUsername:
            log.warning("jsonl invalid username peer=%s username=%r", peer, username)
            await _reject(writer, Error(f"Invalid username ({NAME_RULE}).", "invalid_username"))
            return
        except UsernameTaken:
            log.warning("jsonl username taken peer=%s username=%s", peer, username)
            await _reject(writer, Error("Username already taken.", "username_taken"))
            return
        writer.write((json.dumps({"type": "welcome", "username": username, "room": session.room}) + "\n").encode())
        await writer.drain()
        pump_task = asyncio.create_task(pump(sink, writer))

        while True:
            line = await reader.readline()
            if not line:
                return
            if handle_command(hub, session, parse(line)):
                quitting = True
                return
    except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
        pass
    finally:
        if session is not None:
            hub.logout(session, remember=not quitting)
        if pump_task is not None:
            sink.close()
            try:
                await asyncio.wait_for(pump_task, timeout=5)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pump_task.cancel()
        writer.close()
        try:
            await writer.wait_closed()
        except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
            pass
        log.info("jsonl disconnected peer=%s user=%s", peer, session.username if session else None)


class JsonlServer:
    """A listening server plus the client connections it has accepted."""

    def __init__(self, hub: Hub, password: str, *, fail_delay: float = FAIL_DELAY) -> None:
        self.hub = hub
        self.password = password
        self.fail_delay = fail_delay
        self.server: asyncio.Server | None = None
        self.writers: set[asyncio.StreamWriter] = set()

    async def start(self, host: str, port: int) -> None:
        self.server = await asyncio.start_server(self._handle, host, port)
        log.info("jsonl listening host=%s port=%s", host, self.port)

    @property
    def port(self) -> int:
        return self.server.sockets[0].getsockname()[1]

    async def close(self) -> None:
        self.server.close()
        for writer in list(self.writers):
            writer.close()
        await self.server.wait_closed()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.writers.add(writer)
        try:
            await handle_client(self.hub, self.password, reader, writer, fail_delay=self.fail_delay)
        finally:
            self.writers.discard(writer)


async def serve(hub: Hub, password: str, host: str, port: int, *, fail_delay: float = FAIL_DELAY) -> JsonlServer:
    srv = JsonlServer(hub, password, fail_delay=fail_delay)
    await srv.start(host, port)
    return srv
