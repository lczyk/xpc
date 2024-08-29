import time
from typing import Any

from server import MyManager

if __name__ == "__main__":
    manager = MyManager(
        address=("localhost", 50000),
        authkey=b"password",
    )
    manager.connect()

    def my_callback(*args: Any, **kwargs: Any) -> int:
        # def my_callback() -> int:
        print("my_callback called with args:", args, "kwargs:", kwargs)
        # time.sleep(0.1)
        # raise ValueError("This is a test error")
        return 100001

    manager.register("my_callback", my_callback)

    # Spin
    try:
        while True:
            print(".", end="", flush=True)
            time.sleep(1)
    except KeyboardInterrupt:
        pass
