from typing import Optional

import pytest
from xpc import Manager


def start_man() -> Manager:
    man: Optional[Manager] = Manager(
        address=("localhost", 9999),
        authkey="password",
    )
    try:
        assert man
        man.start(timeout=1.0)
    except ConnectionRefusedError:
        man = None
    if not man:
        pytest.fail("Failed to connect to the server.", pytrace=False)
    return man


def test_man_1() -> None:
    man = start_man()
    man.shutdown()


def test_man_2() -> None:
    man = start_man()
    man.shutdown()
