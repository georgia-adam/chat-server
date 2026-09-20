"""Events emitted by the Hub. Transports render these into wire format."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Message:
    """A chat message. Also the unit stored in room history and on disk."""

    room: str
    sender: str
    text: str
    ts: float | None = None  # unix time

    def to_dict(self) -> dict:
        return {"sender": self.sender, "text": self.text, "ts": self.ts}

    @classmethod
    def from_dict(cls, room: str, data: dict) -> Message:
        return cls(room, data["sender"], data["text"], data.get("ts"))


@dataclass(frozen=True)
class History:
    """Recent messages in a room, sent on entering it."""

    room: str
    messages: tuple[Message, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Presence:
    """Who else is in the room (excluding the recipient)."""

    room: str
    others: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class UserJoined:
    room: str
    username: str


@dataclass(frozen=True)
class UserLeft:
    room: str
    username: str


@dataclass(frozen=True)
class Info:
    text: str


@dataclass(frozen=True)
class Error:
    text: str


Event = Message | History | Presence | UserJoined | UserLeft | Info | Error
