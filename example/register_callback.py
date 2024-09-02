import sys
import time
from pathlib import Path

__project_root__ = Path(__file__).resolve().parents[1]
sys.path.append(str(__project_root__ / "src"))

from typing import Any

from _logging import setup_logging

from xpc import Manager

if __name__ == "__main__":
    logger = setup_logging()

    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--address", default="localhost")
    parser.add_argument("--port", type=int, default=50000)
    parser.add_argument("--authkey", default="password")
    parser.add_argument("--frequency", type=int, default=5)
    parser.add_argument("--sleep", type=float, default=0.1)
    args = parser.parse_args()

    manager = Manager(
        address=(args.address, args.port),
        authkey=args.authkey,
    )
    manager.connect()

    logger.info(f"Connected to the server at {args.address}:{args.port}")
    logger.info(f"Authkey: {args.authkey}")
    logger.info(f"Frequency: {args.frequency}")

    # Set up `my_callback`. We can use globals and we add a lock to make the counter work properly.
    from threading import Lock

    i = 0
    lock = Lock()
    SLEEP = args.sleep

    def my_callback(*args: Any, **kwargs: Any) -> int:
        time.sleep(SLEEP)
        global i  # noqa: PLW0603
        with lock:
            i += 1
        return i

    manager.register("my_callback", my_callback)

    # Spin
    try:
        while True:
            # Attempt to call the callback locally
            value, found = manager.call("my_callback", 1, 2, 3, hello="world")
            if found:
                logger.info(f"callback returned: {value}")
            else:
                logger.warning("callback not found")
            time.sleep(1 / args.frequency)
    except KeyboardInterrupt:
        pass
