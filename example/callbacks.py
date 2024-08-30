import sys
import time
from pathlib import Path

__project_root__ = Path(__file__).resolve().parents[1]
sys.path.append(str(__project_root__ / "src"))

from typing import Any

from xpc import Manager

if __name__ == "__main__":
    manager = Manager(
        address=("localhost", 50000),
        authkey=b"password",
    )
    manager.connect()

    def my_callback(*args: Any, **kwargs: Any) -> int:
        # def my_callback() -> int:
        print("my_callh args:", args, "kwargs:", kwargs)
        time.sleep(1)
        # raise ValueError("This is a test error")
        return 101

    manager.register("my_callback", my_callback)

    # Spin
    try:
        while True:
            print(".", end="", flush=True)
            time.sleep(1)
    except KeyboardInterrupt:
        pass
