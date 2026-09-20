import pytest

from chat_server.events import Error, History, Info, Message, Presence, UserLeft
from chat_server.hub import Hub, UsernameTaken


class ListSink(list):
    def send(self, event):
        self.append(event)


def login(hub, name):
    sink = ListSink()
    session = hub.login(name, sink)
    sink.clear()
    return session, sink


def test_first_login_lands_in_lobby_and_reports_presence():
    hub = Hub()
    sink = ListSink()
    session = hub.login("alice", sink)
    assert session.room == "lobby"
    assert sink == [Presence("lobby", ())]


def test_duplicate_username_rejected():
    hub = Hub()
    hub.login("alice", ListSink())
    with pytest.raises(UsernameTaken):
        hub.login("alice", ListSink())


def test_say_reaches_others_only_and_records_history():
    hub = Hub()
    a, a_sink = login(hub, "alice")
    b, b_sink = login(hub, "bob")
    a_sink.clear()
    hub.say(a, "hi")
    assert a_sink == []
    assert b_sink == [Message("lobby", "alice", "hi")]
    assert list(hub.rooms["lobby"].history) == ["alice: hi\n"]


def test_history_is_capped():
    hub = Hub(history_len=2)
    a, _ = login(hub, "alice")
    for i in range(3):
        hub.say(a, str(i))
    assert list(hub.rooms["lobby"].history) == ["alice: 1\n", "alice: 2\n"]


def test_join_moves_user_and_notifies_old_room():
    hub = Hub()
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
    hub = Hub()
    a, _ = login(hub, "alice")
    hub.join(a, "gaming")
    hub.say(a, "first")
    b, b_sink = login(hub, "bob")
    b_sink.clear()
    hub.join(b, "gaming")
    assert b_sink == [History("gaming", ("alice: first\n",)), Presence("gaming", ("alice",))]


def test_join_same_room_is_noop_and_missing_arg_is_error():
    hub = Hub()
    a, a_sink = login(hub, "alice")
    hub.join(a, "lobby")
    assert a_sink == []
    hub.join(a, None)
    assert a_sink == [Error("Usage: /join <room>")]


def test_room_history_survives_room_emptying():
    hub = Hub()
    a, _ = login(hub, "alice")
    hub.join(a, "gaming")
    hub.say(a, "hello")
    hub.logout(a)
    assert hub.rooms["gaming"].members == {}
    assert list(hub.rooms["gaming"].history) == ["alice: hello\n"]


def test_logout_remembers_room_and_rejoins():
    hub = Hub()
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
    hub = Hub()
    a, _ = login(hub, "alice")
    hub.join(a, "gaming")
    hub.logout(a, remember=False)
    assert hub.last_room == {}

    b, _ = login(hub, "bob")
    hub.logout(b)
    assert hub.last_room == {}


def test_logout_twice_is_harmless():
    hub = Hub()
    a, _ = login(hub, "alice")
    hub.logout(a)
    hub.logout(a)
    assert hub.sessions == {}


def test_snapshot_matches_existing_file_shape_and_round_trips():
    data = {
        "last_room": {"Miles": "gaming", "Jennifer": "gaming"},
        "room_history": {
            "lobby": ["Miles: Hello jennifer\n"],
            "gaming": ["Jennifer: Hello\n", "Miles: Heyy in gaming now\n"],
        },
    }
    hub = Hub()
    hub.restore(data)
    assert hub.snapshot() == data

    # rooms that exist but have no history are left out of the snapshot
    a, _ = login(hub, "alice")
    hub.join(a, "empty")
    assert "empty" not in hub.snapshot()["room_history"]
