import sys
import time
from pathlib import Path

__project_root__ = Path(__file__).resolve().parents[1]
sys.path.append(str(__project_root__ / "src"))

from xpc import Manager

if __name__ == "__main__":
    import logging

    try:
        import colorlog

        handler = colorlog.StreamHandler()
        # Add date to the log format
        handler.setFormatter(colorlog.ColoredFormatter("%(asctime)s %(log_color)s%(levelname)s%(reset)s %(message)s"))
    except ImportError:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))

    logging.basicConfig(level=logging.INFO, handlers=[handler])

    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--address", default="localhost")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--authkey", default="password")
    parser.add_argument("--frequency", type=int, default=5)
    args = parser.parse_args()

    manager = Manager(
        address=(args.address, args.port),
        authkey=args.authkey,
    )
    manager.start()

    print(f"Server started at {args.address}:{args.port}")
    print(f"Authkey: {args.authkey}")
    print(f"Frequency: {args.frequency}")

    try:
        while True:
            _name = "my_callback"
            _args = (1, 2, 3)
            _kwargs = {"hello": "world"}
            logging.info(f"calling '{_name}' with args: {_args} and kwargs: {_kwargs}")
            value, found = manager.call(_name, *_args, **_kwargs)
            if found:
                logging.info(f"callback returned: {value}")
            else:
                logging.warning("callback not found")
            time.sleep(1 / args.frequency)
    except KeyboardInterrupt:
        pass
