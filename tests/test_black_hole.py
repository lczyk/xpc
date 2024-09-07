from multiprocessing.connection import Listener

import pytest
from conftest import Subtests
import threading
import time
from xpc import Manager, find_free_port
from xpc.xpc import Client, Listener
from multiprocessing.connection import AuthenticationError


def check_address(address: tuple) -> bool:
    listener = None
    try:
        listener = Listener(address)
    except OSError:
        return False
    finally:
        if listener:
            listener.close()
    return True


def test_black_hole_with_timeout(subtests: Subtests) -> None:
    port = find_free_port()
    address = ("localhost", port)
    password = b"password"

    # We should be able to connect to the address
    man = Manager(
        address=address,
        authkey=password,
    )
    man.start(timeout=1.0)
    man.shutdown()

    # We should *not* deadlock when the address is already in use
    # but not responding
    for timeout in [1.0, None]:
        with (
            subtests.test(timeout=timeout),
            pytest.raises(TimeoutError),
            Listener(address, authkey=password),
        ):
            man = Manager(
                address=address,
                authkey=password,
            )
            man.connect(timeout=timeout)


def _test_listener_client_passwords(
    lauthkey: bytes | None,
    cauthkey: bytes | None,
    timeout: float | None = None,
) -> tuple[Exception | None, Exception | None, list]:
    address = ("localhost", find_free_port())

    thread_exc = None
    thread_got = []
    client_exc = None

    stop = threading.Event()

    def target() -> None:
        try:
            with Listener(address, authkey=lauthkey) as listener:
                c = listener.accept(timeout=timeout)
                while not stop.is_set():
                    if c.poll(timeout=timeout):
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
        with Client(address, authkey=cauthkey, timeout=timeout) as client:
            client.send("hello")
            time.sleep(0.1)
            client.send(None)

    except Exception as e:
        client_exc = e

    finally:
        stop.set()
        t.join()

    return thread_exc, client_exc, thread_got


def test_no_passwords() -> None:
    te, ce, got = _test_listener_client_passwords(None, None)
    assert te is None
    assert ce is None
    assert got == ["hello"]


def test_two_matching_passwords() -> None:
    te, ce, got = _test_listener_client_passwords(b"password", b"password")
    assert te is None
    assert ce is None
    assert got == ["hello"]


def test_client_has_wrong_password() -> None:
    te, ce, got = _test_listener_client_passwords(b"password", b"wrong")
    assert isinstance(te, AuthenticationError)
    assert str(te) == "digest received was wrong"
    assert isinstance(ce, AuthenticationError)
    assert str(ce) == "digest sent was rejected"
    assert got == []


def test_client_has_no_password() -> None:
    te, ce, got = _test_listener_client_passwords(b"password", None)
    assert isinstance(te, AuthenticationError)
    assert ce is None
    assert got == []


@pytest.mark.skip(reason="deadlocks")
def test_listener_has_no_password() -> None:
    _test_listener_client_passwords(None, b"password")


def test_listener_has_no_password_timeout() -> None:
    te, ce, got = _test_listener_client_passwords(None, b"password", timeout=0.25)
    assert te is None
    assert isinstance(ce, TimeoutError)
    assert got == []


# if __name__ == "__main__":
#     print(" no passwords ".center(40, "-"))
#     print(_test(listener=None, client=None))

#     print(" two matching passwords ".center(40, "-"))
#     print(_test(listener="password", client="password"))

#     print(" client has wrong password ".center(40, "-"))
#     print(_test(listener="password", client="wrong"))

#     print(" client has no password ".center(40, "-"))
#     print(_test(listener="password", client=None))

#     # This is the case which deadlocks
#     print(" listener has no password ".center(40, "-"))
#     print(_test(listener=None, client="password"))
