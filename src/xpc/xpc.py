"""
Single-file module for cross-process callbacks.

Hosted at https://github.com/MarcinKonowalczyk/xpc

We piggyback a bit on the BaseManager from the multiprocessing module, but we roll our own server class.
Written by Marcin Konowalczyk.
"""

import sys
import threading
import traceback
from multiprocessing import connection, process, util
from multiprocessing.context import BaseContext
from multiprocessing.managers import (  # type: ignore
    BaseManager,
    State,
    dispatch,
    get_context,
)
from multiprocessing.process import AuthenticationString  # type: ignore
from typing import TYPE_CHECKING, Any, Callable, Union

if TYPE_CHECKING:
    from typing_extensions import override
else:
    override = lambda x: x


__version__ = "0.2.0"

__all__ = ["Manager", "kill_multiprocessing_orphans"]


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


class Server(_Server):
    public = ("shutdown", "create", "has_callback", "register", "call", "dummy")

    def __init__(
        self,
        _registry: dict[str, str] = {},  # noqa: B006, XXX: unused
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

        self._registry: dict[str, str] = _registry
        self._authkey = AuthenticationString(authkey)

        # do authentication later
        self.listener = connection.Listener(address=address, backlog=128)
        self.address = self.listener.address

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
            del self._registry[name]
            return None, False
        finally:
            if conn:
                conn.close()

    def serve_forever(self) -> None:
        self.serve(forever=True)


class Manager(BaseManager, _Server):
    _Server = Server
    public = ("_call",)

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
        self._registry: dict[str, Callable] = {}

    @override
    def connect(self) -> None:
        """Connect manager object to the server process"""
        self.serve(forever=False)  # Start own server
        assert self._address is not None
        super().connect()

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
            dispatch(conn, None, "register", (name, self.listener.address))
        finally:
            conn.close()

    def call(self, name: str, /, *args: Any, **kwds: Any) -> tuple[Any, bool]:
        """Attempt to call a callback on the server"""
        assert self._state.value == State.STARTED, "server not yet started"
        assert self._address is not None
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
