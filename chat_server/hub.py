"""Chat logic with no I/O. Sessions receive events through a Sink."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Protocol

from .events import Error, Event, History, Info, Message, Presence, UserLeft

LOBBY = "lobby"


class Sink(Protocol):
    def send(self, event: Event) -> None: ...


class UsernameTaken(Exception):
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
    history: deque[str] = field(init=False)

    def __post_init__(self) -> None:
        self.history = deque(maxlen=self.history_len)

    def broadcast(self, event: Event, *, exclude: str | None = None) -> None:
        for username, session in list(self.members.items()):
            if username != exclude:
                session.send(event)


class Hub:
    def __init__(self, history_len: int = 10) -> None:
        self.history_len = history_len
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

    def _leave(self, session: Session) -> None:
        """Remove the session from its room. Rooms persist (they hold history)."""
        room = self.rooms[session.room]
        room.members.pop(session.username, None)
        room.broadcast(UserLeft(room.name, session.username))

    # -- public API --------------------------------------------------------

    def login(self, username: str, sink: Sink) -> Session:
        if username in self.sessions:
            raise UsernameTaken(username)
        room = self.last_room.pop(username, LOBBY)
        session = Session(username, room, sink)
        self.sessions[username] = session
        if room != LOBBY:
            session.send(Info(f"Welcome back — rejoined {room}."))
        self._enter(session, room)
        return session

    def logout(self, session: Session, *, remember: bool = True) -> None:
        if self.sessions.pop(session.username, None) is None:
            return
        room = session.room
        self._leave(session)
        if remember and room != LOBBY:
            self.last_room[session.username] = room

    def join(self, session: Session, room: str | None) -> None:
        if not room:
            session.send(Error("Usage: /join <room>"))
            return
        if session.room == room:
            return
        old = self.rooms[session.room]
        old.members.pop(session.username, None)
        self._enter(session, room)
        old.broadcast(UserLeft(old.name, session.username))

    def who(self, session: Session) -> None:
        room = self.rooms[session.room]
        others = tuple(u for u in room.members if u != session.username)
        session.send(Presence(room.name, others))

    def say(self, session: Session, text: str) -> None:
        room = self.rooms[session.room]
        room.history.append(f"{session.username}: {text}\n")
        room.broadcast(Message(room.name, session.username, text), exclude=session.username)

    # -- persistence -------------------------------------------------------

    def snapshot(self) -> dict:
        return {
            "last_room": dict(self.last_room),
            "room_history": {
                name: list(r.history) for name, r in self.rooms.items() if r.history
            },
        }

    def restore(self, data: dict) -> None:
        self.last_room.update(data.get("last_room", {}))
        for name, lines in data.get("room_history", {}).items():
            self._room(name).history.extend(lines)
