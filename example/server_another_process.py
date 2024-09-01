import sys
import time
from pathlib import Path

__project_root__ = Path(__file__).resolve().parents[1]
sys.path.append(str(__project_root__ / "src"))

import logging
import multiprocessing

from xpc import Manager


def setup_logging() -> None:
    try:
        import colorlog

        handler = colorlog.StreamHandler()
        # Add date to the log format
        handler.setFormatter(colorlog.ColoredFormatter("%(asctime)s %(log_color)s%(levelname)s%(reset)s %(message)s"))
    except ImportError:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))

    logging.basicConfig(level=logging.INFO, handlers=[handler])


def process_target(man: Manager) -> None:
    setup_logging()
    try:
        while True:
            # logging.info("calling 'my_callback' from another process")
            value, found = man.call("my_callback")
            if found:
                logging.info(f"another callback returned: {value}")
            else:
                logging.warning("another callback not found")
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    setup_logging()
    manager = Manager(
        address=("localhost", 50000),
        authkey=b"password",
    )
    manager.start()

    p = multiprocessing.Process(target=process_target, args=(manager,))
    p.start()

    try:
        while True:
            # logging.info("calling 'my_callback' from main process")
            value, found = manager.call("my_callback")
            if found:
                logging.info(f"main callback returned: {value}")
            else:
                logging.warning("main callback not found")
            time.sleep(0.2)

    except KeyboardInterrupt:
        pass
