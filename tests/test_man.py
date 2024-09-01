import pickle

import pytest

from xpc import Manager


def test_start() -> None:
    man = Manager()
    man.start()


def test_picklable() -> None:
    man1 = Manager()
    man1.start()
    man2 = pickle.loads(pickle.dumps(man1))
    man3 = pickle.loads(pickle.dumps(man2))

    _, found = man1.call("hello")
    assert not found

    _, found = man2.call("hello")
    assert not found

    _, found = man3.call("hello")
    assert not found

    with pytest.raises(RuntimeError):
        man2.start()
