import argparse
import asyncio
import logging
import os

from .hub import Hub
from .state import load_state, save_state
from .tcp import serve

log = logging.getLogger(__name__)


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="chat_server", description="asyncio TCP chat server")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8888)
    p.add_argument("--state-file", default="chat_state.json")
    p.add_argument("--save-interval", type=float, default=10, help="seconds between saves")
    p.add_argument("--log-level", default="INFO", help="DEBUG, INFO, WARNING or ERROR")
    return p.parse_args(argv)


async def periodic_save(hub: Hub, path: str, interval: float) -> None:
    while True:
        await asyncio.sleep(interval)
        try:
            save_state(path, hub.snapshot())
        except Exception:
            log.exception("save failed path=%s", path)


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
        log.info("stopped")


def main() -> None:
    password = os.environ.get("CHAT_PASSWORD")
    if not password:
        raise SystemExit("CHAT_PASSWORD environment variable is required")
    args = parse_args()
    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    try:
        asyncio.run(run(args, password))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
