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

import os
import signal
import sys
import threading
import traceback
from multiprocessing import connection, process, util
from multiprocessing.context import BaseContext, ProcessError
from multiprocessing.managers import (  # type: ignore
    State,
    dispatch,
    get_context,
)
from multiprocessing.process import AuthenticationString  # type: ignore
from typing import TYPE_CHECKING, Any, Callable, Union

if TYPE_CHECKING:
    from typing_extensions import Literal, override
else:
    override = lambda x: x
    Literal = Union


__version__ = "0.2.0"

__all__ = ["Manager", "kill_multiprocessing_orphans"]


if os.environ.get("XPC_DEBUG", False):
    util.log_to_stderr(10)
    util.info("xpc module loaded")

    try:
        import colorlog

        logger = util.get_logger()
        handler = colorlog.StreamHandler()
        handler.setFormatter(colorlog.ColoredFormatter())
        logger.addHandler(handler)
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

    raise_on_error: bool = False

    def serve(self, address: Union[tuple[str, int], str]) -> None:
        self.stop_event = threading.Event()
        process.current_process()._manager_server = self  # type: ignore
        accepter = threading.Thread(target=self.accepter, args=(address,))
        accepter.daemon = True
        accepter.start()

    def accepter(
        self,
        address: Union[tuple[str, int], str],
        on_start: Union[threading.Event, None] = None,
    ) -> None:
        listener = connection.Listener(address=address, backlog=128)
        if on_start:
            print("Setting on_start")
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
            ignore, funcname, args, kwds = request
            assert funcname in self.public, f"{funcname!r} unrecognized"
            func = getattr(self, funcname)
        except Exception:
            msg = ("#TRACEBACK", traceback.format_exc())
        else:
            try:
                result = func(c, *args, **kwds)
            except Exception:
                if self.raise_on_error:
                    raise
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
            util.info("SystemExit in manager process")
            pass
        finally:
            conn.close()


class Server(_Server):
    public = ("shutdown", "register", "call", "dummy", "accept_connection")

    def __init__(
        self,
        address: Union[tuple[str, int], str, None] = None,
        authkey: Union[bytes, str] = b"",
        *,
        picklable: bool = False,
    ):
        if not isinstance(authkey, bytes):
            raise TypeError(f"Authkey {authkey!r} is type {type(authkey)!s}, not bytes")

        if address is None:
            raise ValueError("Address must be provided")

        self._registry: dict[str, str] = {}
        authkey = bytes(authkey) if picklable else AuthenticationString(authkey)
        self._authkey = authkey

        self._address = address

    def dummy(self, c: connection.Connection) -> None:
        pass

    def register(self, c: connection.Connection, name: str, address: str) -> None:
        """Called by the client to register a callback"""
        self._registry[name] = address

    def shutdown(self, c: connection.Connection) -> None:
        """Called by the client to shut down the server"""
        try:
            util.debug("manager received shutdown message")
            c.send(("#RETURN", None))
        except BaseException:
            import traceback

            traceback.print_exc()
        finally:
            self.stop_event.set()

    def call(self, c: connection.Connection, name: str, /, *args: Any, **kwds: Any) -> tuple[Any, bool]:
        util.debug(f"Calling {name} with args {args} and kwargs {kwds}")
        if name not in self._registry:
            return None, False
        address = self._registry[name]
        conn = None
        try:
            conn = connection.Client(address, authkey=self._authkey)
            return dispatch(conn, None, "_call", (name, *args), kwds), True
        except Exception as e:
            util.info(f"Error calling {name}: {e}")
            # mpc is broken. Remove it.
            self._registry.pop(name, None)
            return None, False
        finally:
            if conn:
                conn.close()


class Manager(_Server):
    _Server = Server
    public = ("_call",)

    _address: Union[tuple[str, int], str]
    _address2: Union[tuple[str, int], str]
    _authkey: bytes

    raise_on_error: bool = True

    def __init__(
        self,
        address: Union[tuple[str, int], str, None] = None,
        authkey: Union[bytes, None] = None,
        ctx: Union[BaseContext, None] = None,
        *,
        shutdown_timeout: float = 1.0,
        picklable: bool = False,
    ) -> None:
        address = _resolve_address(address)[0] if address is None else address
        self._address = address
        self._address2 = _resolve_address()[0]  # Also create an address for the reverse connection

        authkey = process.current_process().authkey if authkey is None else authkey
        authkey = bytes(authkey) if picklable else AuthenticationString(authkey)
        self._picklable = picklable
        self._authkey = authkey

        self._state = State()
        self._state.value = State.INITIAL
        self._Listener, self._Client = connection.Listener, connection.Client
        self._ctx = ctx or get_context()
        if not hasattr(self._ctx, "Process"):
            raise ValueError("Context does not support Process objects")

        self._shutdown_timeout = shutdown_timeout

        # NOTE: do authentication later
        self._registry: dict[str, Callable] = {}

    def connect(self) -> None:
        """Connect manager object to the server process"""
        self.serve(address=self._address2)  # Start the callback server
        conn = connection.Client(self._address, authkey=self._authkey)
        dispatch(conn, None, "dummy")
        self._state.value = State.STARTED

    @override
    def register(self, name: str, callable: Callable) -> None:  # type: ignore
        """Register a new callback on the server. Return the token."""
        assert self._state.value == State.STARTED, "server not yet started"
        # Register on the local
        self._registry[name] = callable
        # Register on the remote
        assert self._address is not None
        conn = self._Client(self._address, authkey=self._authkey)
        try:
            dispatch(conn, None, "register", (name, self._address2))
        finally:
            conn.close()

    def call(self, name: str, /, *args: Any, **kwds: Any) -> tuple[Any, bool]:
        """Attempt to call a callback on the server"""
        assert self._state.value == State.STARTED, "server not yet started"
        assert self._address is not None
        # TODO: hold conn in tls
        conn = self._Client(self._address, authkey=self._authkey)
        try:
            return dispatch(conn, None, "call", (name, *args), kwds)  # type: ignore
        finally:
            conn.close()

    def _call(self, c: connection.Connection, name: str, /, *args: Any, **kwds: Any) -> tuple[Any, bool]:
        """This is the method that is called by the server to call a callback"""
        if name not in self._registry:
            raise ValueError(f"Callback {name!r} not found")
        return self._registry[name](*args, **kwds)  # type: ignore

    ##############################

    def start(self) -> None:
        """Spawn a server process for this manager object"""
        if self._state.value != State.INITIAL:
            if self._state.value == State.STARTED:
                raise ProcessError("Already started server")
            elif self._state.value == State.SHUTDOWN:
                raise ProcessError("Manager has shut down")
            else:
                raise ProcessError(f"Unknown state {self._state.value!r}")

        # pipe over which we will retrieve address of server
        reader, writer = connection.Pipe(duplex=False)

        # spawn process which runs a server
        assert hasattr(self._ctx, "Process")
        self._process = self._ctx.Process(
            target=type(self)._run_server,
            args=(
                self._address,
                self._authkey,
                writer,
                self._picklable,
            ),
        )
        ident = ":".join(str(i) for i in self._process._identity)
        self._process.name = type(self).__name__ + "-" + ident
        self._process.start()

        # get address of server
        writer.close()
        self._address = reader.recv()
        reader.close()

        # register a finalizer
        self._state.value = State.STARTED
        self.shutdown = util.Finalize(
            self,
            type(self)._finalize_manager,
            args=(self._process, self._address, self._authkey, self._state, self._Client, self._shutdown_timeout),
            exitpriority=0,
        )

    @classmethod
    def _run_server(
        cls,
        address: Union[tuple[str, int], str],
        authkey: Union[bytes, str],
        writer: object,
        picklable: bool = False,
    ) -> None:
        """Create a server, report its address and run it"""
        # bpo-36368: protect server process from KeyboardInterrupt signals
        signal.signal(signal.SIGINT, signal.SIG_IGN)

        # create server
        server = cls._Server(address, authkey, picklable=picklable)

        # inform parent process of the server's address
        writer.send(server._address)  # type: ignore
        writer.close()  # type: ignore

        # run the manager
        util.info("manager serving at %r", server._address)

        try:
            server.serve(address=server._address)
            try:
                while not server.stop_event.is_set():
                    server.stop_event.wait(1)
            except (KeyboardInterrupt, SystemExit):
                pass
        finally:
            if sys.stdout != sys.__stdout__:  # what about stderr?
                util.debug("resetting stdout, stderr")
                sys.stdout = sys.__stdout__
                sys.stderr = sys.__stderr__
            sys.exit(0)

    @staticmethod
    def _finalize_manager(
        process: process.BaseProcess,
        address: Union[tuple[str, int], str],
        authkey: Union[bytes, str],
        state: State,
        _Client: object,
        shutdown_timeout: float,
    ) -> None:
        """Shutdown the manager process; will be registered as a finalizer"""
        if process.is_alive():
            util.info("sending shutdown message to manager")
            try:
                conn = _Client(address, authkey=authkey)  # type: ignore
                try:
                    dispatch(conn, None, "shutdown")
                finally:
                    conn.close()
            except Exception:
                pass

            process.join(timeout=shutdown_timeout)
            if process.is_alive():
                util.info("manager still alive")
                if hasattr(process, "terminate"):
                    util.info("trying to `terminate()` manager process")
                    process.terminate()
                    process.join(timeout=shutdown_timeout)
                    if process.is_alive():
                        util.info("manager still alive after terminate")
                        process.kill()
                        process.join()

        state.value = State.SHUTDOWN

    @override
    def __reduce__(self) -> tuple[type, tuple, dict]:
        return (ManagerProxy, (self._address, self._authkey), {})


class ManagerProxy:
    def __init__(
        self,
        address: Union[tuple[str, int], str],
        authkey: bytes,
    ) -> None:
        self._address = address

        self._authkey = bytes(authkey) if authkey is not None else None
        self._Client = connection.Client

    def call(self, name: str, /, *args: Any, **kwds: Any) -> tuple[Any, bool]:
        """Attempt to call a callback on the server"""

        try:
            conn = self._Client(self._address, authkey=self._authkey)
        except ConnectionRefusedError:
            # The proxy cannot connect to the server
            return None, False

        try:
            return dispatch(conn, None, "call", (name, *args), kwds)  # type: ignore
        finally:
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
