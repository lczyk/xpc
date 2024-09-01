import sys
from collections.abc import Generator
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

import pytest

__project_root = Path(__file__).resolve().parents[1]
sys.path.append(str(__project_root / "src"))


from _server_fixture import *  # noqa: E402, F403


# Register a custom pytest --kill-orphans command line option
def pytest_addoption(parser: Any) -> None:
    parser.addoption(
        "--kill-orphans",
        action="store_true",
        default=False,
        help="Kill any orphaned processes after the test run",
    )


# Register a custom code to run before all tests
def pytest_sessionstart(session: Any) -> None:
    if session.config.getoption("--kill-orphans"):
        try:
            from xpc import kill_multiprocessing_orphans

            killed_pids = kill_multiprocessing_orphans()
            if killed_pids:
                print(f"Killed orphaned processes: {killed_pids}")
        except Exception as e:
            print(f"Error killing orphans: {e}")
            pass


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
