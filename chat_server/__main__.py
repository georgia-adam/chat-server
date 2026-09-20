import argparse
import asyncio
import os

from .hub import Hub
from .state import load_state, save_state
from .tcp import serve


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="chat_server", description="asyncio TCP chat server")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8888)
    p.add_argument("--state-file", default="chat_state.json")
    p.add_argument("--save-interval", type=float, default=10, help="seconds between saves")
    return p.parse_args(argv)


async def periodic_save(hub: Hub, path: str, interval: float) -> None:
    while True:
        await asyncio.sleep(interval)
        try:
            save_state(path, hub.snapshot())
        except Exception as e:
            print(f"save_state failed: {e}")


async def run(args: argparse.Namespace, password: str) -> None:
    hub = Hub()
    hub.restore(load_state(args.state_file))
    saver = asyncio.create_task(periodic_save(hub, args.state_file, args.save_interval))
    server = await serve(hub, password, args.host, args.port)
    try:
        await server.serve_forever()
    finally:
        saver.cancel()
        await server.close()  # logs everyone out so their rooms are remembered
        save_state(args.state_file, hub.snapshot())  # final save on shutdown


def main() -> None:
    password = os.environ.get("CHAT_PASSWORD")
    if not password:
        raise SystemExit("CHAT_PASSWORD environment variable is required")
    try:
        asyncio.run(run(parse_args(), password))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
