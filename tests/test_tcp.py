import asyncio

import pytest

from chat_server.events import Error, History, Info, Message, Presence, UserJoined, UserLeft
from chat_server.tcp import QueueSink, render


def test_render_matches_original_wire_text():
    assert render(Message("lobby", "alice", "hi")) == b"alice: hi\n"
    assert render(History("gaming", (Message("gaming", "a", "1", 1.0), Message("gaming", "b", "2")))) == (
        b"--- last 2 messages in gaming ---\na: 1\nb: 2\n--- end history ---\n"
    )
    assert render(Presence("lobby", ())) == b"You are the only user in lobby.\n"
    assert render(Presence("lobby", ("a", "b"))) == b"Users in lobby: a, b\n"
    assert render(UserJoined("lobby", "alice")) == b"alice has joined lobby.\n"
    assert render(UserLeft("lobby", "alice")) == b"alice has left lobby.\n"
    assert render(Info("Welcome back — rejoined gaming.")) == "Welcome back — rejoined gaming.\n".encode()
    assert render(Error("Unknown command: /x")) == b"Unknown command: /x\n"


async def test_queue_sink_flags_overflow():
    sink = QueueSink(maxsize=1)
    sink.send(Info("a"))
    assert not sink.overflowed
    sink.send(Info("b"))
    assert sink.overflowed


async def test_wrong_password_closes(server):
    c = await server.raw()
    await c.expect("Password: ")
    await c.send("nope")
    assert await c.line() == "Wrong password.\n"
    await c.eof()


async def test_wrong_password_is_delayed(server):
    server.srv.fail_delay = 0.3
    c = await server.raw()
    await c.expect("Password: ")
    started = asyncio.get_running_loop().time()
    await c.send("nope")
    assert await c.line() == "Wrong password.\n"
    assert asyncio.get_running_loop().time() - started >= 0.3


async def test_invalid_username_closes(server):
    c = await server.connect("bad name")
    assert (await c.line()).startswith("Invalid username (")
    await c.eof()
    assert server.hub.sessions == {}


async def test_duplicate_username_rejected(server):
    a = await server.connect("alice")
    assert await a.line() == "You are the only user in lobby.\n"
    dup = await server.connect("alice")
    await dup.expect("Username already taken. Closing connection.")
    await dup.eof()


async def test_message_reaches_others_but_is_not_echoed(server):
    a = await server.connect("alice")
    assert await a.line() == "You are the only user in lobby.\n"
    b = await server.connect("bob")
    assert await b.line() == "Users in lobby: alice\n"
    assert await a.line() == "bob has joined lobby.\n"

    await a.send("hi bob")
    assert await b.line() == "alice: hi bob\n"
    await a.send("/who")
    assert await a.line() == "Users in lobby: bob\n"  # nothing was echoed before this


async def test_join_who_and_command_errors(server):
    a = await server.connect("alice")
    await a.line()
    b = await server.connect("bob")
    await b.line()
    await a.line()  # bob has joined lobby.

    await a.send("/join gaming")
    assert await a.line() == "You are the only user in gaming.\n"
    assert await b.line() == "alice has left lobby.\n"
    await a.send("/who")
    assert await a.line() == "You are the only user in gaming.\n"
    await a.send("/join")
    assert await a.line() == "Usage: /join <room>\n"
    await a.send("/frobnicate now")
    assert await a.line() == "Unknown command: /frobnicate\n"
    await a.send("/join gaming")  # same room: silent
    await a.send("/who")
    assert await a.line() == "You are the only user in gaming.\n"


async def test_joiner_sees_history(server):
    a = await server.connect("alice")
    await a.line()
    await a.send("/join gaming")
    await a.line()
    await a.send("first")

    b = await server.connect("bob")
    await b.line()
    await b.send("/join gaming")
    assert await b.line() == "--- last 1 messages in gaming ---\n"
    assert await b.line() == "alice: first\n"
    assert await b.line() == "--- end history ---\n"
    assert await b.line() == "Users in gaming: alice\n"
    assert await a.line() == "bob has joined gaming.\n"


async def test_quit_forgets_room_but_disconnect_remembers_it(server):
    a = await server.connect("alice")
    await a.line()
    await a.send("/join gaming")
    await a.line()
    await a.send("/quit")
    await a.eof()
    await server.wait_logged_out("alice")

    a = await server.connect("alice")
    assert await a.line() == "You are the only user in lobby.\n"
    await a.send("/join gaming")
    await a.line()
    await a.close()
    await server.wait_logged_out("alice")

    a = await server.connect("alice")
    assert await a.line() == "Welcome back — rejoined gaming.\n"
    assert await a.line() == "You are the only user in gaming.\n"


async def test_leave_notification_on_disconnect(server):
    a = await server.connect("alice")
    await a.line()
    b = await server.connect("bob")
    await b.line()
    await a.close()
    assert await b.line() == "alice has left lobby.\n"


async def test_shutdown_disconnects_clients_and_completes(server):
    a = await server.connect("alice")
    await a.line()
    await asyncio.wait_for(server.srv.close(), 2)
    await a.eof()
    assert server.hub.sessions == {}


async def test_cancelling_serve_forever_then_close_finishes_with_clients_connected(server):
    a = await server.connect("alice")
    await a.line()
    task = asyncio.create_task(server.srv.serve_forever())
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 2)
    await asyncio.wait_for(server.srv.close(), 2)
    await a.eof()
