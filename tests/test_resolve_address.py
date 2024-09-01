import sys

import pytest

from xpc.xpc import _resolve_address as resolve_address


def test_resolve_address() -> None:
    _address, _family = resolve_address()
    ...


def test_resolve_address_af_inet() -> None:
    address, family = resolve_address(family="AF_INET")
    assert family == "AF_INET"
    assert address == ("localhost", 0)


def test_resolve_address_af_unix() -> None:
    _address, family = resolve_address(family="AF_UNIX")
    assert family == "AF_UNIX"
    # print(address)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_resolve_address_af_pipe() -> None:
    _address, family = resolve_address(family="AF_PIPE")
    assert family == "AF_PIPE"
    # print(address)
