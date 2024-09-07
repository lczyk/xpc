import socket
import threading
import time
from multiprocessing.connection import Client, Listener


def _test(*, listener: "str | None", client: "str | None") -> tuple["Exception | None, Exception | None, list"]:
    _autkey_listener = listener.encode() if listener else None
    _authkey_client = client.encode() if client else None

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("localhost", 0))
        address = s.getsockname()

    thread_exc = None
    thread_got = []
    client_exc = None

    def target() -> None:
        try:
            with Listener(address, authkey=_autkey_listener) as l:
                c = l.accept()
                while True:
                    value = c.recv()
                    if not value:
                        break
                    thread_got.append(value)
        except Exception as e:
            nonlocal thread_exc
            thread_exc = e

    t = threading.Thread(target=target)
    t.start()

    try:
        with Client(address, authkey=_authkey_client) as c:
            c.send("hello")
            time.sleep(0.1)
            c.send(None)

        t.join()
    except Exception as e:
        client_exc = e

    return thread_exc, client_exc, thread_got


if __name__ == "__main__":
    print(" no passwords ".center(40, "-"))
    print(_test(listener=None, client=None))

    print(" two matching passwords ".center(40, "-"))
    print(_test(listener="password", client="password"))

    print(" client has wrong password ".center(40, "-"))
    print(_test(listener="password", client="wrong"))

    print(" client has no password ".center(40, "-"))
    print(_test(listener="password", client=None))

    # This is the case which deadlocks
    print(" listener has no password ".center(40, "-"))
    print(_test(listener=None, client="password"))
