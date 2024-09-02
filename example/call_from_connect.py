import sys
import time
from pathlib import Path

__project_root__ = Path(__file__).resolve().parents[1]
sys.path.append(str(__project_root__ / "src"))


from xpc import Manager

if __name__ == "__main__":
    manager = Manager(
        address=("localhost", 50000),
        authkey=b"password",
    )
    manager.connect()
    print("Connected to server")

    # Spin
    try:
        while True:
            print(".", end="", flush=True)
            value, found = manager.call("my_callback", 1, 2, 3, hello="world")
            print(f"callback found: {found}")
            print(f"callback returned: {value}")
            time.sleep(1)
    except KeyboardInterrupt:
        pass
