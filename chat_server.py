import asyncio
import json
import os
from collections import deque

STATE_FILE = "chat_state.json"
SAVE_INTERVAL = 10  # seconds
HISTORY_LEN = 10

CHAT_PASSWORD = os.environ.get("CHAT_PASSWORD")
if not CHAT_PASSWORD:
    raise SystemExit("CHAT_PASSWORD environment variable is required")

rooms: dict[str, dict[str, asyncio.StreamWriter]] = {}
user_room: dict[str, str] = {}
last_room: dict[str, str] = {}
room_history: dict[str, deque[str]] = {}

def get_history(room: str) -> deque[str]:
    return room_history.setdefault(room, deque(maxlen=HISTORY_LEN))

def load_state():
    try:
        with open(STATE_FILE) as f:
            data = json.load(f)
    except FileNotFoundError:
        return
    last_room.update(data.get("last_room", {}))
    for room, msgs in data.get("room_history", {}).items():
        room_history[room] = deque(msgs, maxlen=HISTORY_LEN)

def save_state():
    data = {
        "last_room": last_room,
        "room_history": {r: list(h) for r, h in room_history.items()},
    }
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, STATE_FILE)  # atomic on POSIX

async def periodic_save():
    while True:
        await asyncio.sleep(SAVE_INTERVAL)
        try:
            save_state()
        except Exception as e:
            print(f"save_state failed: {e}")

async def send_history(writer, room):
    history = room_history.get(room)
    if not history:
        return
    writer.write(f"--- last {len(history)} messages in {room} ---\n".encode())
    for line in history:
        writer.write(line.encode())
    writer.write(b"--- end history ---\n")
    await writer.drain()

async def cmd_join(username, kwd, writer):
    if not kwd:
        writer.write(b"Usage: /join <room>\n")
        await writer.drain()
        return
    if user_room[username] == kwd:
        return
    old_room = user_room.pop(username)
    rooms[old_room].pop(username)
    if not rooms[old_room]:
        rooms.pop(old_room)
    user_room[username] = kwd
    rooms.setdefault(kwd, {})[username] = writer
    await send_history(writer, kwd)
    await cmd_who(username, None, writer)
    await send_leave_msg(username, old_room)

async def send_leave_msg(username, room):
    if not rooms.get(room, None):
        return
    msg = f"{username} has left {room}.\n".encode()
    tasks = [send(w, msg) for w in list(rooms[room].values())]
    await asyncio.gather(*tasks)

async def cmd_who(username, kwd, writer):
    room = user_room[username]
    in_room = ", ".join([u for u in rooms[room].keys() if u != username])
    msg = f"You are the only user in {room}.\n" if not in_room else f"Users in {room}: {in_room}\n"
    writer.write(msg.encode())
    await writer.drain()

async def cmd_quit(username, kwd, writer):
    writer.close()

COMMANDS = {"/join": cmd_join, "/who": cmd_who, "/quit": cmd_quit}

async def send(w, message):
    try:
        w.write(message)
        await w.drain()
    except (ConnectionResetError, BrokenPipeError):
        pass

async def handle_client(reader, writer):
    username = None
    quitting = False
    try:
        writer.write(b"Password: ")
        await writer.drain()
        password_bytes = await reader.readline()
        if password_bytes.decode().strip() != CHAT_PASSWORD:
            writer.write(b"Wrong password.\n")
            await writer.drain()
            return

        writer.write(b"Username: ")
        username_bytes = await reader.readline()
        username = username_bytes.decode().strip()
        if username in user_room:
            writer.write(b"Username already taken. Closing connection.")
            await writer.drain()
            return

        room = last_room.pop(username, "lobby")
        rooms.setdefault(room, {})[username] = writer
        user_room[username] = room
        if room != "lobby":
            writer.write(f"Welcome back — rejoined {room}.\n".encode())
        await send_history(writer, room)
        await cmd_who(username, None, writer)

        while True:
            data = await reader.readline()
            if not data:
                return
            if data.startswith(b"/"):
                parts = data.decode().strip().split(maxsplit=1)
                cmd = parts[0]
                kwd = parts[1] if len(parts) > 1 else None
                handler = COMMANDS.get(cmd)
                if handler:
                    if cmd == "/quit":
                        quitting = True
                    await handler(username, kwd, writer)
                else:
                    writer.write(f"Unknown command: {cmd}\n".encode())
                    await writer.drain()
                continue

            message_str = f"{username}: {data.decode().strip()}\n"
            room = user_room[username]
            get_history(room).append(message_str)
            message = message_str.encode()
            tasks = [send(w, message) for c, w in list(rooms[room].items()) if c != username]
            await asyncio.gather(*tasks)

    finally:
        room = user_room.pop(username, None)
        if room:
            rooms[room].pop(username, None)
            await send_leave_msg(username, room)
            if not rooms[room]:
                rooms.pop(room, None)
            if not quitting and room != "lobby":
                last_room[username] = room
        writer.close()
        await writer.wait_closed()

async def main():
    load_state()
    saver = asyncio.create_task(periodic_save())
    server = await asyncio.start_server(handle_client, '0.0.0.0', 8888)
    try:
        async with server:
            await server.serve_forever()
    finally:
        saver.cancel()
        save_state()  # final save on shutdown

asyncio.run(main())
