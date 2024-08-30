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
    with (
        open("server.log", "w+") as f,
        subprocess.Popen(
            args,
            stdout=f,
            stderr=subprocess.STDOUT,
            bufsize=0,
            start_new_session=True,
        ) as p,
    ):
        time.sleep(1)
        yield p


def test_run_server(server: subprocess.Popen) -> None:
    assert server.poll() is None
    server.send_signal(signal.SIGINT)
    retcode = server.wait()
    assert retcode == 0


# def test_run_server_again(server: subprocess.Popen) -> None:
#     assert server.poll() is None
