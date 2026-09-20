import asyncio
import json

from chat_server.events import Error, History, Info, Message, Presence, UserJoined, UserLeft
from chat_server.jsonl import parse, render


def test_render_is_one_json_object_per_line():
    def line(event):
        raw = render(event)
        assert raw.endswith(b"\n") and raw.count(b"\n") == 1
        return json.loads(raw)

    assert line(Message("lobby", "alice", "hi", 1.0)) == {
        "type": "message", "room": "lobby", "sender": "alice", "text": "hi", "ts": 1.0
    }
    assert line(History("gaming", (Message("gaming", "a", "1", 1.0),))) == {
        "type": "history", "room": "gaming", "messages": [{"sender": "a", "text": "1", "ts": 1.0}]
    }
    assert line(Presence("lobby", ("a", "b"))) == {"type": "presence", "room": "lobby", "others": ["a", "b"]}
    assert line(UserJoined("lobby", "alice")) == {"type": "joined", "room": "lobby", "username": "alice"}
    assert line(UserLeft("lobby", "alice")) == {"type": "left", "room": "lobby", "username": "alice"}
    assert line(Info("Welcome back — rejoined gaming.")) == {"type": "info", "text": "Welcome back — rejoined gaming."}
    assert line(Error("Usage: /join <room>", "usage")) == {"type": "error", "code": "usage", "text": "Usage: /join <room>"}


def test_parse_rejects_anything_but_typed_objects():
    assert parse(b'{"type": "who"}\n') == {"type": "who"}
    for bad in [b"", b"not json\n", b"[1]\n", b'{"no": "type"}\n', b'{"type": 3}\n']:
        assert parse(bad) is None


async def test_wrong_password_closes(server):
    c = await server.raw_json()
    await c.send({"type": "login", "password": "nope", "username": "alice"})
    assert await c.recv() == {"type": "error", "code": "auth", "text": "Wrong password."}
    await c.eof()


async def test_wrong_password_is_delayed(server):
    server.jsonl.fail_delay = 0.3
    c = await server.raw_json()
    started = asyncio.get_running_loop().time()
    await c.send({"type": "login", "password": "nope", "username": "alice"})
    assert (await c.recv())["code"] == "auth"
    assert asyncio.get_running_loop().time() - started >= 0.3


async def test_first_line_must_be_a_login(server):
    c = await server.raw_json()
    await c.send({"type": "who"})
    assert (await c.recv())["code"] == "bad_request"
    await c.eof()


async def test_invalid_and_duplicate_usernames_rejected(server):
    c = await server.connect_json("bad name")
    assert (await c.recv())["code"] == "invalid_username"
    await c.eof()

    a = await server.connect_json("alice")
    assert (await a.recv())["type"] == "welcome"
    dup = await server.connect_json("alice")
    assert (await dup.recv())["code"] == "username_taken"
    await dup.eof()


async def test_login_welcome_then_presence(server):
    a = await server.connect_json("alice")
    assert await a.recv() == {"type": "welcome", "username": "alice", "room": "lobby"}
    assert await a.recv() == {"type": "presence", "room": "lobby", "others": []}


async def test_message_reaches_others_but_is_not_echoed(server):
    a = await server.connect_json("alice")
    await a.recv(); await a.recv()
    b = await server.connect_json("bob")
    await b.recv()
    assert await b.recv() == {"type": "presence", "room": "lobby", "others": ["alice"]}
    assert await a.recv() == {"type": "joined", "room": "lobby", "username": "bob"}

    await a.send({"type": "say", "text": "hi bob"})
    got = await b.recv()
    assert (got["type"], got["sender"], got["text"]) == ("message", "alice", "hi bob")
    assert isinstance(got["ts"], float)
    await a.send({"type": "who"})
    assert await a.recv() == {"type": "presence", "room": "lobby", "others": ["bob"]}  # nothing echoed before


async def test_join_history_and_command_errors(server):
    a = await server.connect_json("alice")
    await a.recv(); await a.recv()
    await a.send({"type": "join", "room": "gaming"})
    assert await a.recv() == {"type": "presence", "room": "gaming", "others": []}
    await a.send({"type": "say", "text": "first"})

    b = await server.connect_json("bob")
    await b.recv(); await b.recv()
    await b.send({"type": "join", "room": "gaming"})
    history = await b.recv()
    assert history["type"] == "history" and [m["text"] for m in history["messages"]] == ["first"]
    assert await b.recv() == {"type": "presence", "room": "gaming", "others": ["alice"]}
    assert await a.recv() == {"type": "joined", "room": "gaming", "username": "bob"}

    await a.send({"type": "join"})
    assert (await a.recv())["code"] == "usage"
    await a.send({"type": "join", "room": "bad room"})
    assert (await a.recv())["code"] == "invalid_room"
    await a.send({"type": "frobnicate"})
    assert (await a.recv())["code"] == "unknown_command"
    await a.send({"type": "say", "text": 5})
    assert (await a.recv())["code"] == "bad_request"
    a.writer.write(b"this is not json\n")
    assert (await a.recv())["code"] == "bad_request"


async def test_quit_forgets_room_but_disconnect_remembers_it(server):
    a = await server.connect_json("alice")
    await a.recv(); await a.recv()
    await a.send({"type": "join", "room": "gaming"})
    await a.recv()
    await a.send({"type": "quit"})
    await a.eof()
    await server.wait_logged_out("alice")

    a = await server.connect_json("alice")
    assert (await a.recv())["room"] == "lobby"
    await a.recv()
    await a.send({"type": "join", "room": "gaming"})
    await a.recv()
    await a.close()
    await server.wait_logged_out("alice")

    a = await server.connect_json("alice")
    assert (await a.recv())["room"] == "gaming"
    assert (await a.recv())["type"] == "info"


async def test_json_and_nc_clients_share_a_room(server):
    nc = await server.connect("alice")
    assert await nc.line() == "You are the only user in lobby.\n"
    js = await server.connect_json("bob")
    await js.recv()
    assert await js.recv() == {"type": "presence", "room": "lobby", "others": ["alice"]}
    assert await nc.line() == "bob has joined lobby.\n"

    await nc.send("hello from nc")
    got = await js.recv()
    assert (got["sender"], got["text"]) == ("alice", "hello from nc")
    await js.send({"type": "say", "text": "hello from json"})
    assert await nc.line() == "bob: hello from json\n"


async def test_shutdown_disconnects_clients(server):
    a = await server.connect_json("alice")
    await a.recv(); await a.recv()
    await asyncio.wait_for(server.jsonl.close(), 2)
    await a.eof()
    assert server.hub.sessions == {}
