import signal
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

__project_root__ = Path(__file__).parent.parent
__example_server__ = __project_root__ / "example" / "server.py"


@pytest.fixture
def server() -> Iterator[subprocess.Popen]:
    assert __example_server__.exists()

    interpreter = sys.executable
    args = [interpreter, str(__example_server__)]

    with subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ) as p:
        time.sleep(0.1)
        assert p.poll() is None
        yield p
        if p.poll() is None:
            if sys.platform == "win32":
                p.send_signal(signal.SIGTERM)
            else:
                p.send_signal(signal.SIGINT)
            p.wait()
        assert p.poll() is not None
