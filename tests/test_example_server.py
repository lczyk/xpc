import signal
import subprocess
import sys
from contextlib import suppress
from threading import Event

import pytest

from xpc import Manager


@pytest.mark.skipif(sys.platform != "win32", reason="Test only for Windows")
def test_run_server_windows(server: subprocess.Popen) -> None:
    # Send a signal to the server to stop
    server.send_signal(signal.SIGTERM)
    retcode = server.wait()
    assert retcode == 1


@pytest.mark.skipif(sys.platform == "win32", reason="Test only for non-Windows")
def test_run_server_nonwindows(server: subprocess.Popen) -> None:
    # Send a signal to the server to stop
    server.send_signal(signal.SIGINT)
    retcode = server.wait()
    assert retcode == 0


@pytest.mark.skipif(sys.platform != "win32", reason="Test only for Windows")
def test_run_server_again_windows(server: subprocess.Popen) -> None:
    # Send a signal to the server to stop
    server.send_signal(signal.SIGTERM)
    retcode = server.wait()
    assert retcode == 1


@pytest.mark.skipif(sys.platform == "win32", reason="Test only for non-Windows")
def test_run_server_again_nonwindows(server: subprocess.Popen) -> None:
    # Send a signal to the server to stop
    server.send_signal(signal.SIGINT)
    retcode = server.wait()
    assert retcode == 0


def test_run_server_nostop(server: subprocess.Popen) -> None:
    pass


def test_run_server_nostop_again(server: subprocess.Popen) -> None:
    pass


def test_register_callback(server: subprocess.Popen) -> None:
    man = Manager(
        address=("localhost", 19191),
        authkey="password",
    )
    man.connect()

    i = 0

    called = Event()

    def my_callback(*args: object, **kwargs: object) -> None:
        nonlocal i
        i += 1
        called.set()

    assert i == 0

    man.register("my_callback", my_callback)

    with suppress(TimeoutError):
        called.wait(2.0)

    assert called.is_set()
    assert i > 0
