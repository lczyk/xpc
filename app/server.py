import argparse
import datetime
import multiprocessing
import multiprocessing.managers
import time


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.parse_args()

    manager = multiprocessing.managers.BaseManager(
        address=("localhost", 50000),
        authkey=b"password",
    )
    manager.start()

    while True:
        now = datetime.datetime.now()
        if hasattr(manager, "my_callback"):
            value = manager.my_callback()
            print(f"{now}: {value}")
        else:
            print(f"{now}: Method my_callback not found")
        time.sleep(1)


if __name__ == "__main__":
    main()
