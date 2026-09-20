"""Line-oriented TCP transport (nc-compatible) on top of the Hub."""

from __future__ import annotations

import asyncio
import hmac
import logging

from .events import Error, Event, History, Info, Message, Presence, UserJoined, UserLeft
from .hub import NAME_RULE, Hub, InvalidUsername, Session, UsernameTaken

log = logging.getLogger(__name__)

QUEUE_SIZE = 256
FAIL_DELAY = 2.0  # seconds to stall a client after a wrong password
_CLOSE = None  # sentinel telling the pump to stop after flushing


def render(event: Event) -> bytes:
    """Turn an event into the exact text the original server produced."""
    match event:
        case Message(_, sender, text):
            out = f"{sender}: {text}\n"
        case History(room, messages):
            out = (
                f"--- last {len(messages)} messages in {room} ---\n"
                + "".join(f"{m.sender}: {m.text}\n" for m in messages)
                + "--- end history ---\n"
            )
        case Presence(room, others):
            out = f"Users in {room}: {', '.join(others)}\n" if others else f"You are the only user in {room}.\n"
        case UserJoined(room, username):
            out = f"{username} has joined {room}.\n"
        case UserLeft(room, username):
            out = f"{username} has left {room}.\n"
        case Info(text) | Error(text):
            out = f"{text}\n"
        case _:
            raise TypeError(f"unknown event {event!r}")
    return out.encode()


class QueueSink:
    """Non-blocking sink: events go on a bounded queue drained by a pump task."""

    def __init__(self, maxsize: int = QUEUE_SIZE) -> None:
        self.queue: asyncio.Queue = asyncio.Queue(maxsize)
        self.overflowed = False

    def send(self, event: Event) -> None:
        try:
            self.queue.put_nowait(event)
        except asyncio.QueueFull:
            self.overflowed = True

    def close(self) -> None:
        try:
            self.queue.put_nowait(_CLOSE)
        except asyncio.QueueFull:
            self.overflowed = True


async def pump(sink: QueueSink, writer: asyncio.StreamWriter) -> None:
    """Write queued events to one client. Ends on close sentinel, overflow, or socket error."""
    try:
        while True:
            event = await sink.queue.get()
            if event is _CLOSE:
                return
            writer.write(render(event))
            await writer.drain()
            if sink.overflowed:
                return
    except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
        pass
    finally:
        writer.close()


COMMANDS = ("/join", "/who", "/quit")


def password_matches(supplied: str, expected: str) -> bool:
    """Constant-time comparison so response timing does not leak how much of the password matched."""
    return hmac.compare_digest(supplied.encode(), expected.encode())


def _peer(writer: asyncio.StreamWriter) -> str:
    addr = writer.get_extra_info("peername")
    return f"{addr[0]}:{addr[1]}" if addr else "?"


async def handle_client(
    hub: Hub,
    password: str,
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    *,
    fail_delay: float = FAIL_DELAY,
) -> None:
    peer = _peer(writer)
    session: Session | None = None
    sink = QueueSink()
    pump_task: asyncio.Task | None = None
    quitting = False
    log.info("connected peer=%s", peer)
    try:
        writer.write(b"Password: ")
        await writer.drain()
        line = await reader.readline()
        if not password_matches(line.decode(errors="replace").strip(), password):
            log.warning("auth failed peer=%s", peer)
            await asyncio.sleep(fail_delay)
            writer.write(b"Wrong password.\n")
            await writer.drain()
            return

        writer.write(b"Username: ")
        await writer.drain()
        username = (await reader.readline()).decode(errors="replace").strip()
        try:
            session = hub.login(username, sink)
        except InvalidUsername:
            log.warning("invalid username peer=%s username=%r", peer, username)
            writer.write(f"Invalid username ({NAME_RULE}). Closing connection.".encode())
            await writer.drain()
            return
        except UsernameTaken:
            log.warning("username taken peer=%s username=%s", peer, username)
            writer.write(b"Username already taken. Closing connection.")
            await writer.drain()
            return
        pump_task = asyncio.create_task(pump(sink, writer))

        while True:
            data = await reader.readline()
            if not data:
                return
            if data.startswith(b"/"):
                parts = data.decode(errors="replace").strip().split(maxsplit=1)
                cmd = parts[0]
                arg = parts[1] if len(parts) > 1 else None
                if cmd == "/join":
                    hub.join(session, arg)
                elif cmd == "/who":
                    hub.who(session)
                elif cmd == "/quit":
                    quitting = True
                    return
                else:
                    sink.send(Error(f"Unknown command: {cmd}"))
                continue
            hub.say(session, data.decode(errors="replace").strip())
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
        log.info("disconnected peer=%s user=%s", peer, session.username if session else None)


class ChatServer:
    """A listening server plus the client connections it has accepted."""

    def __init__(self, hub: Hub, password: str, *, fail_delay: float = FAIL_DELAY) -> None:
        self.hub = hub
        self.password = password
        self.fail_delay = fail_delay
        self.server: asyncio.Server | None = None
        self.writers: set[asyncio.StreamWriter] = set()

    async def start(self, host: str, port: int) -> None:
        self.server = await asyncio.start_server(self._handle, host, port)
        log.info("listening host=%s port=%s", host, self.port)

    @property
    def port(self) -> int:
        return self.server.sockets[0].getsockname()[1]

    async def serve_forever(self) -> None:
        """Run until cancelled. Deliberately not asyncio.Server.serve_forever(),
        which on cancellation awaits wait_closed() before we get a chance to
        disconnect clients; call close() afterwards."""
        await asyncio.get_running_loop().create_future()

    async def close(self) -> None:
        """Stop listening and disconnect every client.

        Closing clients explicitly matters: since Python 3.12, wait_closed()
        blocks until all connections are gone, so Ctrl-C would otherwise hang
        while anyone is still connected.
        """
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


async def serve(
    hub: Hub, password: str, host: str, port: int, *, fail_delay: float = FAIL_DELAY
) -> ChatServer:
    chat = ChatServer(hub, password, fail_delay=fail_delay)
    await chat.start(host, port)
    return chat
