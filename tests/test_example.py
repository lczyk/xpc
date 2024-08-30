import pytest
import time
from pathlib import Path

__project_root__ = Path(__file__).parent.parent
__example_server__ = __project_root__ / "example" / "server.py"

import subprocess


@pytest.fixture
def server() -> subprocess.Popen:
    assert __example_server__.exists()
    args = ["python", str(__example_server__)]
    p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    yield p
    p.kill()


def test_example(server: subprocess.Popen) -> None:
    print(server)
    time.sleep(0.1)
    print(f"Status: {server.poll()}")
    print("Killing server")
