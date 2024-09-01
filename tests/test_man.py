import pickle

from xpc import Manager


def test_start() -> None:
    man = Manager()
    man.start()


def test_picklable() -> None:
    man1 = Manager(picklable=True)
    man2 = pickle.loads(pickle.dumps(man1))

    man1.start()
    man3 = pickle.loads(pickle.dumps(man1))

    _, found = man1.call("hello")
    assert not found

    _, found = man2.call("hello")
    assert not found

    _, found = man3.call("hello")
    assert not found

    man2.start()
