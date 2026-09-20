"""Events emitted by the Hub. Transports render these into wire format."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Message:
    """A chat message from another user in the room."""

    room: str
    sender: str
    text: str


@dataclass(frozen=True)
class History:
    """Recent messages in a room, sent on entering it."""

    room: str
    lines: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Presence:
    """Who else is in the room (excluding the recipient)."""

    room: str
    others: tuple[str, ...] = field(default_factory=tuple)


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


Event = Message | History | Presence | UserLeft | Info | Error
