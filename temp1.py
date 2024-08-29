# We want to start the app with the `python -m app.server --mode mock` command
# Before that we want to register a cross-process callback which will be called periodically by the app
# We can't modify the app code

import signal
import sys
import threading
import time
from multiprocessing import connection, process, util
from multiprocessing.managers import (
    State,
    Token,
    dispatch,
    get_context,
)
from traceback import format_exc
from typing import Any

_missing = object()


class MyServer:
    """
    Server class which runs in a process controlled by a manager object
    """

    public = [
        "shutdown",
        "create",
        "has_callback",
        "register",
        "call",
        "register_manager",
    ]

    def __init__(self, address, authkey):
        if not isinstance(authkey, bytes):
            raise TypeError(f"Authkey {authkey!r} is type {type(authkey)!s}, not bytes")

        self.registry = {}
        self.authkey = process.AuthenticationString(authkey)
        Listener, _Client = connection.Listener, connection.Client

        # do authentication later
        self.listener = Listener(address=address, backlog=128)
        self.address = self.listener.address

        self._managers = set()

    def serve_forever(self):
        """Run the server forever"""
        self.stop_event = threading.Event()
        process.current_process()._manager_server = self
        try:
            accepter = threading.Thread(target=self.accepter)
            accepter.daemon = True
            accepter.start()
            try:
                while not self.stop_event.is_set():
                    self.stop_event.wait(1)
            except (KeyboardInterrupt, SystemExit):
                pass
        finally:
            if sys.stdout != sys.__stdout__:  # what about stderr?
                util.debug("resetting stdout, stderr")
                sys.stdout = sys.__stdout__
                sys.stderr = sys.__stderr__
            sys.exit(0)

    def accepter(self):
        while True:
            try:
                c = self.listener.accept()
            except OSError:
                continue
            t = threading.Thread(target=self.handle_request, args=(c,))
            t.daemon = True
            t.start()

    def _handle_request(self, c):
        request = None
        try:
            connection.deliver_challenge(c, self.authkey)
            connection.answer_challenge(c, self.authkey)
            request = c.recv()
            ignore, funcname, args, kwds = request
            assert funcname in self.public, f"{funcname!r} unrecognized"
            func = getattr(self, funcname)
        except Exception:
            msg = ("#TRACEBACK", format_exc())
        else:
            try:
                result = func(c, *args, **kwds)
            except Exception:
                msg = ("#TRACEBACK", format_exc())
            else:
                msg = ("#RETURN", result)

        try:
            c.send(msg)
        except Exception as e:
            try:
                c.send(("#TRACEBACK", format_exc()))
            except Exception:
                pass
            util.info("Failure to send message: %r", msg)
            util.info(" ... request was %r", request)
            util.info(" ... exception was %r", e)

    def handle_request(self, conn):
        """Handle a new connection"""
        try:
            self._handle_request(conn)
        except SystemExit:
            # Server.serve_client() calls sys.exit(0) on EOF
            pass
        finally:
            conn.close()

    def register(self, c, typeid, address, callback):
        if not hasattr(callback, "_mpc"):
            raise TypeError(f"Callback {callback!r} is not MultiprocessCallback")
        callback.address = address
        callback.authkey = self.authkey  # remote will have the same authkey as we do
        self.registry[typeid] = callback

    def register_manager(self, c, address):
        self._managers.add(address)

    # def fallback_getvalue(self, conn, ident, obj):
    #     return obj

    # def fallback_str(self, conn, ident, obj):
    #     return str(obj)

    # def fallback_repr(self, conn, ident, obj):
    #     return repr(obj)

    # fallback_mapping = {"__str__": fallback_str, "__repr__": fallback_repr, "#GETVALUE": fallback_getvalue}

    def shutdown(self, c):
        """Shutdown this process"""
        try:
            util.debug("manager received shutdown message")
            c.send(("#RETURN", None))
        except:
            import traceback

            traceback.print_exc()
        finally:
            self.stop_event.set()

    def call(self, c, typeid, /, *args, **kwds) -> tuple[Any, bool]:
        if typeid not in self.registry:
            return None, False
        mpc = self.registry[typeid]
        if not hasattr(mpc, "_mpc"):
            raise TypeError(f"Callback {mpc!r} is not MultiprocessCallback")
        try:
            value = mpc.call(*args, **kwds)
        except Exception:
            # mpc is broken. Remove it.
            del self.registry[typeid]
            return None, False
        return value, True


########################################################################################


class MultiprocessCallback:
    _mpc = True

    def __init__(self, name, callback):
        self.name = name
        self.callback = callback
        self.address = None
        self.authkey = None

    def __reduce__(self) -> str | tuple[Any, ...]:
        """Dont pickle the callback. We won't need it on the other side."""
        return (MultiprocessCallback, (self.name, None))

    def call(self, /, *args, **kwds):
        if self.callback:
            # We have the callback. Jsut call it.
            return self.callback(*args, **kwds)
        else:
            # We're on the remote. We need to call back to the originator.
            conn = connection.Client(self.address, authkey=self.authkey)
            try:
                return dispatch(conn, None, "call2", (self.name, *args), kwds)
            finally:
                conn.close()


class EndListener(Exception):
    pass


class MyManager:
    _Server = MyServer
    public = ["call2"]

    def __init__(self, address=None, authkey=None, ctx=None, *, shutdown_timeout=1.0):
        if authkey is None:
            authkey = process.current_process().authkey
        self._address = address  # XXX not final address if eg ('', 0)
        self._authkey = process.AuthenticationString(authkey)
        self._state = State()
        self._state.value = State.INITIAL
        self._Listener, self._Client = connection.Listener, connection.Client
        self._ctx = ctx or get_context()
        self._shutdown_timeout = shutdown_timeout

        # do authentication later
        self.listener = self._Listener(address=None, backlog=128)
        self._man_address = self.listener.address

        self.registry = {}

    def get_server(self):
        """
        Return server object with serve_forever() method and address attribute
        """
        if self._state.value != State.INITIAL:
            if self._state.value == State.STARTED:
                raise ProcessError("Already started server")
            elif self._state.value == State.SHUTDOWN:
                raise ProcessError("Manager has shut down")
            else:
                raise ProcessError(f"Unknown state {self._state.value!r}")
        return Server(self._address, self._authkey)

    def connect(self):
        """
        Connect manager object to the server process
        """
        self.serve()
        conn = connection.Client(self._address, authkey=self._authkey)
        self._state.value = State.STARTED

        try:
            dispatch(conn, None, "register_manager", (self._man_address,))
        finally:
            conn.close()

    def start(self, initializer=None, initargs=()):
        address = self._start(
            self.address,
            self._authkey,
            initializer,
            initargs,
        )
        self._address = address

    def _start(
        self,
        address,
        authkey,
        initializer=None,
        initargs=(),
    ):
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
        self._process = self._ctx.Process(
            target=type(self)._run_server,
            args=(address, authkey, writer, initializer, initargs),
        )
        ident = ":".join(str(i) for i in self._process._identity)
        self._process.name = type(self).__name__ + "-" + ident
        self._process.start()

        # get address of server
        writer.close()
        address = reader.recv()
        reader.close()

        # register a finalizer
        self._state.value = State.STARTED
        self.shutdown = util.Finalize(
            self,
            type(self)._finalize_manager,
            args=(self._process, address, authkey, self._state, self._Client, self._shutdown_timeout),
            exitpriority=0,
        )

        return address

    @classmethod
    def _run_server(cls, address, authkey, writer, initializer=None, initargs=()):
        """Create a server, report its address and run it"""
        # bpo-36368: protect server process from KeyboardInterrupt signals
        signal.signal(signal.SIGINT, signal.SIG_IGN)

        if initializer is not None:
            initializer(*initargs)

        # create server
        server = cls._Server(address, authkey)

        # inform parent process of the server's address
        writer.send(server.address)
        writer.close()

        # run the manager
        util.info("manager serving at %r", server.address)
        server.serve_forever()

    def join(self, timeout=None):
        """Join the manager process (if it has been spawned)"""
        if self._process is not None:
            self._process.join(timeout)
            if not self._process.is_alive():
                self._process = None

    @staticmethod
    def _finalize_manager(process, address, authkey, state, _Client, shutdown_timeout):
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

    def register_callback(self, typeid, callable):
        """Register a new callback on the server. Return the token."""
        assert self._state.value == State.STARTED, "server not yet started"
        # Register on the local
        self.registry[typeid] = callable
        # Register on the remote
        mpc = MultiprocessCallback(typeid, callable)
        conn = self._Client(self._address, authkey=self._authkey)
        try:
            id = dispatch(conn, None, "register", (typeid, self._man_address, mpc))
        finally:
            conn.close()
        return Token(typeid, self._address, id)

    def call(self, typeid, /, *args, **kwds) -> tuple[Any, bool]:
        assert self._state.value == State.STARTED, "server not yet started"
        conn = self._Client(self._address, authkey=self._authkey)
        try:
            return dispatch(conn, None, "call", (typeid, *args), kwds)
        finally:
            conn.close()

    def call2(self, c, name, /, *args, **kwds):
        if name not in self.registry:
            raise ValueError(f"Callback {name!r} not found")
        return self.registry[name](*args, **kwds)

    def _create(self, typeid, /, *args, **kwds):
        """
        Create a new shared object; return the token and exposed tuple
        """
        assert self._state.value == State.STARTED, "server not yet started"
        conn = self._Client(self._address, authkey=self._authkey)
        try:
            id, exposed = dispatch(conn, None, "create", (typeid, *args), kwds)
        finally:
            conn.close()
        token = Token(typeid, self._address, id), exposed
        return token

    # def listen(self):
    #     """Listen for callbacks"""
    #     while True:
    #         data = self._reader.recv()
    #         if isinstance(data, EndListener):
    #             break

    ############################################################################################################

    def serve(self):
        self.stop_event = threading.Event()
        process.current_process()._manager_server = self
        accepter = threading.Thread(target=self.accepter)
        accepter.daemon = True
        accepter.start()

    def accepter(self):
        while True:
            try:
                c = self.listener.accept()
            except OSError:
                continue
            t = threading.Thread(target=self.handle_request, args=(c,))
            t.daemon = True
            t.start()

    def _handle_request(self, c):
        request = None
        try:
            connection.deliver_challenge(c, self._authkey)
            connection.answer_challenge(c, self._authkey)
            request = c.recv()
            ignore, funcname, args, kwds = request
            assert funcname in self.public, f"{funcname!r} unrecognized"
            func = getattr(self, funcname)
        except Exception:
            msg = ("#TRACEBACK", format_exc())
        else:
            try:
                result = func(c, *args, **kwds)
            except Exception:
                # NOTE: We purposefully don't send the exception back to the client
                raise
            else:
                msg = ("#RETURN", result)

        try:
            c.send(msg)
        except Exception as e:
            try:
                c.send(("#TRACEBACK", format_exc()))
            except Exception:
                pass
            util.info("Failure to send message: %r", msg)
            util.info(" ... request was %r", request)
            util.info(" ... exception was %r", e)

    def handle_request(self, conn):
        """Handle a new connection"""
        try:
            self._handle_request(conn)
        except SystemExit:
            # Server.serve_client() calls sys.exit(0) on EOF
            pass
        finally:
            conn.close()


if __name__ == "__main__":
    import logging

    import colorlog

    handler = colorlog.StreamHandler()
    # Add date to the log format
    handler.setFormatter(colorlog.ColoredFormatter("%(asctime)s %(log_color)s%(levelname)s%(reset)s %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler])

    manager = MyManager(
        address=("localhost", 50000),
        authkey=b"password",
    )
    manager.start()

    try:
        while True:
            name = "my_callback"
            args = (1, 2, 3)
            kwargs = {"hello": "world"}
            logging.info(f"calling '{name}' with args: {args} and kwargs: {kwargs}")
            value, found = manager.call(name, *args, **kwargs)
            if found:
                logging.info(f"callback returned: {value}")
            else:
                logging.warning("callback not found")
            time.sleep(0.01)
    except KeyboardInterrupt:
        pass
