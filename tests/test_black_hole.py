from multiprocessing.connection import Listener

import pytest
from conftest import Subtests

from xpc import Manager, find_free_port


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
            man.connect(timeout=1.0)


# def test_black_hole_without_timeout() -> None:
#     port = find_free_port()
#     address = ("localhost", port)
#     password = b"password"

#     # We should be able to connect to the address
#     man = Manager(
#         address=address,
#         authkey=password,
#     )
#     man.start(timeout=1.0)
#     man.shutdown()

#     # We should *not* deadlock when the address is already in use
#     # but not responding
#     with (
#         pytest.raises(TimeoutError),
#         Listener(address, authkey=password),
#     ):
#         man = Manager(
#             address=address,
#             authkey=password,
#         )
#         man.connect()
