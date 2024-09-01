import signal
import subprocess
import sys

import pytest


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
