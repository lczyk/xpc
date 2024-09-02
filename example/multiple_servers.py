import sys
from pathlib import Path

__project_root__ = Path(__file__).resolve().parents[1]
sys.path.append(str(__project_root__ / "src"))

import time
from threading import Event, Thread, current_thread

from xpc import Manager


def target(stop: Event, address: str, port: int, authkey: str, frequency: int) -> None:
    man = Manager(
        address=(address, port),
        authkey=authkey,
    )
    man.start_or_connect()
    print(f"Connected to server on {current_thread().name}")

    # Spin
    try:
        while not stop.is_set():
            value, found = man.call("my_callback", 1, 2, 3, hello="world")
            if found:
                print(f"callback returned: {value} on {current_thread().name}")
            stop.wait(1 / frequency)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--address", default="localhost")
    parser.add_argument("--port", type=int, default=50000)
    parser.add_argument("--authkey", default="password")
    parser.add_argument("--frequency", type=int, default=5)
    parser.add_argument("-N", type=int, default=10)
    args = parser.parse_args()

    stop = Event()
    argst = (stop, args.address, args.port, args.authkey, args.frequency)
    threads = [Thread(target=target, args=argst) for _ in range(args.N)]

    for thread in threads:
        thread.start()

    # Spin
    try:
        while True:
            # Attempt to call the callback locally
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()

    for thread in threads:
        thread.join()
