import asyncio

import pytest

from chat_server.hub import Hub
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


class Server:
    def __init__(self, hub: Hub, port: int):
        self.hub = hub
        self.port = port
        self.clients: list[Client] = []

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
    s = Server(hub, srv.port)
    s.srv = srv
    yield s
    for c in s.clients:
        await c.close()
    await asyncio.wait_for(srv.close(), TIMEOUT)
