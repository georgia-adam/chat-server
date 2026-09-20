import pytest

from chat_server.events import Error, History, Info, Message, Presence, UserLeft
from chat_server.hub import Hub, UsernameTaken

T = 1_700_000_000.0


def make_hub(**kwargs) -> Hub:
    return Hub(clock=lambda: T, **kwargs)


class ListSink(list):
    def send(self, event):
        self.append(event)


def login(hub, name):
    sink = ListSink()
    session = hub.login(name, sink)
    sink.clear()
    return session, sink


def test_first_login_lands_in_lobby_and_reports_presence():
    hub = make_hub()
    sink = ListSink()
    session = hub.login("alice", sink)
    assert session.room == "lobby"
    assert sink == [Presence("lobby", ())]


def test_duplicate_username_rejected():
    hub = make_hub()
    hub.login("alice", ListSink())
    with pytest.raises(UsernameTaken):
        hub.login("alice", ListSink())


def test_say_reaches_others_only_and_records_history():
    hub = make_hub()
    a, a_sink = login(hub, "alice")
    b, b_sink = login(hub, "bob")
    a_sink.clear()
    hub.say(a, "hi")
    assert a_sink == []
    assert b_sink == [Message("lobby", "alice", "hi", T)]
    assert list(hub.rooms["lobby"].history) == [Message("lobby", "alice", "hi", T)]


def test_history_is_capped():
    hub = make_hub(history_len=2)
    a, _ = login(hub, "alice")
    for i in range(3):
        hub.say(a, str(i))
    assert [m.text for m in hub.rooms["lobby"].history] == ["1", "2"]


def test_join_moves_user_and_notifies_old_room():
    hub = make_hub()
    a, a_sink = login(hub, "alice")
    b, b_sink = login(hub, "bob")
    hub.say(b, "old news")
    a_sink.clear()
    b_sink.clear()

    hub.join(a, "gaming")

    assert a.room == "gaming"
    assert hub.rooms["gaming"].members == {"alice": a}
    assert "alice" not in hub.rooms["lobby"].members
    assert a_sink == [Presence("gaming", ())]
    assert b_sink == [UserLeft("lobby", "alice")]


def test_join_shows_history_then_presence():
    hub = make_hub()
    a, _ = login(hub, "alice")
    hub.join(a, "gaming")
    hub.say(a, "first")
    b, b_sink = login(hub, "bob")
    b_sink.clear()
    hub.join(b, "gaming")
    assert b_sink == [
        History("gaming", (Message("gaming", "alice", "first", T),)),
        Presence("gaming", ("alice",)),
    ]


def test_join_same_room_is_noop_and_missing_arg_is_error():
    hub = make_hub()
    a, a_sink = login(hub, "alice")
    hub.join(a, "lobby")
    assert a_sink == []
    hub.join(a, None)
    assert a_sink == [Error("Usage: /join <room>")]


def test_room_history_survives_room_emptying():
    hub = make_hub()
    a, _ = login(hub, "alice")
    hub.join(a, "gaming")
    hub.say(a, "hello")
    hub.logout(a)
    assert hub.rooms["gaming"].members == {}
    assert [m.text for m in hub.rooms["gaming"].history] == ["hello"]


def test_logout_remembers_room_and_rejoins():
    hub = make_hub()
    a, _ = login(hub, "alice")
    hub.join(a, "gaming")
    b, b_sink = login(hub, "bob")
    hub.join(b, "gaming")
    b_sink.clear()

    hub.logout(a)

    assert b_sink == [UserLeft("gaming", "alice")]
    assert hub.last_room == {"alice": "gaming"}

    sink = ListSink()
    session = hub.login("alice", sink)
    assert session.room == "gaming"
    assert sink == [Info("Welcome back — rejoined gaming."), Presence("gaming", ("bob",))]
    assert hub.last_room == {}


def test_logout_with_quit_forgets_room_and_lobby_is_never_remembered():
    hub = make_hub()
    a, _ = login(hub, "alice")
    hub.join(a, "gaming")
    hub.logout(a, remember=False)
    assert hub.last_room == {}

    b, _ = login(hub, "bob")
    hub.logout(b)
    assert hub.last_room == {}


def test_logout_twice_is_harmless():
    hub = make_hub()
    a, _ = login(hub, "alice")
    hub.logout(a)
    hub.logout(a)
    assert hub.sessions == {}


def test_snapshot_round_trips_and_skips_rooms_without_history():
    data = {
        "last_room": {"Miles": "gaming"},
        "room_history": {
            "gaming": [
                {"sender": "Jennifer", "text": "Hello", "ts": T},
                {"sender": "Miles", "text": "Heyy in gaming now", "ts": T + 1},
            ],
        },
    }
    hub = make_hub()
    hub.restore(data)
    assert hub.snapshot() == data

    a, _ = login(hub, "alice")
    hub.join(a, "empty")
    assert "empty" not in hub.snapshot()["room_history"]

