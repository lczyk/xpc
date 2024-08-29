# We want to start the app with the `python -m app.server --mode mock` command
# Before that we want to register a cross-process callback which will be called periodically by the app
# We can't modify the app code

import multiprocessing
import multiprocessing.managers
import time
from multiprocessing.managers import (
    AutoProxy,
    State,
    Token,
    dispatch,
)
from typing import Callable


class MyServer(multiprocessing.managers.Server):
    public = [*multiprocessing.managers.Server.public, "register", "has_callback"]

    def register(self, c, typeid, /, *args, **kwds):
        """Register a new shared object type"""
        self.registry[typeid] = (args[0], None, None, None)

    def has_callback(self, c, typeid, /):
        return typeid in self.registry


class MyManager(multiprocessing.managers.BaseManager):
    _Server = MyServer

    def _register_callback(self, typeid, callable):
        """Register a new callback on the server. Return the token."""
        assert self._state.value == State.STARTED, "server not yet started"
        conn = self._Client(self._address, authkey=self._authkey)
        try:
            id = dispatch(conn, None, "register", (typeid, callable))
        finally:
            conn.close()
        return Token(typeid, self._address, id)

    def _has_callback(self, typeid):
        assert self._state.value == State.STARTED, "server not yet started"
        conn = self._Client(self._address, authkey=self._authkey)
        try:
            return dispatch(conn, None, "has_callback", (typeid,))
        finally:
            conn.close()

    def register_callback(
        self,
        typeid,
        callable: Callable,
    ) -> None:
        """Register a callback function to be sent to the server"""
        self._register_callback(typeid, callable)

    def has_callback(self, typeid):
        return self._has_callback(typeid)

    def _get_proxy(self, typeid):
        token, exp = self._create(typeid)
        proxy = AutoProxy(
            token,
            self._serializer,
            manager=self,
            authkey=self._authkey,
            exposed=exp,
        )
        conn = self._Client(token.address, authkey=self._authkey)
        dispatch(conn, None, "decref", (token.id,))
        return proxy

    def call(self, typeid):
        if not self.has_callback(typeid):
            return None
        return self._get_proxy(typeid)


if __name__ == "__main__":
    manager = MyManager(
        address=("localhost", 50000),
        authkey=b"password",
    )
    manager.start()

    # manager.register_callback("my_callback", my_callback)

    try:
        while True:
            try:
                value = manager.call("my_callback")
            except AttributeError:
                value = None
            print(f"value: {value}")
            time.sleep(1)
    except KeyboardInterrupt:
        pass
