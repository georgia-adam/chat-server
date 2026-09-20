"""Chat logic with no I/O. Sessions receive events through a Sink."""

from __future__ import annotations

import logging
import re
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Protocol

from .events import Error, Event, History, Info, Message, Presence, UserJoined, UserLeft

log = logging.getLogger(__name__)

LOBBY = "lobby"
NAME_RULE = "1-32 characters: letters, digits, _ or -"
_NAME_RE = re.compile(r"[A-Za-z0-9_-]{1,32}")
MAX_MESSAGE_LEN = 1000


def valid_name(name: str) -> bool:
    """True if `name` is acceptable as a username or room name."""
    return _NAME_RE.fullmatch(name) is not None


class Sink(Protocol):
    def send(self, event: Event) -> None: ...


class UsernameTaken(Exception):
    pass


class InvalidUsername(Exception):
    pass


@dataclass
class Session:
    username: str
    room: str
    sink: Sink

    def send(self, event: Event) -> None:
        self.sink.send(event)


@dataclass
class Room:
    name: str
    history_len: int
    members: dict[str, Session] = field(default_factory=dict)
    history: deque[Message] = field(init=False)

    def __post_init__(self) -> None:
        self.history = deque(maxlen=self.history_len)

    def broadcast(self, event: Event, *, exclude: str | None = None) -> None:
        for username, session in list(self.members.items()):
            if username != exclude:
                session.send(event)


class Hub:
    def __init__(
        self,
        history_len: int = 10,
        clock: Callable[[], float] = time.time,
        max_message_len: int = MAX_MESSAGE_LEN,
    ) -> None:
        self.history_len = history_len
        self.clock = clock
        self.max_message_len = max_message_len
        self.rooms: dict[str, Room] = {}
        self.sessions: dict[str, Session] = {}
        self.last_room: dict[str, str] = {}

    # -- rooms -------------------------------------------------------------

    def _room(self, name: str) -> Room:
        room = self.rooms.get(name)
        if room is None:
            room = self.rooms[name] = Room(name, self.history_len)
        return room

    def _enter(self, session: Session, name: str) -> None:
        room = self._room(name)
        room.members[session.username] = session
        session.room = name
        if room.history:
            session.send(History(name, tuple(room.history)))
        self.who(session)
        room.broadcast(UserJoined(name, session.username), exclude=session.username)

    def _leave(self, session: Session) -> None:
        """Remove the session from its room, notify the others, and drop the room if nothing is left."""
        room = self.rooms[session.room]
        room.members.pop(session.username, None)
        room.broadcast(UserLeft(room.name, session.username))
        if not room.members and not room.history:
            del self.rooms[room.name]

    # -- public API --------------------------------------------------------

    def login(self, username: str, sink: Sink) -> Session:
        if not valid_name(username):
            raise InvalidUsername(username)
        if username in self.sessions:
            raise UsernameTaken(username)
        room = self.last_room.pop(username, LOBBY)
        session = Session(username, room, sink)
        self.sessions[username] = session
        if room != LOBBY:
            session.send(Info(f"Welcome back — rejoined {room}."))
        self._enter(session, room)
        log.info("login user=%s room=%s", username, room)
        return session

    def logout(self, session: Session, *, remember: bool = True) -> None:
        if self.sessions.pop(session.username, None) is None:
            return
        room = session.room
        self._leave(session)
        if remember and room != LOBBY:
            self.last_room[session.username] = room
        log.info("logout user=%s room=%s remembered=%s", session.username, room, remember and room != LOBBY)

    def join(self, session: Session, room: str | None) -> None:
        if not room:
            session.send(Error("Usage: /join <room>", "usage"))
            return
        if not valid_name(room):
            session.send(Error(f"Invalid room name ({NAME_RULE}).", "invalid_room"))
            return
        if session.room == room:
            return
        old = session.room
        self._leave(session)
        self._enter(session, room)
        log.info("join user=%s room=%s from=%s", session.username, room, old)

    def who(self, session: Session) -> None:
        room = self.rooms[session.room]
        others = tuple(u for u in room.members if u != session.username)
        session.send(Presence(room.name, others))

    def say(self, session: Session, text: str) -> None:
        if not text:
            return
        if len(text) > self.max_message_len:
            session.send(Error(f"Message too long (max {self.max_message_len} characters).", "message_too_long"))
            return
        room = self.rooms[session.room]
        message = Message(room.name, session.username, text, self.clock())
        room.history.append(message)
        room.broadcast(message, exclude=session.username)

    # -- persistence -------------------------------------------------------

    def snapshot(self) -> dict:
        return {
            "last_room": dict(self.last_room),
            "room_history": {
                name: [m.to_dict() for m in r.history] for name, r in self.rooms.items() if r.history
            },
        }

    def restore(self, data: dict) -> None:
        self.last_room.update(data.get("last_room", {}))
        for name, entries in data.get("room_history", {}).items():
            self._room(name).history.extend(Message.from_dict(name, e) for e in entries)
