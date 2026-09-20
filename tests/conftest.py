import asyncio
import json

import pytest

from chat_server.hub import Hub
from chat_server.jsonl import serve as serve_jsonl
from chat_server.tcp import serve

PASSWORD = "pw"
TIMEOUT = 2


class Client:
    def __init__(self, reader, writer):
        self.reader = reader
        self.writer = writer

    async def expect(self, text: str) -> None:
        """Assert the next bytes on the wire are exactly `text`."""
        got = await asyncio.wait_for(self.reader.readexactly(len(text)), TIMEOUT)
        assert got.decode() == text

    async def line(self) -> str:
        return (await asyncio.wait_for(self.reader.readline(), TIMEOUT)).decode()

    async def eof(self) -> None:
        assert await asyncio.wait_for(self.reader.read(), TIMEOUT) == b""

    async def send(self, text: str) -> None:
        self.writer.write((text + "\n").encode())
        await self.writer.drain()

    async def close(self) -> None:
        self.writer.close()
        try:
            await self.writer.wait_closed()
        except (ConnectionResetError, BrokenPipeError):
            pass


class JsonClient(Client):
    """A JSON-lines client: send objects, receive objects."""

    async def send(self, obj: dict) -> None:
        self.writer.write((json.dumps(obj) + "\n").encode())
        await self.writer.drain()

    async def recv(self) -> dict:
        line = await asyncio.wait_for(self.reader.readline(), TIMEOUT)
        assert line, "connection closed"
        return json.loads(line)


class Server:
    def __init__(self, hub: Hub, port: int, jsonl_port: int):
        self.hub = hub
        self.port = port
        self.jsonl_port = jsonl_port
        self.clients: list[Client] = []

    async def raw_json(self) -> JsonClient:
        reader, writer = await asyncio.open_connection("127.0.0.1", self.jsonl_port)
        client = JsonClient(reader, writer)
        self.clients.append(client)
        return client

    async def connect_json(self, username: str, password: str = PASSWORD) -> JsonClient:
        """Open a JSON-lines connection and log in, leaving the welcome line unread."""
        client = await self.raw_json()
        await client.send({"type": "login", "password": password, "username": username})
        return client

    async def raw(self) -> Client:
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        client = Client(reader, writer)
        self.clients.append(client)
        return client

    async def connect(self, username: str, password: str = PASSWORD) -> Client:
        """Open a connection and complete the handshake, leaving the presence line unread."""
        client = await self.raw()
        await client.expect("Password: ")
        await client.send(password)
        await client.expect("Username: ")
        await client.send(username)
        return client

    async def wait_logged_out(self, username: str) -> None:
        for _ in range(100):
            if username not in self.hub.sessions:
                return
            await asyncio.sleep(0.01)
        raise AssertionError(f"{username} still logged in")


@pytest.fixture
async def server():
    hub = Hub()
    srv = await serve(hub, PASSWORD, "127.0.0.1", 0, fail_delay=0)
    jsonl = await serve_jsonl(hub, PASSWORD, "127.0.0.1", 0, fail_delay=0)
    s = Server(hub, srv.port, jsonl.port)
    s.srv = srv
    s.jsonl = jsonl
    yield s
    for c in s.clients:
        await c.close()
    await asyncio.wait_for(srv.close(), TIMEOUT)
    await asyncio.wait_for(jsonl.close(), TIMEOUT)
