import sys
from collections.abc import Generator
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

import pytest

__project_root = Path(__file__).resolve().parents[1]
sys.path.append(str(__project_root / "src"))


from _server_fixture import *  # noqa: E402, F403


@pytest.fixture(autouse=True)
def verbosity(request: pytest.FixtureRequest) -> int:
    verbose: int
    try:
        _verbose = request.config.option.verbose
        assert isinstance(_verbose, int)
        verbose = _verbose
    except Exception:
        verbose = 0

    return verbose


##========================================================================================================
##
##   ####  ##   ##  #####  ######  ######   ####  ######  ####
##  ##     ##   ##  ##  ##   ##    ##      ##       ##   ##
##   ###   ##   ##  #####    ##    #####    ###     ##    ###
##     ##  ##   ##  ##  ##   ##    ##         ##    ##      ##
##  ####    #####   #####    ##    ######  ####     ##   ####
##
##========================================================================================================


class Subtests(Protocol):
    def test(self, **kwargs: Any) -> "Subtests": ...

    def __enter__(self) -> "Subtests": ...

    def __exit__(self, *args: Any) -> None: ...


class NullSubtests:
    def test(self, **kwargs: Any) -> "NullSubtests":
        return self

    def __enter__(self) -> "NullSubtests":
        return self

    def __exit__(self, *args: Any) -> None:
        pass


if TYPE_CHECKING:
    _null_subtests: Subtests = NullSubtests.__new__(NullSubtests)


@pytest.fixture(autouse=True)
def add_space_before_print() -> Generator[None, None, None]:
    import builtins

    _print = builtins.print

    def patched_print(*args: Any, **kwargs: Any) -> None:
        _print(end="\n")  # Add a newline
        _print(*args, **kwargs)
        builtins.print = _print

    builtins.print = patched_print
    try:
        yield
    finally:
        builtins.print = _print
