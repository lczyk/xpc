"""
We want to start the app with the `python -m app.server --mode mock` command
Before that we want to register a cross-process callback which will be called periodically by the app
We can't modify the app code
"""

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
from multiprocessing.managers import BaseManager

from multiprocessing.process import AuthenticationString  # type: ignore
from typing import Any, Callable, Union

__version__ = "0.1.0"

__all__ = ["Manager"]


class _Server:
    _authkey: bytes
    listener: connection.Listener
    public: tuple[str, ...]

    def serve(self, forever: bool = True) -> None:
        """Run the server forever"""
        self.stop_event = threading.Event()
        process.current_process()._manager_server = self  # type: ignore
        try:
            accepter = threading.Thread(target=self.accepter)
            accepter.daemon = True
            accepter.start()
            if forever:
                try:
                    while not self.stop_event.is_set():
                        self.stop_event.wait(1)
                except (KeyboardInterrupt, SystemExit):
                    pass
        finally:
            if forever:
                if sys.stdout != sys.__stdout__:  # what about stderr?
                    util.debug("resetting stdout, stderr")
                    sys.stdout = sys.__stdout__
                    sys.stderr = sys.__stderr__
                sys.exit(0)

    def accepter(self) -> None:
        while True:
            try:
                c = self.listener.accept()
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
            pass
        finally:
            conn.close()

    def serve_forever(self) -> None:
        self.serve(forever=True)


class Server(_Server):
    """
    Server class which runs in a process controlled by a manager object
    """

    public = (
        "shutdown",
        "create",
        "has_callback",
        "register",
        "call",
        "dummy",
    )

    def __init__(
        self,
        _registry: dict[str, str] = {},  # XXX: unused
        address: Union[tuple[str, int], str, None] = None,
        authkey: Union[bytes, str] = b"",
        _serializer: str = "pickle",  # XXX: unused
    ):
        if not isinstance(authkey, bytes):
            raise TypeError(f"Authkey {authkey!r} is type {type(authkey)!s}, not bytes")
        if len(_registry) != 0:
            raise ValueError("Registry must be empty")
        if _serializer != "pickle":
            raise ValueError(f"Serializer {_serializer!r} not supported")

        self.registry: dict[str, str] = _registry
        self._authkey = AuthenticationString(authkey)

        # do authentication later
        self.listener = connection.Listener(address=address, backlog=128)
        self.address = self.listener.address

    def dummy(self, c: connection.Connection) -> None:
        pass

    def register(self, c: connection.Connection, name: str, address: str) -> None:
        self.registry[name] = address

    def shutdown(self, c: connection.Connection) -> None:
        """Shutdown this process"""
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
        if name not in self.registry:
            return None, False
        address = self.registry[name]
        conn = None
        try:
            conn = connection.Client(address, authkey=self._authkey)
            return dispatch(conn, None, "call2", (name, *args), kwds), True
        except Exception as e:
            util.info(f"Error calling {name}: {e}")
            # mpc is broken. Remove it.
            del self.registry[name]
            return None, False
        finally:
            if conn:
                conn.close()


class Manager(_Server):
    _Server = Server
    public = ("call2",)

    def __init__(
        self,
        address: Union[tuple[str, int], str, None] = None,
        authkey: Union[bytes, str, None] = None,
        ctx: Union[BaseContext, None] = None,
        *,
        shutdown_timeout: float = 1.0,
    ) -> None:
        if authkey is None:
            authkey = process.current_process().authkey
        self._address = address  # XXX not final address if eg ('', 0)
        self._authkey = AuthenticationString(authkey)
        self._state = State()
        self._state.value = State.INITIAL
        self._Listener, self._Client = connection.Listener, connection.Client
        self._ctx = ctx or get_context()
        if not hasattr(self._ctx, "Process"):
            raise ValueError("Context does not support Process objects")
        self._shutdown_timeout = shutdown_timeout
        self._serializer = "pickle"

        # NOTE: do authentication later
        self.listener = self._Listener(address=None, backlog=128)
        self.registry: dict[str, Callable] = {}

    def connect(self) -> None:
        """Connect manager object to the server process"""
        self.serve(forever=False)  # Start own server
        assert self._address is not None

        # Do a dummy call to check if the server is alive
        conn = connection.Client(self._address, authkey=self._authkey)
        self._state.value = State.STARTED
        try:
            dispatch(conn, None, "dummy")
        finally:
            conn.close()

    def start(
        self,
        initializer: Callable | None = None,
        initargs: tuple = (),
    ) -> None:
        """Spawn a server process for this manager object"""
        if self._state.value != State.INITIAL:
            if self._state.value == State.STARTED:
                raise ProcessError("Already started server")
            elif self._state.value == State.SHUTDOWN:
                raise ProcessError("Manager has shut down")
            else:
                raise ProcessError(f"Unknown state {self._state.value!r}")

        if initializer is not None and not callable(initializer):
            raise TypeError("initializer must be a callable")

        # pipe over which we will retrieve address of server
        reader, writer = connection.Pipe(duplex=False)

        # spawn process which runs a server
        self._process = self._ctx.Process(  # type: ignore
            target=type(self)._run_server,
            args=(self.address, self._authkey, writer, initializer, initargs),
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
            args=(self._process, self.address, self._authkey, self._state, self._Client, self._shutdown_timeout),
            exitpriority=0,
        )

    @classmethod
    def _run_server(
        cls,
        address: tuple[str, int] | str | None,
        authkey: bytes,
        writer: connection.Connection,
        initializer: Callable | None = None,
        initargs: tuple = (),
    ) -> None:
        """Create a server, report its address and run it"""
        # bpo-36368: protect server process from KeyboardInterrupt signals
        signal.signal(signal.SIGINT, signal.SIG_IGN)

        if initializer is not None:
            initializer(*initargs)

        # create server
        server = cls._Server({}, address, authkey, "pickle")

        # inform parent process of the server's address
        writer.send(server.address)
        writer.close()

        # run the manager
        util.info("manager serving at %r", server.address)
        server.serve(forever=True)

    def join(self, timeout: float | None = None) -> None:
        """Join the manager process (if it has been spawned)"""
        if self._process is not None:
            self._process.join(timeout)
            if not self._process.is_alive():
                self._process = None

    @staticmethod
    def _finalize_manager(
        process,
        address,
        authkey,
        state,
        _Client,
        shutdown_timeout,
    ):
        """Shutdown the manager process; will be registered as a finalizer"""
        if process.is_alive():
            util.info("sending shutdown message to manager")
            try:
                conn = _Client(address, authkey=authkey)
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

    @property
    def address(self):
        return self._address

    def register(self, name: str, callable: Callable) -> None:
        """Register a new callback on the server. Return the token."""
        assert self._state.value == State.STARTED, "server not yet started"
        # Register on the local
        self.registry[name] = callable
        # Register on the remote
        conn = self._Client(self._address, authkey=self._authkey)
        try:
            dispatch(conn, None, "register", (name, self.listener.address))
        finally:
            conn.close()

    def call(self, name: str, /, *args, **kwds) -> tuple[Any, bool]:
        assert self._state.value == State.STARTED, "server not yet started"
        conn = self._Client(self._address, authkey=self._authkey)
        try:
            return dispatch(conn, None, "call", (name, *args), kwds)
        finally:
            conn.close()

    def call2(self, c: connection.Connection, name: str, /, *args, **kwds):
        if name not in self.registry:
            raise ValueError(f"Callback {name!r} not found")
        return self.registry[name](*args, **kwds)


##=========================================================================================================
##
##  ##   ##   ####  ######  ####  ######  ####  ######  #####
##  ###  ##  ##  ##   ##     ##   ##       ##   ##      ##  ##
##  #### ##  ##  ##   ##     ##   #####    ##   #####   #####
##  ## ####  ##  ##   ##     ##   ##       ##   ##      ##  ##
##  ##  ###   ####    ##    ####  ##      ####  ######  ##   ##
##
##=========================================================================================================


class Notifier:
    """A class to send a notification about the completion of the setup."""

    def __init__(self, file_path: str | Path | None = None, systemd: bool = False) -> None:
        self.file_path: Path | None = None
        if file_path is not None:
            file_path = Path(file_path).resolve()
            file_path.unlink(missing_ok=True)
            self.file_path = file_path

        self._socket: socket.socket | None = None
        if systemd:
            try:
                self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
                addr = os.getenv("NOTIFY_SOCKET")
                # https://gist.github.com/grawity/6e5980981dccf66f554bbebb8cd169fc
                # _"If the first path byte is @, this means an "abstract" socket,
                # and you should change the 1st byte to 0x00 before using"_
                addr = "\0" + addr[1:] if addr[0] == "@" else addr  # type: ignore
                self._socket.connect(addr)  # type: ignore
            except Exception:
                self._socket = None

    def startup(self) -> None:
        """Notify that the setup is complete."""
        if self.file_path is not None:
            self._touch(self.file_path)

        if self._socket:
            self._socket.sendall(b"READY=1")

    def shutdown(self) -> None:
        if self.file_path is not None:
            self._touch(self.file_path)

        if self._socket:
            self._socket.sendall(b"STOPPING=1")

    @staticmethod
    def _touch(file_path: str | Path) -> None:
        file_path = Path(file_path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w") as f:
            f.write("")


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
