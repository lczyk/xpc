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

    manager = Manager(
        address=("localhost", 50000),
        authkey=b"password",
    )
    manager.start()

    try:
        while True:
            name = "my_callback"
            args = (1, 2, 3)
            kwargs = {"hello": "world"}
            logging.info(f"calling '{name}' with args: {args} and kwargs: {kwargs}")
            value, found = manager.call(name, *args, **kwargs)
            if found:
                logging.info(f"callback returned: {value}")
            else:
                logging.warning("callback not found")
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
