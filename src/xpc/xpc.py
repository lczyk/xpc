"""
Single-file module for cross-process callbacks.

Hosted at https://github.com/MarcinKonowalczyk/xpc

This module provides a simple way to register callbacks in one process and call them in another. The motivating
use-case is to allow registering custom callbacks in an application during testing, or for dynamic instrumentation
(although the performance hit might be significant).

In a main application we want to create a Manager object and start it:

    ```python
    from xpc import Manager
    man = Manager(
        address=("localhost", 50000),
        authkey="password",
    )
    man.start()
    ```

We can then attempt callbacks from it:

    ```python
    result, found = manager.call("my_callback", 1, 2, 3, a=4, b=5)
    if found:
        print(f"Result: {result}")
    else:
        print("Callback not found")
    ```

In a separate process, we can register callbacks by creating a Manager object and connecting to the server:

    ```python
    from xpc import Manager

    manager = Manager(
        address=("localhost", 50000),
        authkey="password",
    )
    manager.connect()

    def my_callback(*args, **kwargs):
        print("my_callback args:", args, "kwargs:", kwargs)
        return 99

    manager.register("my_callback", my_callback)
    ```

The main app will then succeed in calling the callback. All the args and kwargs are pickled and sent over to the
process which registered the callback, and the return values are sent back. **The callback executes in the process
which registered it.**

TODO:
- [ ] The communication between manager and server can probably be done much neater -- this could all take place
    over a single connection between the server and the manager.
- [ ] `unregister` method for the manager and nicer handling of multiple `register` calls.
- [ ] Better error handling for errors in the callbacks. Currently, the server will just remove the callback from
    the registry no matter what. Thats appropriate if someone registers a callback with wrong signature, but
    what if we want the callback to return an error? We should probably return (value, error, found) from the call.
- [ ] Do we even need the server to run in a separate process? mutliprocessing.Manager does this, but we could
    probably just run the server in a separate thread and then we would not need to worry about the server process
    getting orphaned(?) This might also improve the performance of `call` from the main manager, since we would
    not need to call to a separate process???
- [ ] Switch to our own multiprocessing-style logging
- [ ]

Written by Marcin Konowalczyk.
"""

import enum
import os
import threading
import traceback
from functools import wraps
from multiprocessing import connection, process, util
from multiprocessing.managers import dispatch  # type: ignore
from multiprocessing.process import AuthenticationString  # type: ignore
from typing import TYPE_CHECKING, Any, Callable, TypeVar, Union

if TYPE_CHECKING:
    from typing_extensions import Literal, override
else:
    override = lambda x: x
    Literal = Union
_T = TypeVar("_T", bound=Callable)

__version__ = "0.3.0"

__all__ = ["Manager", "kill_multiprocessing_orphans"]


if os.environ.get("XPC_DEBUG", False):
    util.log_to_stderr(10)
    util.info("xpc module loaded")

    try:
        import colorlog

        logger = util.get_logger()
        logger.handlers[0].setFormatter(colorlog.ColoredFormatter())
    except ImportError:
        pass


def _resolve_address(
    address: Union[tuple[str, int], str, None] = None,
    family: Union[Literal["AF_INET", "AF_UNIX", "AF_PIPE"], None] = None,  # noqa: F821
) -> tuple[Union[tuple[str, int], str], Literal["AF_INET", "AF_UNIX", "AF_PIPE"]]:  # noqa: F821
    """Resolve the address and family for a connection"""
    if family is not None:
        connection._validate_family(family)  # type: ignore

    if address is None and family is None:  # Default address and family
        family = connection.default_family  # type: ignore
        address = connection.arbitrary_address(family)  # type: ignore
    elif address is None:  # Resolve the address based on the family
        address = connection.arbitrary_address(family)  # type: ignore
    elif family is None:  # Resolve the family based on the address
        family = connection.address_type(address)  # type: ignore
    return address, family  # type: ignore


class _Server:
    _authkey: bytes
    public: tuple[str, ...]
    address: Union[tuple[str, int], str]

    def serve(self, address: Union[tuple[str, int], str], timeout: Union[float, None] = None) -> None:
        self.stop_event = threading.Event()
        process.current_process()._manager_server = self  # type: ignore
        on_start = threading.Event()
        accepter = threading.Thread(target=self.accepter, args=(address, on_start))
        accepter.daemon = True
        accepter.start()
        on_start.wait(timeout=timeout)

    def accepter(
        self,
        address: Union[tuple[str, int], str],
        on_start: Union[threading.Event, None] = None,
    ) -> None:
        listener = connection.Listener(address=address, backlog=128)
        if on_start:
            on_start.set()
        while True:
            try:
                c = listener.accept()
            except OSError:
                continue
            t = threading.Thread(target=self.handle_request, args=(c,))
            t.daemon = True
            t.start()

    def _handle_request(self, c: connection.Connection) -> None:
        request = None
        try:
            connection.deliver_challenge(c, self._authkey)
            connection.answer_challenge(c, self._authkey)
            request = c.recv()
            _ignore, funcname, args, kwds = request
            assert funcname in self.public, f"{funcname!r} unrecognized"
            func = getattr(self, funcname)
        except Exception:
            msg = ("#TRACEBACK", traceback.format_exc())
        else:
            try:
                result = func(c, *args, **kwds)
            except Exception:
                msg = ("#TRACEBACK", traceback.format_exc())
            else:
                msg = ("#RETURN", result)

        try:
            c.send(msg)
        except Exception as e:
            try:
                c.send(("#TRACEBACK", traceback.format_exc()))
            except Exception:
                pass
            util.info("Failure to send message: %r", msg)
            util.info(" ... request was %r", request)
            util.info(" ... exception was %r", e)

    def handle_request(self, conn: connection.Connection) -> None:
        """Handle a new connection"""
        try:
            self._handle_request(conn)
        except SystemExit:
            util.info("SystemExit in server")
            pass
        finally:
            conn.close()


class State(enum.Enum):
    INITIAL = 0
    SERVER_STARTED = 1
    # SERVER_SHUTDOWN = 2
    CLIENT_STARTED = 3
    # CLIENT_SHUTDOWN = 4


def check_state(state: State) -> Callable[[_T], _T]:
    def decorator(func: _T) -> _T:
        @wraps(func)
        def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
            __tracebackhide__ = True
            assert (
                self._state == state
            ), f"Must be in state {state} to call {func.__name__}. Current state: {self._state}"
            return func(self, *args, **kwargs)

        return wrapper  # type: ignore

    return decorator


class Manager(_Server):
    public = ("_dummy", "_call", "_register")

    _address: Union[tuple[str, int], str]
    _address2: Union[tuple[str, int], str]
    _authkey: bytes

    def __init__(
        self,
        address: Union[tuple[str, int], str, None] = None,
        authkey: Union[bytes, str, None] = None,
        *,
        picklable: bool = False,
    ) -> None:
        address = _resolve_address(address)[0] if address is None else address
        self._address = address
        self._address2 = _resolve_address()[0]  # Also create an address for the reverse connection

        authkey = authkey.encode() if isinstance(authkey, str) else authkey
        authkey = process.current_process().authkey if authkey is None else authkey
        authkey = bytes(authkey) if picklable else AuthenticationString(authkey)
        self._picklable = picklable
        self._authkey = authkey

        self._state = State.INITIAL
        self._Listener, self._Client = connection.Listener, connection.Client

        self._registry_callback: dict[str, Callable] = {}
        self._registry_address: dict[str, Union[tuple[str, int], str]] = {}

    @check_state(State.INITIAL)
    def connect(self) -> None:
        """Connect manager object to the server process"""
        self.serve(address=self._address2)  # Start the callback server

        # Make a dummy call to the main server to make sure it is running
        conn = connection.Client(self._address, authkey=self._authkey)
        dispatch(conn, None, "_dummy")
        self._state = State.CLIENT_STARTED

    @check_state(State.CLIENT_STARTED)
    def register(self, name: str, callable: Callable) -> None:
        """Register a new callback on the server. Return the token."""
        util.debug(f"Registering '{name}'")

        # Register on the local
        self._registry_callback[name] = callable

        # Register on the server
        conn = self._Client(self._address, authkey=self._authkey)
        try:
            dispatch(conn, None, "_register", (name, self._address2))
        finally:
            conn.close()

    @check_state(State.SERVER_STARTED)
    def call(self, name: str, /, *args: Any, **kwds: Any) -> tuple[Any, bool]:
        """Attempt to call a callback on the server"""
        address = self._registry_address.get(name)
        if address is None:
            util.debug(f"Server does not know about '{name}'")
            return None, False
        else:
            util.debug(f"Server calling '{name}' at {address}")

        conn = None
        try:
            conn = connection.Client(address, authkey=self._authkey)
            return dispatch(conn, None, "_call", (name, *args), kwds), True
        except Exception as e:
            util.info(f"Error calling '{name}': {e}")
            # call is broken. remove it.
            self._registry_address.pop(name, None)
            return None, False
        finally:
            if conn:
                conn.close()

    @check_state(State.INITIAL)
    def start(self) -> None:
        """Spawn a server process for this manager object"""
        self.serve(address=self._address)  # Start the main server
        # Make a dummy call to the main server
        conn = connection.Client(self._address, authkey=self._authkey)
        dispatch(conn, None, "_dummy")
        self._state = State.SERVER_STARTED

    def _dummy(self, c: connection.Connection) -> None:
        pass

    def _call(self, c: connection.Connection, name: str, /, *args: Any, **kwds: Any) -> tuple[Any, bool]:
        """This is the method that is called by the server to call a callback"""
        util.debug(f"Client calling '{name}' with args: {args} and kwargs: {kwds}")
        if name not in self._registry_callback:
            raise ValueError(f"Callback {name!r} not found")
        return self._registry_callback[name](*args, **kwds)  # type: ignore

    def _register(self, c: connection.Connection, name: str, address: Union[tuple[str, int], str]) -> None:
        """Called by the client to register a callback"""
        util.debug(f"Server registering '{name}' at {address}")
        self._registry_address[name] = address

    @override
    def __reduce__(self) -> tuple[type, tuple, dict]:
        return (ManagerProxy, (self._address, self._authkey, self._registry_address), {})


class ManagerProxy:
    def __init__(
        self,
        address: Union[tuple[str, int], str],
        authkey: bytes,
        registry2: dict[str, Union[tuple[str, int], str]],
    ) -> None:
        self._address = address

        self._authkey = bytes(authkey) if authkey is not None else None
        self._Client = connection.Client
        self._registry_address = registry2

    def call(self, name: str, /, *args: Any, **kwds: Any) -> tuple[Any, bool]:
        """Attempt to call a callback on the server"""
        address = self._registry_address.get(name)
        if address is None:
            util.debug(f"Server does not know about '{name}'")
            return None, False
        else:
            util.debug(f"Server calling '{name}' at {address}")

        conn = None
        try:
            conn = connection.Client(address, authkey=self._authkey)
            return dispatch(conn, None, "_call", (name, *args), kwds), True
        except Exception as e:
            util.info(f"Error calling '{name}': {e}")
            # call is broken. remove it.
            self._registry_address.pop(name, None)
            return None, False
        finally:
            if conn:
                conn.close()

    def register(self, name: str, callable: Callable) -> None:
        raise RuntimeError("Cannot register a callback on a ManagerProxy")

    def start(self) -> None:
        raise RuntimeError("Cannot start a ManagerProxy. Start the main Manager object instead.")

    def connect(self) -> None:
        raise RuntimeError("Cannot connect a ManagerProxy. Connect the main Manager object instead.")


def _get_multiprocessing_pids() -> list[int]:
    pids: list[int] = []
    try:
        from psutil import process_iter
    except ImportError:
        return pids

    for proc in process_iter():
        try:
            if "python" in proc.name().lower():
                cmdline = " ".join(proc.cmdline())
                if "multiprocessing" in cmdline:
                    pids.append(proc.pid)
        except Exception:  # noqa: PERF203
            pass

    return pids


def kill_multiprocessing_orphans(*args: Any, **kwargs: Any) -> list[int]:
    """If a process is killed, its children can be left orphaned. This kills all
    python processes which have 'multiprocessing' in their command line args.

    Example usage:
    >>> import signal
    >>> signal.signal(signal.SIGINT, kill_multiprocessing_orphans)
    """

    try:
        from psutil import Process
    except ImportError:
        return []

    pids = _get_multiprocessing_pids()
    for pid in pids:
        try:
            Process(pid).kill()
        except Exception:  # noqa: PERF203
            pass

    return pids


__license__ = """
Copyright 2024 Marcin Konowalczyk

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are
met:

1.  Redistributions of source code must retain the above copyright
    notice, this list of conditions and the following disclaimer.

2.  Redistributions in binary form must reproduce the above copyright
    notice, this list of conditions and the following disclaimer in the
    documentation and/or other materials provided with the distribution.

3.  Neither the name of the copyright holder nor the names of its
    contributors may be used to endorse or promote products derived from
    this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
"AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A
PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED
TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
"""


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--kill-orphans", action="store_true")
    args = parser.parse_args()

    if args.kill_orphans:
        pids = kill_multiprocessing_orphans()
        print(f"Killed {len(pids)} orphaned processes")
    else:
        parser.print_help()
