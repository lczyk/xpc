import signal
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

__project_root__ = Path(__file__).parent.parent
__example_server__ = __project_root__ / "example" / "server.py"

from xpc import kill_multiprocessing_orphans


@pytest.fixture
def server() -> Iterator[subprocess.Popen]:
    assert __example_server__.exists()

    import sys

    interpreter = sys.executable
    args = [interpreter, str(__example_server__)]

    signal.signal(signal.SIGINT, kill_multiprocessing_orphans)
    with subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ) as p:
        time.sleep(0.1)
        assert p.poll() is None
        yield p
        if p.poll() is None:
            p.send_signal(signal.SIGINT)


def test_run_server(server: subprocess.Popen) -> None:
    # Send a signal to the server to stop
    server.send_signal(signal.SIGINT)
    retcode = server.wait()
    assert retcode == 0


def test_run_server_again(server: subprocess.Popen) -> None:
    server.send_signal(signal.SIGINT)
    retcode = server.wait()
    assert retcode == 0


def test_run_server_nostop(server: subprocess.Popen) -> None:
    pass


def test_run_server_nostop_again(server: subprocess.Popen) -> None:
    pass
