# def my_callback():
#     print("my_callback called with args:", args, "kwargs:", kwargs)
#     return 100001

from typing import Any

from temp1 import MyManager

if __name__ == "__main__":
    manager = MyManager(
        address=("localhost", 50000),
        authkey=b"password",
    )
    manager.connect()

    def my_callback(*args: Any, **kwargs: Any) -> int:
        print("my_callback called with args:", args, "kwargs:", kwargs)
        return 100001

    manager.register_callback("my_callback", my_callback)

    import time

    try:
        while True:
            print(".", end="", flush=True)
            time.sleep(1)
    except KeyboardInterrupt:
        pass
