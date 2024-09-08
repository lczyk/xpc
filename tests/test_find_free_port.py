import psutil
import pytest
from xpc import find_free_port


def get_all_used_ports() -> set:
    return set(conn.laddr.port for conn in psutil.net_connections())


def test_find_free_port() -> None:
    new_port = find_free_port()
    try:
        all_used_ports = get_all_used_ports()
    except psutil.AccessDenied:
        pytest.skip("This test requires root privileges")
    assert new_port not in all_used_ports
