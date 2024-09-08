import threading
import time
from multiprocessing.connection import AuthenticationError  # type: ignore[attr-defined]
from typing import Optional
import traceback

import pytest
from xpc import Manager, find_free_port
from xpc.xpc import Client, Listener


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


@pytest.mark.parametrize("timeout", [None, 1.0])
def test_black_hole_with_timeout(timeout: Optional[float]) -> None:
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
    with (
        pytest.raises(TimeoutError),
        Listener(address, authkey=password),
    ):
        man = Manager(
            address=address,
            authkey=password,
        )
        man.connect(timeout=timeout)


def _test_listener_client_passwords(
    lauthkey: Optional[bytes],
    cauthkey: Optional[bytes],
    timeout: Optional[float] = None,
    print_traceback: bool = False,
) -> tuple[Optional[Exception], Optional[Exception], list]:
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
            if print_traceback:
                print("Listener exception:")
                traceback.print_exc()
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
        if print_traceback:
            print("Client exception:")
            traceback.print_exc()
        client_exc = e

    finally:
        stop.set()
        t.join()

    return thread_exc, client_exc, thread_got


def test_no_passwords(verbosity: int) -> None:
    te, ce, got = _test_listener_client_passwords(None, None, print_traceback=verbosity > 1)
    assert te is None
    assert ce is None
    assert got == ["hello"]


def test_two_matching_passwords(verbosity: int) -> None:
    te, ce, got = _test_listener_client_passwords(b"password", b"password", print_traceback=verbosity > 1)
    assert te is None
    assert ce is None
    assert got == ["hello"]


def test_client_has_wrong_password(verbosity: int) -> None:
    te, ce, got = _test_listener_client_passwords(b"password", b"wrong", print_traceback=verbosity > 1)
    assert isinstance(te, AuthenticationError)
    assert str(te) == "digest received was wrong"
    assert isinstance(ce, AuthenticationError)
    assert str(ce) == "digest sent was rejected"
    assert got == []


def test_client_has_no_password(verbosity: int) -> None:
    te, ce, got = _test_listener_client_passwords(b"password", None, print_traceback=verbosity > 1)
    assert isinstance(te, AuthenticationError)
    assert ce is None
    assert got == []


@pytest.mark.skip(reason="deadlocks")
def test_listener_has_no_password(verbosity: int) -> None:
    _test_listener_client_passwords(None, b"password")


def test_listener_has_no_password_timeout(verbosity: int) -> None:
    te, ce, got = _test_listener_client_passwords(None, b"password", timeout=0.25, print_traceback=verbosity > 1)
    assert te is None
    assert isinstance(ce, TimeoutError)
    assert got == []


def _test_listener_deadlock(
    timeout: Optional[float] = None,
    print_traceback: bool = False,
) -> tuple[Optional[Exception], bool]:
    address = ("localhost", find_free_port())

    thread_exc = None
    got_past_accept = False

    def target() -> None:
        try:
            with Listener(address, authkey=b"password") as listener:
                try:
                    listener.accept(timeout=timeout)
                except TimeoutError:
                    pass
                nonlocal got_past_accept
                got_past_accept = True
        except Exception as e:
            if print_traceback:
                print("Listener exception:")
                traceback.print_exc()
            nonlocal thread_exc
            thread_exc = e

    t = threading.Thread(target=target)
    t.start()

    with Client(address, authkey=None, timeout=timeout):
        time.sleep(1.0)

    t.join()

    return thread_exc, got_past_accept


def test_listener_deadlock(verbosity: int) -> None:
    te, got = _test_listener_deadlock(None, print_traceback=verbosity > 1)
    assert te is not None
    assert not got


def test_listener_deadlock_timeout(verbosity: int) -> None:
    te, got = _test_listener_deadlock(0.25, print_traceback=verbosity > 1)
    assert te is None
    assert got
