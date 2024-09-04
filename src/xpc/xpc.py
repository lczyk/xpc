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
- [ ] `unregister` method for the manager and nicer handling of multiple `register` calls.
- [ ] Better error handling for errors in the callbacks. Currently, the server will just remove the callback from
    the registry no matter what. Thats appropriate if someone registers a callback with wrong signature, but
    what if we want the callback to return an error? We should probably return (value, error, found) from the call.

Written by Marcin Konowalczyk.
"""

import os
import threading
import traceback
from multiprocessing import connection, process, util
from multiprocessing.managers import dispatch as _dispatch  # type: ignore
from multiprocessing.process import AuthenticationString  # type: ignore
from typing import TYPE_CHECKING, Any, Callable, Optional, TypeVar, Union

if TYPE_CHECKING:
    from typing_extensions import Literal, override
else:
    override = lambda x: x
    Literal = Union
_T = TypeVar("_T", bound=Callable)

_Address = Union[tuple[str, int], str]

__version__ = "0.7.4"

__all__ = ["Manager"]

_logger: "Optional[logging.Logger]" = None

_debug = lambda msg, *args: _logger.log(10, msg, *args, stacklevel=2) if _logger else None
_info = lambda msg, *args: _logger.log(20, msg, *args, stacklevel=2) if _logger else None

if os.environ.get("XPC_DEBUG", False):
    import logging

    _logger = logging.getLogger("xpc")
    handler = logging.StreamHandler()
    format = "[%(levelname)s/%(processName)s/%(threadName)s] %(message)s"
    try:
        import colorlog

        handler.setFormatter(colorlog.ColoredFormatter("%(log_color)s" + format))
    except ImportError:
        formatter = logging.Formatter(format)
        handler.setFormatter(formatter)
    _logger.addHandler(handler)
    _logger.setLevel(logging.DEBUG)
    _info("xpc module loaded")


def _resolve_address(
    address: Union[_Address, None] = None,
    family: Union[Literal["AF_INET", "AF_UNIX", "AF_PIPE"], None] = None,  # noqa: F821
) -> tuple[_Address, Literal["AF_INET", "AF_UNIX", "AF_PIPE"]]:  # noqa: F821
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


def conn_and_dispatch(
    address: _Address,
    authkey: bytes,
    name: str,
    args: tuple[Any, ...] = (),
    kwds: Optional[dict[str, Any]] = {},  # noqa: B006
) -> tuple[Any, Optional[Exception]]:
    if kwds is None:
        kwds = {}
    conn = None
    exc = None
    rv = None
    try:
        conn = connection.Client(address, authkey=authkey)
        rv = _dispatch(conn, None, name, args, kwds)
    except Exception as e:
        exc = e
    finally:
        if conn:
            conn.close()

    return rv, exc


class _Server:
    _authkey: bytes
    public: tuple[str, ...]
    _this_address: Optional[_Address]

    def shutdown(self) -> None:
        """Shutdown the server. Will be overridden in `serve` by the finalizer."""
        pass

    def serve(self, address: _Address, authkey: bytes, timeout: Union[float, None] = None) -> None:
        self.stop_event = threading.Event()
        process.current_process()._manager_server = self  # type: ignore
        on_start = threading.Event()
        accepter = threading.Thread(target=self.accepter, args=(address, authkey, on_start))
        accepter.daemon = True
        accepter.start()
        if not on_start.wait(timeout=timeout):
            raise TimeoutError("Server failed to start")

        args = (accepter, self.stop_event, 0.25, address, authkey)
        self.shutdown = util.Finalize(self, self._finalize, args=args, exitpriority=0)  # type: ignore

    @staticmethod
    def _finalize(
        accepter: threading.Thread,
        stop_event: threading.Event,
        shutdown_timeout: float,
        address: _Address,
        authkey: bytes,
    ) -> None:
        _debug("Finalizing server")
        if accepter.is_alive():
            _info("Accepter is still alive. Stopping it.")
            stop_event.set()

            # Make a dummy call to the server to make it notice the stop event
            _, exc = conn_and_dispatch(address, authkey, "_dummy")
            if exc:
                _info(f"Failed to stop server: {exc!r}")

            accepter.join(timeout=shutdown_timeout)
            if accepter.is_alive():
                _info("Accepter is still alive!!")
                # Final attempt at killing the accepter thread
                try:  # noqa: SIM105, RUF100
                    accepter._stop()  # type: ignore
                except Exception:
                    pass

    def accepter(
        self,
        address: _Address,
        authkey: bytes,
        on_start: Union[threading.Event, None] = None,
    ) -> None:
        listener = None
        try:
            listener = connection.Listener(address=address, backlog=128)
            try:
                if on_start:
                    on_start.set()
                while True:
                    if self.stop_event.is_set():
                        _debug("Server stop event set. Stopping.")
                        break
                    try:
                        c = listener.accept()
                    except OSError:
                        continue
                    t = threading.Thread(target=self.handle_request, args=(c,))
                    t.name = "handle_request"
                    t.daemon = True
                    t.start()
            except Exception as e:
                _info(f"Server failed: {e!r}")
        except Exception as e:
            _info(f"Failed to create listener on {address}: {e!r}")
            return
        finally:
            if listener:
                try:
                    listener.close()
                except Exception as e:
                    _info(f"Failed to close listener: {e!r}")

    def handle_request(self, conn: connection.Connection) -> None:
        """Handle a new connection"""
        try:
            self._handle_request(conn)
        except SystemExit:
            _info("SystemExit in server")
            pass
        finally:
            conn.close()
        _debug("Connection closed")

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
            try:  # noqa: SIM105, RUF100
                c.send(("#TRACEBACK", traceback.format_exc()))
            except Exception:
                pass
            _info("Failure to send message: %r", msg)
            _info(" ... request was %r", request)
            _info(" ... exception was %r", e)


class Manager(_Server):
    _address: _Address
    _address2: _Address
    _this_address: Optional[_Address]
    _authkey: AuthenticationString

    def __init__(
        self,
        address: Union[_Address, None] = None,
        authkey: Union[bytes, str, None] = None,
    ) -> None:
        address = _resolve_address(address)[0] if address is None else address
        self._address = address
        self._address2 = _resolve_address()[0]  # Also create an address for the reverse connection
        self._this_address = None

        authkey = authkey.encode() if isinstance(authkey, str) else authkey
        authkey = process.current_process().authkey if authkey is None else authkey
        self._authkey = AuthenticationString(authkey)

        self._Listener, self._Client = connection.Listener, connection.Client

        self._registry_callback: dict[str, Callable] = {}
        self._registry_address: dict[str, _Address] = {}

    @property
    def _is_server(self) -> bool:
        return self._this_address == self._address

    @property
    def _is_client(self) -> bool:
        return self._this_address == self._address2

    def start(self, timeout: Union[float, None] = None) -> None:
        """Spawn a server process for this manager object"""
        assert self._this_address is None, "Manager already started"
        self.serve(address=self._address, authkey=self._authkey, timeout=timeout)  # Start the main server

        # Make a dummy call to the main server
        _, exc = conn_and_dispatch(self._address, self._authkey, "_dummy")
        if exc:
            raise exc
        self._this_address = self._address

    def connect(self, timeout: Union[float, None] = None) -> None:
        """Connect manager object to the server process"""
        assert self._this_address is None, "Manager already started"
        self.serve(address=self._address2, authkey=self._authkey, timeout=timeout)  # Start the callback server

        # Make a dummy call to the main server to make sure it is running
        _, exc = conn_and_dispatch(self._address, self._authkey, "_dummy")
        if exc:
            raise exc
        self._this_address = self._address2

    def start_or_connect(self, timeout: Union[float, None] = None, _depth: int = 0) -> None:
        """Start the server if we are the server, or connect to the server if we are the client"""
        assert self._this_address is None, "Manager already started"
        _debug(f"Starting or connecting to server. Depth: {_depth}")
        # Make a call to the server to see if it is running
        _, exc = conn_and_dispatch(self._address, self._authkey, "_dummy")

        if not exc:
            _debug("Server is running")
            # Server is running. Connect to it.
            self.connect(timeout=timeout)
        else:
            _debug("Server is not running")
            # Server is not running. Try to start it.
            try:
                if _depth == 0:
                    self.start(timeout=0.1)
                else:
                    self.start(timeout=timeout)
            except Exception as e:
                if isinstance(e, TimeoutError) and _depth == 0:
                    _info("Server start contention. Retrying.")
                else:
                    _info(f"Failed to start server. Retrying. Error: {e!r}")
                # Ups. We failed to start the server. This might happen if multiple processes
                # are trying to start the server at the same time.
                if _depth > 0:
                    raise
                self.start_or_connect(_depth=_depth + 1)

    def register(self, name: str, callable: Callable) -> bool:
        """Register a new callback on the server. Return the token."""
        assert self._this_address is not None, "Manager not started. Call start() or connect() first."

        if self._is_client:
            _debug(f"Registering '{name}'")

            # Register on the local
            self._registry_callback[name] = callable

            # Register on the server
            _, exc = conn_and_dispatch(self._address, self._authkey, "_register", (name, self._address2))
            if exc:
                # If we failed to register on the server, remove the local registration
                _info(f"Failed to register '{name}': {exc!r}")
                self._registry_callback.pop(name, None)
                return False

        else:
            _debug(f"Registering '{name}' locally")
            self._registry_callback[name] = callable

        return True

    def call(self, name: str, /, *args: Any, **kwds: Any) -> tuple[Any, bool]:
        """Attempt to call a callback"""
        assert self._this_address is not None, "Manager not started. Call start() or connect() first."

        callback = self._registry_callback.get(name)
        if callback:
            _debug(f"Calling '{name}' locally")
            return self._registry_callback[name](*args, **kwds), True

        address = self._registry_address.get(name)
        if address:
            _debug(f"Calling '{name}' at {address}")
            rv, exc = conn_and_dispatch(address, self._authkey, "_call", (name, *args), kwds)

            if exc:
                _info(f"Error calling '{name}': {exc!r}")
                self._registry_address.pop(name, None)  # XXX: call is broken. remove it.
                return None, False

            return rv, True

        if self._is_client:
            # Try to call the callback remotely
            _debug(f"Client calling '{name}' remotely")
            rv, _ = conn_and_dispatch(self._address, self._authkey, "_call2", (name, *args), kwds)
            return rv  # type: ignore

        # We are the server. We should know about all the callbacks. If we don't, the callback is not registered.
        _debug(f"Server does not know about '{name}'")
        return None, False

    public = ("_dummy", "_call", "_register", "_call2", "_shutdown")

    def _dummy(self, c: connection.Connection) -> None:
        pass

    def _call(self, c: connection.Connection, name: str, /, *args: Any, **kwds: Any) -> tuple[Any, bool]:
        """Called by the server to call a callback"""
        _debug(f"Client calling '{name}' with args: {args} and kwargs: {kwds}")
        if name not in self._registry_callback:
            raise ValueError(f"Callback {name!r} not found")
        return self._registry_callback[name](*args, **kwds)  # type: ignore

    def _call2(self, c: connection.Connection, name: str, /, *args: Any, **kwds: Any) -> tuple[Any, bool]:
        """Called by proxies and connected manager to call a callback"""
        return self.call(name, *args, **kwds)

    def _register(self, c: connection.Connection, name: str, address: _Address) -> None:
        """Called by the client to register a callback. Proxy needs another lever of indirection because
        it does not hold the registry of callbacks."""
        _debug(f"Server registering '{name}' at {address}")
        self._registry_address[name] = address

    @override
    def __reduce__(self) -> tuple[type, tuple, dict]:
        return (ManagerProxy, (self._address, bytes(self._authkey)), {})

    def __del__(self) -> None:
        try:  # noqa: SIM105, RUF100
            self.shutdown()
        except Exception:
            pass

    def __enter__(self) -> "Manager":
        return self

    def __exit__(self, *args: Any) -> None:
        self.shutdown()


class ManagerProxy:
    def __init__(self, address: _Address, authkey: bytes) -> None:
        self._address = address

        self._authkey = bytes(authkey) if authkey is not None else None
        self._Client = connection.Client

    def call(self, name: str, /, *args: Any, **kwds: Any) -> tuple[Any, bool]:
        """Attempt to call a callback on the server"""
        _debug(f"Proxy calling '{name}'")
        rv, _ = conn_and_dispatch(self._address, self._authkey, "_call2", (name, *args), kwds)
        return rv  # type: ignore

    def register(self, name: str, callable: Callable) -> None:
        raise RuntimeError("Cannot register a callback on a ManagerProxy")

    def start(self) -> None:
        raise RuntimeError("Cannot start a ManagerProxy. Start the main Manager object instead.")

    def connect(self) -> None:
        raise RuntimeError("Cannot connect a ManagerProxy. Connect the main Manager object instead.")


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
