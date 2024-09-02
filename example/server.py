import sys
import time
from pathlib import Path

__project_root__ = Path(__file__).resolve().parents[1]
sys.path.append(str(__project_root__ / "src"))

from xpc import Manager

if __name__ == "__main__":
    import argparse

    from _logging import setup_logging

    logger = setup_logging()

    parser = argparse.ArgumentParser()
    parser.add_argument("--address", default="localhost")
    parser.add_argument("--port", type=int, default=50000)
    parser.add_argument("--authkey", default="password")
    parser.add_argument("--frequency", type=int, default=5)
    args = parser.parse_args()

    manager = Manager(
        address=(args.address, args.port),
        authkey=args.authkey,
    )
    manager.start()

    logger.info(f"Server started at {args.address}:{args.port}")
    logger.info(f"Authkey: {args.authkey}")
    logger.info(f"Frequency: {args.frequency}")

    try:
        while True:
            _name = "my_callback"
            _args = (1, 2, 3)
            _kwargs = {"hello": "world"}
            value, found = manager.call(_name, *_args, **_kwargs)
            if found:
                logger.info(f"callback returned: {value}")
            else:
                logger.warning("callback not found")
            time.sleep(1 / args.frequency)
    except KeyboardInterrupt:
        pass
